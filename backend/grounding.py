"""Stage-0 grounding orchestrator: a pluggable registry of GroundingSkills.

Generalizes the former single 'researcher' into multiple skills whose outputs
merge into the one briefing the council injects into Stages 1-3. The decision
(which skills run) is split from execution so the streaming endpoint can emit a
``research_decision`` event before any skill runs.

Skills:
  - web_search  (classifier-gated)  — current/live web facts
  - code_exec   (classifier-gated)  — sandboxed Python computation
  - url_reader  (deterministic)     — fetch + extract URLs found in the query
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from . import config as cfg
from .research_intent import classify_grounding
from .skills.base import GroundingSkill
from .skills.web_search import WebSearchSkill
from .skills.url_reader import UrlReaderSkill
from .skills.code_exec import CodeExecSkill

# Registration order also defines section order in the merged briefing.
_SKILL_TYPES = {
    "web_search": WebSearchSkill,
    "url_reader": UrlReaderSkill,
    "code_exec": CodeExecSkill,
}

_registry: Optional[List[GroundingSkill]] = None


@dataclass
class GroundingDecision:
    needed: bool
    reason: str
    skills: List[str] = field(default_factory=list)


def _build_registry() -> List[GroundingSkill]:
    skills_cfg = (cfg.GROUNDING_CONFIG or {}).get("skills", {}) or {}
    registry: List[GroundingSkill] = []
    for key, klass in _SKILL_TYPES.items():
        sc = skills_cfg.get(key, {}) or {}
        if sc.get("enabled", True):
            registry.append(klass(sc))
    return registry


def get_registry() -> List[GroundingSkill]:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


async def decide(user_query: str) -> GroundingDecision:
    """Classify the query and resolve which grounding skills should run."""
    g = cfg.GROUNDING_CONFIG or {}
    if not g.get("enabled", True):
        return GroundingDecision(False, "Grounding disabled in config", [])

    ic = g.get("intent_classifier", {}) or {}
    if ic.get("enabled", True):
        llm_skills, reason = await classify_grounding(
            user_query, model=ic.get("model", "google/gemini-2.5-flash")
        )
    else:
        llm_skills, reason = {"web_search"}, "Intent classifier disabled; defaulting to web_search"

    active = [s.id for s in get_registry() if s.applies(user_query, set(llm_skills))]
    return GroundingDecision(bool(active), reason, active)


async def run(user_query: str, decision: GroundingDecision) -> Optional[Dict[str, Any]]:
    """Run the selected skills in parallel and merge their fragments."""
    if not decision.needed:
        return None
    selected = set(decision.skills)
    active = [s for s in get_registry() if s.id in selected]
    if not active:
        return None

    results = await asyncio.gather(*(s.ground(user_query) for s in active), return_exceptions=True)
    fragments: List[Dict[str, Any]] = []
    for skill, res in zip(active, results):
        if isinstance(res, Exception):
            print(f"[Grounding] skill {skill.id} errored: {res}")
        elif res:
            fragments.append(res)

    briefing = _merge(user_query, fragments)
    if briefing:
        print(f"[Grounding] {len(fragments)} skill(s) -> briefing "
              f"({len(briefing.get('citations', []))} citations) via {briefing.get('model')}")
    return briefing


async def ground_query(user_query: str) -> Optional[Dict[str, Any]]:
    """Convenience: classify + run. Used by council.stage0_research (non-streaming)."""
    decision = await decide(user_query)
    return await run(user_query, decision)


def _merge(user_query: str, fragments: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Combine briefing fragments into one briefing.

    Single fragment is passed through (normalized) so a web-search-only query
    yields exactly the legacy briefing shape — preserving parity. Multiple
    fragments are concatenated under labeled sections with unioned citations.
    """
    fragments = [f for f in fragments if f]
    if not fragments:
        return None

    today = date.today().strftime("%B %d, %Y")

    if len(fragments) == 1:
        f = dict(fragments[0])
        f.setdefault("query", user_query)
        f.setdefault("date", today)
        f.setdefault("key_facts", "")
        f.setdefault("summary", "")
        f.setdefault("citations", [])
        f.setdefault("search_queries", [])
        f.setdefault("model", f.get("label", "grounding"))
        f["skills_used"] = [f.get("source")]
        return f

    key_facts: List[str] = []
    summaries: List[str] = []
    citations: List[Dict[str, str]] = []
    queries: List[str] = []
    labels: List[str] = []
    date_val: Optional[str] = None

    for f in fragments:
        label = f.get("label") or f.get("source") or "Grounding"
        labels.append(f.get("model") or label)
        date_val = date_val or f.get("date")
        if f.get("key_facts"):
            key_facts.append(f"**{label}**\n\n{f['key_facts']}")
        if f.get("summary"):
            summaries.append(f"**{label}**\n\n{f['summary']}")
        citations.extend(f.get("citations") or [])
        queries.extend(f.get("search_queries") or [])

    seen: set = set()
    unique_citations: List[Dict[str, str]] = []
    for c in citations:
        u = c.get("url")
        if u and u not in seen:
            seen.add(u)
            unique_citations.append(c)

    return {
        "query": user_query,
        "date": date_val or today,
        "key_facts": "\n\n".join(key_facts),
        "summary": "\n\n".join(summaries),
        "citations": unique_citations,
        "search_queries": list(dict.fromkeys(queries)),
        "model": " + ".join(labels),
        "skills_used": [f.get("source") for f in fragments],
    }
