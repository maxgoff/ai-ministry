"""3-stage AI Ministry orchestration with optional Stage 0 research."""

from datetime import date
from typing import List, Dict, Any, Tuple, Optional
from .openrouter import query_models_parallel, query_model
from .config import (
    COUNCIL_MODELS, CHAIRMAN_MODEL, MODEL_PERSONAS, AVAILABLE_PERSONAS,
    DEFAULT_MODEL_PERSONAS, XAI_API_KEY, RESEARCHER_ENABLED,
    RESEARCHER_MODEL, RESEARCHER_TIMEOUT,
    RESEARCHER_FALLBACK_ENABLED, RESEARCHER_FALLBACK_MODEL,
)
from .researcher import run_research


async def stage0_research(user_query: str) -> Optional[Dict[str, Any]]:
    """
    Stage 0: Run web research to ground the ministry in current facts.

    Tries xAI first, falls back to DuckDuckGo + LLM synthesis (no API key
    required) if xAI fails or XAI_API_KEY is unset. Returns the briefing
    dict, or None if research is disabled / both paths fail.
    """
    if not RESEARCHER_ENABLED:
        print("[Stage 0] Researcher disabled in config.")
        return None

    if not XAI_API_KEY and not RESEARCHER_FALLBACK_ENABLED:
        print("[Stage 0] No XAI_API_KEY and fallback disabled — skipping research.")
        return None

    try:
        briefing = await run_research(
            user_query,
            api_key=XAI_API_KEY,
            timeout=float(RESEARCHER_TIMEOUT),
            model=RESEARCHER_MODEL,
            fallback_enabled=RESEARCHER_FALLBACK_ENABLED,
            fallback_model=RESEARCHER_FALLBACK_MODEL,
        )
        if briefing:
            source = briefing.get('model', 'unknown')
            n_cites = len(briefing.get('citations', []))
            print(f"[Stage 0] Research complete via {source}: {n_cites} citations")
        else:
            print("[Stage 0] Research returned empty result from all sources.")
        return briefing
    except Exception as e:
        print(f"[Stage 0] Research failed: {e}")
        return None


def _build_research_context(research_briefing: Optional[Dict[str, Any]]) -> str:
    """Build the research context block to inject into prompts."""
    today = date.today().strftime("%B %d, %Y")
    parts = [f"Today's date is {today}."]

    if research_briefing:
        parts.append("")
        parts.append("RESEARCH BRIEFING (verified via web search):")
        if research_briefing.get("key_facts"):
            parts.append(f"\nKey Facts:\n{research_briefing['key_facts']}")
        if research_briefing.get("summary"):
            parts.append(f"\nSummary:\n{research_briefing['summary']}")
        if research_briefing.get("citations"):
            urls = [c.get("url", "") for c in research_briefing["citations"] if c.get("url")]
            if urls:
                parts.append(f"\nSources: {', '.join(urls[:10])}")
        parts.append("")
        parts.append("Do not contradict verified facts above. If you disagree with any finding, explain why.")

    return "\n".join(parts)


