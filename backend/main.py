"""FastAPI backend for AI Ministry."""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, EmailStr
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio
from datetime import datetime

from . import storage
from .council import run_full_council, generate_conversation_title, stage0_research, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings
from . import config as cfg
from .config import AVAILABLE_MODELS, AVAILABLE_PERSONAS, DEFAULT_MINISTRY_MODELS, DEFAULT_PRIME_MINISTER, DEFAULT_MODEL_PERSONAS, DISCOVERY_CONFIG, RESEARCH_INTENT_ENABLED, RESEARCH_INTENT_MODEL
from .research_intent import should_research
from . import grounding
from .openrouter import query_model
from .auth import get_password_hash, verify_password, create_access_token, get_current_user
from . import trading_storage
from .trading_templates import get_templates_metadata
from .trading_council import run_trading_session
from .model_refresh import (
    run_refresh,
    effective_available_models,
    effective_defaults,
    get_active_registry,
)
from .model_registry import load_registry

app = FastAPI(title="AI Ministry API")

# Enable CORS for local development. The frontend port is chosen dynamically
# by start.sh (to dodge conflicts), so accept any localhost/127.0.0.1 port.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _boot_discovery():
    """
    Always run discovery in the background — startup must never block on
    network I/O (start.sh times out at 30s, and a fresh discovery cycle
    can take longer).

    When no registry exists yet, /api/config falls back to YAML defaults
    until the async refresh completes.

    Set ministry_config.yaml -> discovery.boot_refresh: off to skip entirely.
    """
    mode = DISCOVERY_CONFIG.get("boot_refresh", "async")
    if mode == "off" or not DISCOVERY_CONFIG.get("enabled", True):
        print("[Boot] discovery refresh skipped (config)")
        return

    print("[Boot] firing async discovery refresh (registry served from YAML defaults until done)")
    asyncio.create_task(_safe_refresh())


async def _safe_refresh():
    try:
        diff = await run_refresh()
        print(f"[Refresh] +{len(diff.added)} -{len(diff.removed)} succession={diff.succession} smoke_failures={len(diff.smoke_failures)}")
    except Exception as e:
        print(f"[Refresh] background refresh failed: {e}")


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class MinistryConfig(BaseModel):
    """Configuration for which models and personas to use."""
    ministry_models: Optional[List[str]] = None  # List of model IDs to use
    model_personas: Optional[Dict[str, str]] = None  # Model ID -> Persona ID mapping
    prime_minister: Optional[str] = None  # Model ID for synthesis


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    ministry_config: Optional[MinistryConfig] = None


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


# ============================================
# Authentication Models
# ============================================

class UserCreate(BaseModel):
    """Request to register a new user."""
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    """Request to login an existing user."""
    email: EmailStr
    password: str


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str


class User(BaseModel):
    """User response model (no password exposed)."""
    id: str
    email: str
    created_at: str


# ============================================
# Authentication Endpoints
# ============================================

@app.post("/api/auth/register", response_model=Token)
async def register(request: UserCreate):
    """
    Register a new user and return a JWT token.

    Creates a new user account with the provided email and password.
    Returns a JWT token on successful registration.

    Raises:
        HTTPException 400: If email already exists
    """
    # Check if user with this email already exists
    existing_user = storage.get_user_by_email(request.email)
    if existing_user is not None:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    # Hash the password
    hashed_password = get_password_hash(request.password)

    # Create user in database
    user_id = str(uuid.uuid4())
    user = storage.create_user(user_id, request.email, hashed_password)

    # Create JWT token
    access_token = create_access_token(data={"sub": user["id"]})

    return Token(access_token=access_token, token_type="bearer")


