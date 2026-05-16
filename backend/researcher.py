"""Stage 0 Researcher: Web search grounding via xAI Responses API.

Uses Grok's web_search tool through xAI's Responses API (/v1/responses)
to produce a structured briefing that grounds all subsequent ministry
stages in current, verified facts.
"""

import asyncio
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from .openrouter import query_model

# Retry configuration (mirrors openrouter.py pattern)
MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_DELAY = 30.0
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"
DEFAULT_FALLBACK_MODEL = "google/gemini-2.5-flash"


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


async def _try_xai(
    user_query: str,
    api_key: str,
    timeout: float,
    model: str,
) -> Optional[Dict[str, Any]]:
    """Run xAI Responses with retries. Returns briefing or None on failure."""
    user_content = _build_researcher_prompt(user_query)
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            raw = await _query_xai_responses(
                api_key, user_content, timeout=timeout, model=model
            )
            parsed = _parse_xai_response(raw)
            briefing = _format_briefing(parsed, user_query, model)
            if briefing:
                return briefing
            return None  # empty payload — let caller fall back

        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES and _is_retryable_error(e):
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                print(
                    f"[Researcher] xAI attempt {attempt + 1}/{MAX_RETRIES + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                break

    print(f"[Researcher] xAI failed after {MAX_RETRIES + 1} attempts: {last_error}")
    return None


# =============================================================================
# Fallback path: DuckDuckGo search + LLM synthesis (no API key required)
# =============================================================================

_DDG_SYNTHESIS_PROMPT = """You are a research assistant. The user asked the question below, and a web search returned the snippets below. Produce a briefing in EXACTLY the format specified — nothing else.

Today's date is {today}.

Question: {query}

Search results:
{results_block}

Produce your response with these two markdown headers and nothing else:

## KEY FACTS
- 3 to 8 bullet points of verified facts derived from the snippets above
- Include source URLs in parentheses when available
- Include specific numbers, names, and dates when available

## RESEARCH SUMMARY
2 to 4 paragraphs synthesizing what the search results say about the question. If the results are sparse, contradictory, or unclear, say so plainly."""


async def _ddg_search(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """Run a DuckDuckGo text search via the ddgs library. No API key needed."""
    try:
        from ddgs import DDGS
    except ImportError:
        print("[Researcher] ddgs not installed; skipping DDG fallback")
        return []

    def _search():
        with DDGS() as d:
            return list(d.text(query, max_results=max_results))

    try:
        return await asyncio.to_thread(_search)
    except Exception as e:
        print(f"[Researcher] DDG search failed: {e}")
        return []


def _format_ddg_results(results: List[Dict[str, str]]) -> str:
    """Format raw DDG results into a numbered context block for the synthesizer."""
    if not results:
        return "(no search results)"
    lines = []
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        url = r.get("href") or r.get("url") or ""
        body = (r.get("body") or "").strip()
        lines.append(f"[{i}] {title}\n    URL: {url}\n    {body}")
    return "\n\n".join(lines)


async def _try_ddg(
    user_query: str,
    synthesis_model: str,
    timeout: float,
    max_results: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    Fallback path: DDG search + LLM synthesis into the standard briefing shape.
    Returns None if the search returns nothing or synthesis fails.
    """
    results = await _ddg_search(user_query, max_results=max_results)
    if not results:
        return None

    today = date.today().strftime("%B %d, %Y")
    synthesis_prompt = _DDG_SYNTHESIS_PROMPT.format(
        today=today,
        query=user_query,
        results_block=_format_ddg_results(results),
    )

    response = await query_model(
        synthesis_model,
        [{"role": "user", "content": synthesis_prompt}],
        timeout=timeout,
        max_retries=2,
    )

    if not response or not response.get("content"):
        print("[Researcher] DDG synthesis returned no content")
        return None

    parsed = {
        "text": response["content"],
        "citations": [
            {"url": (r.get("href") or r.get("url") or ""), "title": (r.get("title") or "")}
            for r in results
            if r.get("href") or r.get("url")
        ],
        "search_queries": [user_query],
    }

    return _format_briefing(parsed, user_query, model=f"ddg+{synthesis_model}")


# =============================================================================
# Public entry point
# =============================================================================


async def run_research(
    user_query: str,
    api_key: Optional[str],
    timeout: float = 120.0,
    model: str = "grok-4-1-fast",
    fallback_enabled: bool = True,
    fallback_model: str = DEFAULT_FALLBACK_MODEL,
) -> Optional[Dict[str, Any]]:
    """
    Public entry point: run web research and return a structured briefing.

    Tries xAI Responses API first (if api_key is set), then falls back to
    DuckDuckGo + LLM synthesis. Returns None only if both paths fail.
    """
    if api_key:
        briefing = await _try_xai(user_query, api_key, timeout, model)
        if briefing:
            return briefing
    else:
        print("[Researcher] No XAI_API_KEY — skipping xAI, going straight to fallback")

    if fallback_enabled:
        print(f"[Researcher] Falling back to DuckDuckGo + {fallback_model}")
        return await _try_ddg(user_query, synthesis_model=fallback_model, timeout=timeout)

    return None
