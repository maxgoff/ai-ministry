"""FastAPI backend for AI Ministry."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio
from datetime import datetime

from . import storage
from .council import run_full_council, generate_conversation_title, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings
from .config import AVAILABLE_MODELS, AVAILABLE_PERSONAS, DEFAULT_MINISTRY_MODELS, DEFAULT_PRIME_MINISTER, DEFAULT_MODEL_PERSONAS
from .openrouter import query_model

app = FastAPI(title="AI Ministry API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "AI Ministry API"}


@app.get("/api/config")
async def get_config():
    """Get available models, personas, and default configuration."""
    return {
        "available_models": AVAILABLE_MODELS,
        "available_personas": AVAILABLE_PERSONAS,
        "default_ministry_models": DEFAULT_MINISTRY_MODELS,
        "default_prime_minister": DEFAULT_PRIME_MINISTER,
        "default_model_personas": DEFAULT_MODEL_PERSONAS,
    }


@app.get("/api/models/health")
async def check_models_health():
    """Check which models are currently healthy/available."""
    async def check_model(model: str) -> dict:
        """Check if a single model is healthy."""
        try:
            response = await query_model(
                model,
                [{"role": "user", "content": "Say OK"}],
                timeout=15.0
            )
            return {
                "model": model,
                "healthy": response is not None and response.get('content'),
                "error": None
            }
        except Exception as e:
            return {
                "model": model,
                "healthy": False,
                "error": str(e)
            }

    # Check all models in parallel
    tasks = [check_model(model) for model in AVAILABLE_MODELS]
    results = await asyncio.gather(*tasks)

    return {
        "models": results,
        "healthy_count": sum(1 for r in results if r["healthy"]),
        "total_count": len(results)
    }


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage ministry process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
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

    # Run the 3-stage ministry process
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content,
        ministry_models=ministry_models,
        model_personas=model_personas,
        prime_minister=prime_minister
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage ministry process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
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

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(
                request.content,
                ministry_models=ministry_models,
                model_personas=model_personas
            )
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(
                request.content,
                stage1_results,
                ministry_models=ministry_models
            )
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(
                request.content,
                stage1_results,
                stage2_results,
                prime_minister=prime_minister
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
async def export_conversation_markdown(conversation_id: str):
    """Export a conversation as Markdown."""
    conversation = storage.get_conversation(conversation_id)
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
async def export_conversation_pdf(conversation_id: str):
    """Export a conversation as PDF."""
    conversation = storage.get_conversation(conversation_id)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