@app.post("/api/auth/login", response_model=Token)
async def login(request: UserLogin):
    """
    Authenticate a user and return a JWT token.

    Validates the provided email and password credentials.
    Returns a JWT token on successful authentication.

    Raises:
        HTTPException 401: If email doesn't exist or password is incorrect
    """
    # Check if user exists
    user = storage.get_user_by_email(request.email)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # Verify password
    if not verify_password(request.password, user["hashed_password"]):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # Create JWT token
    access_token = create_access_token(data={"sub": user["id"]})

    return Token(access_token=access_token, token_type="bearer")


@app.get("/api/auth/me", response_model=User)
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    Get the current authenticated user's profile.

    Requires a valid JWT token in the Authorization header.
    Returns the user's id, email, and created_at timestamp.

    Raises:
        HTTPException 401: If not authenticated or token is invalid
    """
    user_id = current_user.get("sub")
    user = storage.get_user_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found"
        )

    return User(
        id=user["id"],
        email=user["email"],
        created_at=user["created_at"]
    )


@app.get("/")
async def root():
    """
    Health check endpoint.

    This is a public endpoint that does not require authentication.
    Use this to verify the API service is running.

    Returns:
        dict: Status object with "ok" status and service name
    """
    return {"status": "ok", "service": "AI Ministry API"}


@app.get("/api/config")
async def get_config():
    """
    Get available models, personas, and default configuration.

    Reads from the live model registry (data/model_registry.json) when
    present so newly discovered models appear without a restart and evicted
    defaults are auto-promoted to their successors. Falls back to YAML
    defaults when no registry exists yet (e.g. first boot before discovery
    finishes).

    Returns:
        dict: Configuration containing available_models, available_personas,
              default_ministry_models, default_prime_minister, and default_model_personas
    """
    available = effective_available_models()
    ministry, personas, pm = effective_defaults()
    registry = get_active_registry()
    return {
        "available_models": available,
        "available_personas": AVAILABLE_PERSONAS,
        "default_ministry_models": ministry,
        "default_prime_minister": pm,
        "default_model_personas": personas,
        "registry_generated_at": registry.generated_at if registry else None,
    }


@app.post("/api/models/refresh")
async def refresh_models(current_user: dict = Depends(get_current_user)):
    """
    Trigger an on-demand model discovery + refresh cycle.

    Discovers each provider's current catalog, applies the current-generation
    policy, smoke-tests new entries, and writes the resulting registry to
    disk. Default ministry members and PM that get evicted are auto-promoted
    to their successors.

    Returns the diff so the UI can show what changed.
    """
    diff = await run_refresh()
    return diff.to_dict()


@app.get("/api/models/registry")
async def get_models_registry(current_user: dict = Depends(get_current_user)):
    """Return the current persisted registry contents (diagnostic UI)."""
    registry = get_active_registry()
    if registry is None:
        return {"generated_at": None, "models": [], "evicted": [], "succession": {}, "smoke_failures": []}
    return {
        "generated_at": registry.generated_at,
        "models": [
            {
                "id": m.id,
                "provider": m.provider,
                "family": m.family,
                "tier": m.tier,
                "version": m.version,
                "source": m.source,
                "pricing_completion": m.pricing_completion,
                "context_length": m.context_length,
                "smoke_tested_at": m.smoke_tested_at,
                "pinned": m.pinned,
            }
            for m in registry.models
        ],
        "evicted": [
            {"id": e.id, "reason": e.reason, "superseded_by": e.superseded_by}
            for e in registry.evicted
        ],
        "succession": registry.succession,
        "smoke_failures": registry.smoke_failures,
    }


@app.get("/api/models/health")
async def check_models_health(current_user: dict = Depends(get_current_user)):
    """
    Check which models are currently healthy/available.

    Requires a valid JWT token in the Authorization header.
    This endpoint consumes API credits by making test calls to each model.

    Raises:
        HTTPException 401: If not authenticated or token is invalid
    """
    # Reasoning models need longer timeouts for health checks
    REASONING_MODELS = {
        "openai/gpt-5.2", "openai/gpt-5.5",
        "google/gemma-4-31b", "google/gemma-4-26b-moe",
        "moonshot/kimi-k2.5", "nvidia/deepseek-v3.2",
        "xai/grok-4.20-0309-reasoning", "xai/grok-4-1-fast-reasoning",
    }

    async def check_model(model: str) -> dict:
        """Check if a single model is healthy."""
        try:
            timeout = 60.0 if model in REASONING_MODELS else 15.0
            response = await query_model(
                model,
                [{"role": "user", "content": "Say OK"}],
                timeout=timeout
            )
            return {
                "model": model,
                "healthy": response is not None and bool(response.get('content')),
                "error": None
            }
        except Exception as e:
            return {
                "model": model,
                "healthy": False,
                "error": str(e)
            }

    # Check all models in parallel — use live registry so newly discovered
    # models are reflected without a restart.
    models_to_check = effective_available_models()
    tasks = [check_model(model) for model in models_to_check]
    results = await asyncio.gather(*tasks)

    return {
        "models": results,
        "healthy_count": sum(1 for r in results if r["healthy"]),
        "total_count": len(results)
    }


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(current_user: dict = Depends(get_current_user)):
    """
    List all conversations for the current authenticated user.

    Requires a valid JWT token in the Authorization header.
    Returns only conversations owned by the authenticated user.

    Raises:
        HTTPException 401: If not authenticated or token is invalid
    """
    user_id = current_user.get("sub")
    return storage.list_conversations(user_id)


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new conversation for the current authenticated user.

    Requires a valid JWT token in the Authorization header.
    The new conversation is automatically associated with the authenticated user.

    Raises:
        HTTPException 401: If not authenticated or token is invalid
    """
    user_id = current_user.get("sub")
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id, user_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a specific conversation with all its messages.

    Requires a valid JWT token in the Authorization header.
    Returns 404 if conversation doesn't exist or is not owned by the user
    (prevents enumeration attacks).

    Raises:
        HTTPException 401: If not authenticated or token is invalid
        HTTPException 404: If conversation not found or not owned by user
    """
    user_id = current_user.get("sub")
    conversation = storage.get_conversation(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Send a message and run the 3-stage ministry process.
    Returns the complete response with all stages.

    Requires a valid JWT token in the Authorization header.
    Verifies that the authenticated user owns the conversation.
    Returns 404 if conversation doesn't exist or is not owned by user
    (prevents enumeration attacks).

    Critical: This endpoint consumes LLM API credits.

    Raises:
        HTTPException 401: If not authenticated or token is invalid
        HTTPException 404: If conversation not found or not owned by user
    """
    # Check if conversation exists and is owned by the authenticated user
    user_id = current_user.get("sub")
    conversation = storage.get_conversation(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Extract ministry config if provided
    ministry_models = None
    model_personas = None
    prime_minister = None
    if request.ministry_config:
        ministry_models = request.ministry_config.ministry_models
        model_personas = request.ministry_config.model_personas
        prime_minister = request.ministry_config.prime_minister

    # Run the full ministry process (Stage 0 research + 3-stage deliberation)
    stage0_briefing, stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content,
        ministry_models=ministry_models,
        model_personas=model_personas,
        prime_minister=prime_minister
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage0_briefing,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage0": stage0_briefing,
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Send a message and stream the 3-stage ministry process.
    Returns Server-Sent Events as each stage completes.

    Requires a valid JWT token in the Authorization header.
    Verifies that the authenticated user owns the conversation.
    Returns 404 if conversation doesn't exist or is not owned by user
    (prevents enumeration attacks).

    Critical: This endpoint consumes LLM API credits.

    Raises:
        HTTPException 401: If not authenticated or token is invalid
        HTTPException 404: If conversation not found or not owned by user
    """
    # Check if conversation exists and is owned by the authenticated user
    user_id = current_user.get("sub")
    conversation = storage.get_conversation(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Extract ministry config if provided
    ministry_models = None
    model_personas = None
    prime_minister = None
    if request.ministry_config:
        ministry_models = request.ministry_config.ministry_models
        model_personas = request.ministry_config.model_personas
        prime_minister = request.ministry_config.prime_minister

    async def event_generator():
        try:
            # Add user message
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 0: decide which grounding skills (web_search / url_reader /
            # code_exec) this query needs, then run them and merge into one
            # briefing. The decision is emitted before any skill runs so the UI
            # can show what's happening. Defaults toward grounding on failure.
            research_briefing = None
            decision = await grounding.decide(request.content)
            yield f"data: {json.dumps({'type': 'research_decision', 'data': {'needed': decision.needed, 'reason': decision.reason, 'skills': decision.skills}})}\n\n"

            if decision.needed:
                yield f"data: {json.dumps({'type': 'stage0_start', 'data': {'skills': decision.skills}})}\n\n"
                research_briefing = await grounding.run(request.content, decision)
                yield f"data: {json.dumps({'type': 'stage0_complete', 'data': research_briefing})}\n\n"

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(
                request.content,
                ministry_models=ministry_models,
                model_personas=model_personas,
                research_briefing=research_briefing,
            )
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(
                request.content,
                stage1_results,
                ministry_models=ministry_models,
                research_briefing=research_briefing,
            )
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(
                request.content,
                stage1_results,
                stage2_results,
                prime_minister=prime_minister,
                research_briefing=research_briefing,
            )
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id,
                research_briefing,
                stage1_results,
                stage2_results,
                stage3_result
            )

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


def _conversation_to_markdown(conversation: Dict[str, Any]) -> str:
    """Convert a conversation to Markdown format."""
    lines = []

    # Header
    lines.append(f"# {conversation['title']}")
    lines.append("")
    created = conversation.get('created_at', '')
    if created:
        try:
            dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            lines.append(f"*Exported from AI Ministry on {dt.strftime('%B %d, %Y')}*")
        except ValueError:
            lines.append(f"*Created: {created}*")
    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in conversation.get('messages', []):
        if msg['role'] == 'user':
            lines.append("## User")
            lines.append("")
            lines.append(msg['content'])
            lines.append("")

        elif msg['role'] == 'assistant':
            # Stage 0: Research Briefing
            stage0 = msg.get('stage0')
            if stage0:
                lines.append("## Research Briefing")
                lines.append("")
                lines.append(f"*Researched by {stage0.get('model', 'Grok')} on {stage0.get('date', '')}*")
                lines.append("")
                if stage0.get('key_facts'):
                    lines.append("### Key Facts")
                    lines.append("")
                    lines.append(stage0['key_facts'])
                    lines.append("")
                if stage0.get('summary'):
                    lines.append("### Summary")
                    lines.append("")
                    lines.append(stage0['summary'])
                    lines.append("")
                if stage0.get('citations'):
                    lines.append("### Sources")
                    lines.append("")
                    for citation in stage0['citations']:
                        url = citation.get('url', '')
                        title = citation.get('title', url)
                        if url:
                            lines.append(f"- [{title}]({url})")
                    lines.append("")

            # Stage 1: Individual Responses
            lines.append("## Ministry Responses")
            lines.append("")
            for response in msg.get('stage1', []):
                model = response.get('model', 'Unknown')
                content = response.get('response', '')
                lines.append(f"### {model}")
                lines.append("")
                lines.append(content)
                lines.append("")

            # Stage 2: Rankings (summarized)
            lines.append("## Peer Rankings")
            lines.append("")
            for ranking in msg.get('stage2', []):
                model = ranking.get('model', 'Unknown')
                parsed = ranking.get('parsed_ranking', [])
                if parsed:
                    lines.append(f"**{model}**: {' > '.join(parsed)}")
            lines.append("")

            # Stage 3: Final Synthesis
            lines.append("## Prime Minister's Synthesis")
            lines.append("")
            stage3 = msg.get('stage3', {})
            pm_model = stage3.get('model', 'Unknown')
            synthesis = stage3.get('response', '')
            lines.append(f"*Synthesized by {pm_model}*")
            lines.append("")
            lines.append(synthesis)
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


@app.get("/api/conversations/{conversation_id}/export/markdown")
async def export_conversation_markdown(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Export a conversation as Markdown.

    Requires a valid JWT token in the Authorization header.
    Verifies that the authenticated user owns the conversation.
    Returns 404 if conversation doesn't exist or is not owned by user
    (prevents enumeration attacks).

    Raises:
        HTTPException 401: If not authenticated or token is invalid
        HTTPException 404: If conversation not found or not owned by user
    """
    user_id = current_user.get("sub")
    conversation = storage.get_conversation(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    markdown = _conversation_to_markdown(conversation)

    # Generate filename from title
    safe_title = "".join(c if c.isalnum() or c in ' -_' else '' for c in conversation['title'])
    safe_title = safe_title.strip().replace(' ', '_')[:50] or 'conversation'
    filename = f"{safe_title}.md"

    return Response(
        content=markdown,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@app.get("/api/conversations/{conversation_id}/export/pdf")
async def export_conversation_pdf(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Export a conversation as PDF.

    Requires a valid JWT token in the Authorization header.
    Verifies that the authenticated user owns the conversation.
    Returns 404 if conversation doesn't exist or is not owned by user
    (prevents enumeration attacks).

    Raises:
        HTTPException 401: If not authenticated or token is invalid
        HTTPException 404: If conversation not found or not owned by user
        HTTPException 501: If fpdf2 package is not installed
    """
    user_id = current_user.get("sub")
    conversation = storage.get_conversation(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        from fpdf import FPDF
        import re

        def normalize_text(text: str) -> str:
            """Replace Unicode characters with ASCII equivalents for PDF."""
            replacements = {
                '"': '"', '"': '"', ''': "'", ''': "'",
                '–': '-', '—': '-', '…': '...',
                '•': '*', '→': '->', '←': '<-',
                '≥': '>=', '≤': '<=', '≠': '!=',
                '\u00a0': ' ',  # Non-breaking space
            }
            for old, new in replacements.items():
                text = text.replace(old, new)
            # Remove any remaining non-ASCII characters
            return text.encode('ascii', 'ignore').decode('ascii')

        class PDF(FPDF):
            def header(self):
                self.set_font('Helvetica', 'B', 10)
                self.set_text_color(100, 100, 100)
                self.cell(0, 10, 'AI Ministry Export', align='R')
                self.ln(10)

            def footer(self):
                self.set_y(-15)
                self.set_font('Helvetica', 'I', 8)
                self.set_text_color(128, 128, 128)
                self.cell(0, 10, f'Page {self.page_no()}', align='C')

        pdf = PDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Title
        pdf.set_font('Helvetica', 'B', 20)
        pdf.set_text_color(44, 62, 80)
        pdf.multi_cell(0, 10, normalize_text(conversation['title']))
        pdf.ln(5)

        # Date
        pdf.set_font('Helvetica', 'I', 10)
        pdf.set_text_color(128, 128, 128)
        created = conversation.get('created_at', '')
        if created:
            try:
                dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                pdf.cell(0, 10, f"Exported on {dt.strftime('%B %d, %Y')}")
            except ValueError:
                pdf.cell(0, 10, f"Created: {created}")
        pdf.ln(10)

        # Horizontal line
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(10)

        for msg in conversation.get('messages', []):
            if msg['role'] == 'user':
                # User message
                pdf.set_font('Helvetica', 'B', 14)
                pdf.set_text_color(52, 73, 94)
                pdf.cell(0, 10, 'User')
                pdf.ln(8)

                pdf.set_font('Helvetica', '', 11)
                pdf.set_text_color(0, 0, 0)
                # Clean markdown formatting for PDF
                content = msg['content']
                content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)  # Remove bold
                content = re.sub(r'\*(.+?)\*', r'\1', content)  # Remove italic
                pdf.multi_cell(0, 6, normalize_text(content))
                pdf.ln(10)

            elif msg['role'] == 'assistant':
                # Stage 0: Research Briefing
                stage0 = msg.get('stage0')
                if stage0:
                    pdf.set_font('Helvetica', 'B', 14)
                    pdf.set_text_color(0, 128, 128)
                    pdf.cell(0, 10, 'Research Briefing')
                    pdf.ln(8)

                    pdf.set_font('Helvetica', 'I', 10)
                    pdf.set_text_color(128, 128, 128)
                    pdf.cell(0, 6, f"Researched by {stage0.get('model', 'Grok')} on {stage0.get('date', '')}")
                    pdf.ln(6)

                    if stage0.get('key_facts'):
                        pdf.set_font('Helvetica', 'B', 11)
                        pdf.set_text_color(0, 100, 100)
                        pdf.cell(0, 8, 'Key Facts')
                        pdf.ln(6)
                        pdf.set_font('Helvetica', '', 10)
                        pdf.set_text_color(0, 0, 0)
                        pdf.multi_cell(0, 5, normalize_text(stage0['key_facts']))
                        pdf.ln(6)

                    if stage0.get('summary'):
                        pdf.set_font('Helvetica', 'B', 11)
                        pdf.set_text_color(0, 100, 100)
                        pdf.cell(0, 8, 'Summary')
                        pdf.ln(6)
                        pdf.set_font('Helvetica', '', 10)
                        pdf.set_text_color(0, 0, 0)
                        pdf.multi_cell(0, 5, normalize_text(stage0['summary']))
                        pdf.ln(8)

                # Stage 1
                pdf.set_font('Helvetica', 'B', 14)
                pdf.set_text_color(52, 73, 94)
                pdf.cell(0, 10, 'Ministry Responses')
                pdf.ln(8)

                for response in msg.get('stage1', []):
                    model = response.get('model', 'Unknown')
                    content = response.get('response', '')

                    pdf.set_font('Helvetica', 'B', 12)
                    pdf.set_text_color(74, 144, 226)
                    pdf.cell(0, 8, model)
                    pdf.ln(6)

                    pdf.set_font('Helvetica', '', 10)
                    pdf.set_text_color(0, 0, 0)
                    # Clean and truncate content for PDF
                    content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
                    content = re.sub(r'\*(.+?)\*', r'\1', content)
                    content = re.sub(r'```[\s\S]*?```', '[code block]', content)
                    if len(content) > 2000:
                        content = content[:2000] + '... [truncated]'
                    pdf.multi_cell(0, 5, normalize_text(content))
                    pdf.ln(8)

                # Stage 2 Summary
                pdf.set_font('Helvetica', 'B', 14)
                pdf.set_text_color(52, 73, 94)
                pdf.cell(0, 10, 'Peer Rankings')
                pdf.ln(8)

                pdf.set_font('Helvetica', '', 10)
                pdf.set_text_color(0, 0, 0)
                for ranking in msg.get('stage2', []):
                    model = ranking.get('model', 'Unknown')
                    parsed = ranking.get('parsed_ranking', [])
                    if parsed:
                        ranking_text = normalize_text(f"{model}: {' > '.join(parsed)}")
                        # Use cell for single line, add line break manually
                        pdf.cell(0, 6, ranking_text[:100])  # Truncate if too long
                        pdf.ln(6)
                pdf.ln(10)

                # Stage 3
                pdf.set_font('Helvetica', 'B', 14)
                pdf.set_text_color(52, 73, 94)
                pdf.cell(0, 10, "Prime Minister's Synthesis")
                pdf.ln(8)

                stage3 = msg.get('stage3', {})
                pm_model = stage3.get('model', 'Unknown')
                synthesis = stage3.get('response', '')

                pdf.set_font('Helvetica', 'I', 10)
                pdf.set_text_color(128, 128, 128)
                pdf.cell(0, 6, f"Synthesized by {pm_model}")
                pdf.ln(6)

                pdf.set_font('Helvetica', '', 10)
                pdf.set_text_color(0, 0, 0)
                synthesis = re.sub(r'\*\*(.+?)\*\*', r'\1', synthesis)
                synthesis = re.sub(r'\*(.+?)\*', r'\1', synthesis)
                synthesis = re.sub(r'```[\s\S]*?```', '[code block]', synthesis)
                pdf.multi_cell(0, 5, normalize_text(synthesis))
                pdf.ln(10)

            # Separator
            pdf.set_draw_color(200, 200, 200)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(10)

        # Generate PDF bytes
        pdf_bytes = pdf.output()

        # Generate filename
        safe_title = "".join(c if c.isalnum() or c in ' -_' else '' for c in conversation['title'])
        safe_title = safe_title.strip().replace(' ', '_')[:50] or 'conversation'
        filename = f"{safe_title}.pdf"

        return Response(
            content=bytes(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="PDF export requires 'fpdf2' package. Install with: pip install fpdf2"
        )


# ============================================
# Trading Advisory Models
# ============================================

class TradingSettingsRequest(BaseModel):
    """Global trading settings."""
    watchlist: Optional[str] = None
    account_size: Optional[str] = None
    open_positions: Optional[str] = None
    risk_tolerance: Optional[str] = None
    risk_per_trade: Optional[str] = None
    trading_style: Optional[str] = None
    markets: Optional[str] = None


class TradingSessionRequest(BaseModel):
    """Request to create and run a trading session."""
    selected_traders: List[str]
    trader_fields: Dict[str, Dict[str, str]] = {}
    global_settings: Dict[str, Any] = {}
    ministry_config: Optional[MinistryConfig] = None


# ============================================
# Trading Advisory Endpoints
# ============================================

@app.get("/api/trading/templates")
async def get_trading_templates():
    """Get trader metadata and field definitions (public, no auth required)."""
    return get_templates_metadata()


@app.get("/api/trading/settings")
async def get_trading_settings(current_user: dict = Depends(get_current_user)):
    """Get the current user's saved global trading settings."""
    user_id = current_user.get("sub")
    return trading_storage.get_trading_settings(user_id)


@app.put("/api/trading/settings")
async def save_trading_settings(
    request: TradingSettingsRequest,
    current_user: dict = Depends(get_current_user),
):
    """Save the current user's global trading settings."""
    user_id = current_user.get("sub")
    settings = {k: v for k, v in request.model_dump().items() if v is not None}
    trading_storage.save_trading_settings(user_id, settings)
    return {"status": "ok"}


@app.get("/api/trading/sessions")
async def list_trading_sessions(current_user: dict = Depends(get_current_user)):
    """List all trading sessions for the current user."""
    user_id = current_user.get("sub")
    return trading_storage.list_trading_sessions(user_id)


@app.get("/api/trading/sessions/{session_id}")
async def get_trading_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get a full trading session with all analyses and master synthesis."""
    user_id = current_user.get("sub")
    session = trading_storage.get_trading_session(session_id, user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trading session not found")
    return session


@app.post("/api/trading/sessions/stream")
async def stream_trading_session(
    request: TradingSessionRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create and run a trading session with SSE streaming.

    Runs each selected trader through the full 4-stage ministry pipeline,
    then auto-synthesizes via the master trader if 2+ traders selected.
    """
    user_id = current_user.get("sub")

    # Extract ministry config
    ministry_models = None
    model_personas = None
    prime_minister = None
    if request.ministry_config:
        ministry_models = request.ministry_config.ministry_models
        model_personas = request.ministry_config.model_personas
        prime_minister = request.ministry_config.prime_minister

    return StreamingResponse(
        run_trading_session(
            user_id=user_id,
            selected_traders=request.selected_traders,
            trader_fields=request.trader_fields,
            global_settings=request.global_settings,
            ministry_models=ministry_models,
            model_personas=model_personas,
            prime_minister=prime_minister,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
