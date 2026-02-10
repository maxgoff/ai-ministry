"""Stage 0 Researcher: Web search grounding via xAI Responses API.

Uses Grok's web_search tool through xAI's Responses API (/v1/responses)
to produce a structured briefing that grounds all subsequent ministry
stages in current, verified facts.
"""

import asyncio
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

# Retry configuration (mirrors openrouter.py pattern)
MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_DELAY = 30.0
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"


def _is_retryable_error(error: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    if isinstance(error, httpx.TimeoutException):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in RETRYABLE_STATUS_CODES
    if isinstance(error, (httpx.ConnectError, httpx.ReadError)):
        return True
    return False


def _build_researcher_prompt(user_query: str) -> str:
    """Build the researcher system+user prompt with today's date."""
    today = date.today().strftime("%B %d, %Y")
    return f"""Today's date is {today}.

You are a research assistant preparing a factual briefing for a panel of AI analysts.
Search the web to find current, accurate information relevant to the following question.

Question: {user_query}

Produce your response in EXACTLY this format with these two markdown headers:

## KEY FACTS
- 3 to 8 bullet points of verified facts, each with a date or source where possible
- Focus on the most recent and relevant information
- Include specific numbers, names, dates when available

## RESEARCH SUMMARY
2 to 4 paragraphs providing context, background, and analysis of the current situation.
Synthesize what you found into a coherent narrative that will help analysts understand
the current state of affairs on this topic."""


async def _query_xai_responses(
    api_key: str,
    user_content: str,
    timeout: float = 120.0,
    model: str = "grok-4-1-fast",
) -> Dict[str, Any]:
    """
    Direct POST to xAI Responses API with web_search tool.

    Returns the raw JSON response dict.
    Raises on HTTP errors (caller handles retries).
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "input": [
            {"role": "user", "content": user_content},
        ],
        "tools": [{"type": "web_search"}],
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            XAI_RESPONSES_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def _parse_xai_response(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract structured data from xAI Responses API output.

    Returns dict with keys: text, citations, search_queries
    """
    text_parts: List[str] = []
    search_queries: List[str] = []

    for item in raw.get("output", []):
        item_type = item.get("type", "")

        # Extract text content from message items
        if item_type == "message":
            for content_block in item.get("content", []):
                if content_block.get("type") == "output_text":
                    text_parts.append(content_block.get("text", ""))

        # Extract search queries from web_search_call items
        elif item_type == "web_search_call":
            query = item.get("query", "") or item.get("search_query", "")
            if query:
                search_queries.append(query)

    # Citations are at the top level in xAI responses
    citations: List[Dict[str, str]] = []
    for citation in raw.get("citations", []):
        entry = {}
        if "url" in citation:
            entry["url"] = citation["url"]
        if "title" in citation:
            entry["title"] = citation["title"]
        if entry:
            citations.append(entry)

    return {
        "text": "\n".join(text_parts).strip(),
        "citations": citations,
        "search_queries": search_queries,
    }


def _format_briefing(
    parsed: Dict[str, Any],
    user_query: str,
    model: str,
) -> Optional[Dict[str, Any]]:
    """
    Split parsed text on section headers and return structured briefing.

    Returns None if text is empty.
    """
    text = parsed.get("text", "")
    if not text:
        return None

    today = date.today().isoformat()
    key_facts = ""
    summary = ""

    # Try to split on section headers
    if "## KEY FACTS" in text and "## RESEARCH SUMMARY" in text:
        parts = text.split("## RESEARCH SUMMARY")
        facts_section = parts[0]
        summary = parts[1].strip() if len(parts) > 1 else ""

        # Extract just the facts content after the header
        if "## KEY FACTS" in facts_section:
            key_facts = facts_section.split("## KEY FACTS")[1].strip()
    elif "## KEY FACTS" in text:
        key_facts = text.split("## KEY FACTS")[1].strip()
        summary = ""
    elif "## RESEARCH SUMMARY" in text:
        summary = text.split("## RESEARCH SUMMARY")[1].strip()
        key_facts = ""
    else:
        # No recognizable headers — use full text as summary
        summary = text
        key_facts = ""

    return {
        "query": user_query,
        "date": today,
        "key_facts": key_facts,
        "summary": summary,
        "full_text": text,
        "citations": parsed.get("citations", []),
        "search_queries": parsed.get("search_queries", []),
        "model": model,
    }


async def run_research(
    user_query: str,
    api_key: str,
    timeout: float = 120.0,
    model: str = "grok-4-1-fast",
) -> Optional[Dict[str, Any]]:
    """
    Public entry point: run web research and return a structured briefing.

    Returns a briefing dict or None on failure.
    Implements exponential backoff retry logic.
    """
    user_content = _build_researcher_prompt(user_query)
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            raw = await _query_xai_responses(
                api_key, user_content, timeout=timeout, model=model
            )
            parsed = _parse_xai_response(raw)
            briefing = _format_briefing(parsed, user_query, model)
            return briefing

        except Exception as e:
            last_error = e

            if attempt < MAX_RETRIES and _is_retryable_error(e):
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                print(
                    f"[Researcher] Attempt {attempt + 1}/{MAX_RETRIES + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                break

    print(f"[Researcher] Failed after {MAX_RETRIES + 1} attempts: {last_error}")
    return None