def _build_scaffolded_prompt(
    user_query: str,
    model: str,
    model_personas: Optional[Dict[str, str]] = None,
    research_briefing: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a scaffolded prompt with persona for a specific model.

    Uses role cycling + scaffolding techniques for higher-order reasoning.

    Args:
        user_query: The user's question
        model: The model identifier
        model_personas: Optional mapping of model -> persona_id
        research_briefing: Optional Stage 0 research briefing
    """
    # Use custom persona mapping if provided
    if model_personas and model in model_personas:
        persona_id = model_personas[model]
        persona = AVAILABLE_PERSONAS.get(persona_id, {
            "name": "Ministry Member",
            "instruction": "You provide thoughtful, well-reasoned analysis."
        })
    else:
        # Fall back to legacy MODEL_PERSONAS format
        persona = MODEL_PERSONAS.get(model, {
            "name": "Ministry Member",
            "instruction": "You provide thoughtful, well-reasoned analysis."
        })

    research_context = _build_research_context(research_briefing)

    return f"""You are the {persona['name']} on an expert ministry. {persona['instruction']}

{research_context}

Question: {user_query}

Before providing your answer:
1. Briefly outline your analytical approach (2-3 sentences explaining how you'll tackle this)
2. Then provide your complete, detailed response

Your analysis:"""


async def stage1_collect_responses(
    user_query: str,
    ministry_models: Optional[List[str]] = None,
    model_personas: Optional[Dict[str, str]] = None,
    research_briefing: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all ministry models.

    Uses scaffolded prompts with unique personas for each model to maximize
    perspective diversity (role cycling technique).

    Args:
        user_query: The user's question
        ministry_models: Optional list of models to use (defaults to COUNCIL_MODELS)
        model_personas: Optional mapping of model -> persona_id
        research_briefing: Optional Stage 0 research briefing

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    import asyncio

    models_to_use = ministry_models or COUNCIL_MODELS

    async def query_with_persona(model: str) -> tuple:
        """Query a single model with its personalized prompt."""
        prompt = _build_scaffolded_prompt(user_query, model, model_personas, research_briefing)
        messages = [{"role": "user", "content": prompt}]
        response = await query_model(model, messages)
        return model, response

    # Query all models in parallel with their personalized prompts
    tasks = [query_with_persona(model) for model in models_to_use]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Format results
    stage1_results = []
    for result in results:
        if isinstance(result, Exception):
            continue  # Skip failed models
        model, response = result
        if response is not None:  # Only include successful responses
            stage1_results.append({
                "model": model,
                "response": response.get('content', '')
            })

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    ministry_models: Optional[List[str]] = None,
    research_briefing: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1
        ministry_models: Optional list of models to use for ranking
        research_briefing: Optional Stage 0 research briefing

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    models_to_use = ministry_models or COUNCIL_MODELS

    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    # Build research context for factual accuracy assessment
    research_context = _build_research_context(research_briefing)

    ranking_prompt = f"""{research_context}

You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Assess factual accuracy — responses that align with the verified research facts should be ranked higher.
3. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all ministry models in parallel
    responses = await query_models_parallel(models_to_use, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed
            })

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    prime_minister: Optional[str] = None,
    research_briefing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Stage 3: Prime Minister synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2
        prime_minister: Optional model to use for synthesis (defaults to CHAIRMAN_MODEL)
        research_briefing: Optional Stage 0 research briefing

    Returns:
        Dict with 'model' and 'response' keys
    """
    pm_model = prime_minister or CHAIRMAN_MODEL

    # Build comprehensive context for prime minister
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
    ])

    # Build Stage 0 section for PM prompt
    stage0_section = ""
    if research_briefing:
        stage0_parts = ["STAGE 0 - Research Briefing (verified via web search):"]
        if research_briefing.get("key_facts"):
            stage0_parts.append(f"\nKey Facts:\n{research_briefing['key_facts']}")
        if research_briefing.get("summary"):
            stage0_parts.append(f"\nSummary:\n{research_briefing['summary']}")
        if research_briefing.get("citations"):
            urls = [c.get("url", "") for c in research_briefing["citations"] if c.get("url")]
            if urls:
                stage0_parts.append(f"\nSources: {', '.join(urls[:10])}")
        stage0_section = "\n".join(stage0_parts) + "\n\n"

    research_context = _build_research_context(research_briefing)

    pm_prompt = f"""{research_context}

You are the Prime Minister of an AI Ministry. Multiple AI models—each with a distinct analytical perspective—have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

{stage0_section}STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

Your task as Prime Minister is to synthesize all of this information into a single, comprehensive answer that represents the ministry's collective wisdom.

YOUR SYNTHESIS MUST INCLUDE:
1. **Clear Structure**: Use sections, headers, or bullet points to organize complex topics
2. **Actionable Insights**: Provide specific, implementable recommendations where applicable
3. **Trade-off Acknowledgment**: Note key trade-offs or areas where ministry members disagreed
4. **Unified Conclusion**: End with a clear, definitive recommendation or takeaway

Consider:
- The unique perspectives each ministry member brought (analytical, systems, principled, deep analysis)
- The peer rankings and what they reveal about response quality
- Patterns of agreement that indicate high-confidence conclusions
- Areas of disagreement that warrant nuanced discussion

Provide your synthesized answer:"""

    messages = [{"role": "user", "content": pm_prompt}]

    # Query the prime minister model
    response = await query_model(pm_model, messages)

    if response is None:
        # Fallback if prime minister fails
        return {
            "model": pm_model,
            "response": "Error: Unable to generate final synthesis."
        }

    return {
        "model": pm_model,
        "response": response.get('content', '')
    }


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use gemini-2.5-flash for title generation (fast and cheap)
    response = await query_model("google/gemini-2.5-flash", messages, timeout=30.0)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


async def run_full_council(
    user_query: str,
    ministry_models: Optional[List[str]] = None,
    model_personas: Optional[Dict[str, str]] = None,
    prime_minister: Optional[str] = None
) -> Tuple[Optional[Dict], List, List, Dict, Dict]:
    """
    Run the complete ministry process (Stage 0 research + 3-stage deliberation).

    Args:
        user_query: The user's question
        ministry_models: Optional list of models to use
        model_personas: Optional mapping of model -> persona_id
        prime_minister: Optional model for final synthesis

    Returns:
        Tuple of (stage0_briefing, stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 0: Research (graceful failure returns None)
    stage0_briefing = await stage0_research(user_query)

    # Stage 1: Collect individual responses
    stage1_results = await stage1_collect_responses(
        user_query,
        ministry_models=ministry_models,
        model_personas=model_personas,
        research_briefing=stage0_briefing,
    )

    # If no models responded successfully, return error
    if not stage1_results:
        return stage0_briefing, [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

    # Stage 2: Collect rankings
    stage2_results, label_to_model = await stage2_collect_rankings(
        user_query,
        stage1_results,
        ministry_models=ministry_models,
        research_briefing=stage0_briefing,
    )

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        prime_minister=prime_minister,
        research_briefing=stage0_briefing,
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings
    }

    return stage0_briefing, stage1_results, stage2_results, stage3_result, metadata
