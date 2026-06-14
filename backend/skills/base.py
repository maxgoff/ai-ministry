"""Base class for Stage-0 grounding skills.

A grounding skill inspects the user query and, when applicable, produces a
*briefing fragment* — a partial dict with any of:
    key_facts:      markdown bullets of grounded facts
    summary:        markdown prose
    citations:      [{"url": str, "title": str}, ...]
    search_queries: [str, ...]
    label:          human-readable header used when merging multiple fragments
    source:         stable skill id (e.g. "web_search")
    model:          engine/model identifier for display

Fragments are merged by backend/grounding.py into the single briefing the
council injects into Stages 1-3 (see council._build_research_context). The
merged dict preserves the keys the existing pipeline + frontend read
(key_facts, summary, citations, search_queries, model, date).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Set


class GroundingSkill(ABC):
    """One pluggable Stage-0 grounding capability."""

    id: str = "skill"
    label: str = "Grounding"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def applies(self, query: str, llm_skills: Set[str]) -> bool:
        """Whether this skill should run for the query.

        ``llm_skills`` is the set the intent classifier selected (for
        classifier-gated skills like web_search / code_exec). Deterministic
        skills (e.g. url_reader) may ignore it and decide from the query alone.
        """

    @abstractmethod
    async def ground(self, query: str) -> Optional[Dict[str, Any]]:
        """Run the skill and return a briefing fragment, or None on no-op/failure."""
