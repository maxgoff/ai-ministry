"""Web-search grounding skill — thin adapter over the existing researcher.

Delegates to researcher.run_research (xAI Responses + grok web_search, with a
DuckDuckGo + LLM-synthesis fallback) so the battle-tested research path is
reused unchanged; this skill only adapts it to the GroundingSkill interface.
"""

from typing import Any, Dict, Optional, Set

from .base import GroundingSkill
from .. import config as cfg
from ..researcher import run_research


class WebSearchSkill(GroundingSkill):
    id = "web_search"
    label = "Web Search"

    def applies(self, query: str, llm_skills: Set[str]) -> bool:
        return "web_search" in llm_skills

    async def ground(self, query: str) -> Optional[Dict[str, Any]]:
        c = self.config
        briefing = await run_research(
            query,
            api_key=cfg.XAI_API_KEY,
            timeout=float(c.get("timeout", 120)),
            model=c.get("model", "grok-4-1-fast"),
            fallback_enabled=c.get("fallback_enabled", True),
            fallback_model=c.get("fallback_model", "google/gemini-2.5-flash"),
        )
        if briefing:
            briefing.setdefault("source", self.id)
            briefing.setdefault("label", self.label)
        return briefing
