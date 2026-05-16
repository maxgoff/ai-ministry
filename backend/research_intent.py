"""Decide whether a user query needs a Stage 0 web research briefing.

A cheap classifier call — typically sub-second — that gates the (much more
expensive and slow) Stage 0 researcher. Defaults to YES on failure so we
don't silently deliver stale info on time-sensitive questions.
"""

import json
import re
from typing import Tuple

from .openrouter import query_model

DEFAULT_CLASSIFIER_MODEL = "google/gemini-2.5-flash"

_CLASSIFIER_PROMPT = """You are a fast intent classifier. Decide if the following user query needs current web information to answer accurately.

Answer YES (needs_research = true) when the query asks about:
- Current events, news, or recent developments
- Live data: prices, weather, sports scores, market or service status
- Specific recent products, releases, announcements, regulations
- Time-sensitive facts ("today", "this week", "latest", "current", "now")
- People or companies whose situation may have changed recently
- Anything where stale knowledge could be misleading

Answer NO (needs_research = false) when the query is:
- A general knowledge question with stable answers (math, definitions, history)
- A reasoning, opinion, strategy, or planning task
- A coding, technical how-to, or design question
- A self-contained problem that does not depend on external state
- A creative or hypothetical exploration

Query:
{query}

Respond in JSON only — no prose, no markdown fences:
{{"needs_research": true_or_false, "reason": "one short sentence"}}"""


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError(f"No JSON object found in: {text!r}")


async def should_research(
    user_query: str,
    model: str = DEFAULT_CLASSIFIER_MODEL,
    timeout: float = 30.0,
) -> Tuple[bool, str]:
    """
    Classify whether the user's query needs a web research briefing.

    Returns (needs_research, reason). Defaults to True on any failure
    (network error, malformed JSON, etc.) — stale info is worse than
    a few extra seconds of latency.
    """
    messages = [
        {"role": "user", "content": _CLASSIFIER_PROMPT.format(query=user_query)}
    ]

    try:
        result = await query_model(model, messages, timeout=timeout, max_retries=1)
        if not result or not result.get("content"):
            return True, "Classifier returned empty response (defaulting to research)"

        parsed = _extract_json(result["content"])
        needs = bool(parsed.get("needs_research", True))
        reason = (str(parsed.get("reason", "")).strip()
                  or ("Classifier flagged as research-worthy" if needs
                      else "Classifier flagged as self-contained"))
        return needs, reason

    except Exception as e:
        print(f"[ResearchIntent] Classifier failed: {e} — defaulting to research")
        return True, f"Classifier error ({type(e).__name__}); defaulting to research"
