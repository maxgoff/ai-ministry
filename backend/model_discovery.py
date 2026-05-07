"""Provider discovery: query each provider's /v1/models endpoint.

Each provider client returns list[DiscoveredModel] or [] on failure. No
exceptions propagate — a provider that's unreachable, missing keys, or returns
malformed data simply contributes zero models to the discovery cycle.

Discovery is intentionally read-only and idempotent. Smoke-testing of new
models happens in a separate stage so we can decide *what's new* before
spending API calls on validation.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from .model_taxonomy import parse_model, ParsedModel


DEFAULT_TIMEOUT = 20.0


def _normalize_id(provider: str, raw_id: str) -> str:
    """
    Build canonical 'provider/model' form.

    Some provider APIs return IDs already containing a '/' (e.g. NVIDIA serves
    'openai/gpt-oss-20b' or 'nvidia/mistral-...'). In those cases we keep the
    upstream prefix to avoid 'nvidia/nvidia/...' double-prefixing — but for
    ID-as-string canonicalization we rewrite to use the discovery provider's
    namespace so smoke tests route correctly.

    Behavior:
      - If raw_id has no '/', prepend provider/.
      - If raw_id starts with '{provider}/', use as-is.
      - Else (raw_id has a different provider prefix): keep the raw upstream
        ID so it's clear who really hosts it.
    """
    if "/" not in raw_id:
        return f"{provider}/{raw_id}"
    if raw_id.startswith(f"{provider}/"):
        return raw_id
    return raw_id  # upstream-prefixed, e.g. nvidia hosting openai/gpt-oss-20b


@dataclass
class DiscoveredModel:
    """A model surfaced by a provider's catalog endpoint."""
    id: str                              # canonical "provider/name" form, e.g. "anthropic/claude-opus-4.6"
    provider: str                        # the discovery provider (may differ from the prefix in id for openrouter)
    source: str                          # "direct" | "openrouter"
    created: Optional[int] = None        # unix timestamp if known
    pricing_completion: Optional[float] = None  # USD/token if known
    context_length: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    parsed: Optional[ParsedModel] = None  # filled in by callers if needed

    def with_parsed(self) -> "DiscoveredModel":
        if self.parsed is None:
            self.parsed = parse_model(self.id)
        return self


# ---------------------------------------------------------------------------
# Direct provider clients
# ---------------------------------------------------------------------------

async def _get_json(url: str, headers: Dict[str, str], timeout: float = DEFAULT_TIMEOUT) -> Optional[Dict[str, Any]]:
    """Issue a GET, return JSON or None on any failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        print(f"[Discovery] GET {url} failed: {e}")
        return None


async def discover_openai(api_key: Optional[str], base_url: str = "https://api.openai.com/v1") -> List[DiscoveredModel]:
    if not api_key:
        return []
    data = await _get_json(f"{base_url}/models", {"Authorization": f"Bearer {api_key}"})
    if not data:
        return []
    out = []
    for m in data.get("data", []):
        mid = m.get("id")
        if not mid:
            continue
        out.append(DiscoveredModel(
            id=_normalize_id("openai", mid),
            provider="openai",
            source="direct",
            created=m.get("created"),
            raw=m,
        ))
    return out


async def discover_anthropic(api_key: Optional[str], base_url: str = "https://api.anthropic.com/v1") -> List[DiscoveredModel]:
    if not api_key:
        return []
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    data = await _get_json(f"{base_url}/models?limit=1000", headers)
    if not data:
        return []
    out = []
    for m in data.get("data", []):
        mid = m.get("id")
        if not mid:
            continue
        out.append(DiscoveredModel(
            id=_normalize_id("anthropic", mid),
            provider="anthropic",
            source="direct",
            raw=m,
        ))
    return out


async def discover_google(api_key: Optional[str], base_url: str = "https://generativelanguage.googleapis.com/v1beta") -> List[DiscoveredModel]:
    if not api_key:
        return []
    data = await _get_json(f"{base_url}/models?key={api_key}&pageSize=200", {})
    if not data:
        return []
    out = []
    for m in data.get("models", []):
        # Google returns "models/gemini-3-pro-preview" — strip prefix.
        name = m.get("name", "")
        if name.startswith("models/"):
            name = name[len("models/"):]
        if not name:
            continue
        # Filter out non-generative endpoints (embeddings, etc.) by checking supported methods.
        methods = m.get("supportedGenerationMethods", [])
        if methods and "generateContent" not in methods:
            continue
        out.append(DiscoveredModel(
            id=_normalize_id("google", name),
            provider="google",
            source="direct",
            raw=m,
        ))
    return out


async def discover_xai(api_key: Optional[str], base_url: str = "https://api.x.ai/v1") -> List[DiscoveredModel]:
    if not api_key:
        return []
    data = await _get_json(f"{base_url}/models", {"Authorization": f"Bearer {api_key}"})
    if not data:
        return []
    out = []
    for m in data.get("data", []):
        mid = m.get("id")
        if not mid:
            continue
        out.append(DiscoveredModel(
            id=_normalize_id("xai", mid),
            provider="xai",
            source="direct",
            created=m.get("created"),
            raw=m,
        ))
    return out


async def discover_moonshot(api_key: Optional[str], base_url: str = "https://api.moonshot.ai/v1") -> List[DiscoveredModel]:
    if not api_key:
        return []
    data = await _get_json(f"{base_url}/models", {"Authorization": f"Bearer {api_key}"})
    if not data:
        return []
    out = []
    for m in data.get("data", []):
        mid = m.get("id")
        if not mid:
            continue
        out.append(DiscoveredModel(
            id=_normalize_id("moonshot", mid),
            provider="moonshot",
            source="direct",
            created=m.get("created"),
            raw=m,
        ))
    return out


async def discover_nvidia(api_key: Optional[str], base_url: str = "https://integrate.api.nvidia.com/v1") -> List[DiscoveredModel]:
    if not api_key:
        return []
    data = await _get_json(f"{base_url}/models", {"Authorization": f"Bearer {api_key}"})
    if not data:
        return []
    out = []
    for m in data.get("data", []):
        mid = m.get("id")
        if not mid:
            continue
        out.append(DiscoveredModel(
            id=_normalize_id("nvidia", mid),
            provider="nvidia",
            source="direct",
            created=m.get("created"),
            raw=m,
        ))
    return out


async def discover_openrouter(api_key: Optional[str], base_url: str = "https://openrouter.ai/api/v1") -> List[DiscoveredModel]:
    """OpenRouter aggregates all providers — used as enrichment + fallback."""
    if not api_key:
        return []
    data = await _get_json(f"{base_url}/models", {"Authorization": f"Bearer {api_key}"})
    if not data:
        return []
    out = []
    for m in data.get("data", []):
        mid = m.get("id")  # already "provider/model" form
        if not mid:
            continue
        pricing = m.get("pricing", {}) or {}
        try:
            completion_cost = float(pricing.get("completion")) if pricing.get("completion") else None
        except (TypeError, ValueError):
            completion_cost = None
        out.append(DiscoveredModel(
            id=mid,
            provider=mid.split("/")[0] if "/" in mid else "openrouter",
            source="openrouter",
            created=m.get("created"),
            pricing_completion=completion_cost,
            context_length=m.get("context_length"),
            raw=m,
        ))
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

# Map provider keys (as used in YAML config) to discovery functions.
_PROVIDER_FUNCS = {
    "openai": discover_openai,
    "anthropic": discover_anthropic,
    "google": discover_google,
    "xai": discover_xai,
    "moonshot": discover_moonshot,
    "nvidia": discover_nvidia,
    "openrouter": discover_openrouter,
}


async def discover_all(provider_configs: Dict[str, Dict[str, Any]]) -> List[DiscoveredModel]:
    """
    Run discovery against every enabled provider in parallel.

    Args:
        provider_configs: {provider_name: {enabled, api_key_env, base_url, role}}

    Returns:
        Flat list of DiscoveredModel from all providers. Direct sources come
        first; OpenRouter entries follow and provide enrichment data.
    """
    tasks = []
    labels = []

    for name, cfg in provider_configs.items():
        if not cfg.get("enabled", True):
            continue
        func = _PROVIDER_FUNCS.get(name)
        if not func:
            print(f"[Discovery] Unknown provider '{name}' in config — skipping")
            continue
        api_key = os.getenv(cfg.get("api_key_env", ""))
        kwargs: Dict[str, Any] = {}
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        tasks.append(func(api_key, **kwargs))
        labels.append(name)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    flat: List[DiscoveredModel] = []
    for label, res in zip(labels, results):
        if isinstance(res, Exception):
            print(f"[Discovery] {label} raised: {res}")
            continue
        print(f"[Discovery] {label}: {len(res)} models")
        flat.extend(res)

    # Attach parsed taxonomy to each entry once.
    for d in flat:
        d.with_parsed()

    return flat


def merge_enrichment(models: List[DiscoveredModel]) -> List[DiscoveredModel]:
    """
    Dedupe by id, preferring 'direct' entries; fold OpenRouter pricing/context
    into the canonical entry.
    """
    by_id: Dict[str, DiscoveredModel] = {}
    for m in models:
        existing = by_id.get(m.id)
        if existing is None:
            by_id[m.id] = m
            continue
        # If we already have a direct entry, fold in OpenRouter enrichment fields
        # without overwriting. Otherwise upgrade to direct if this one is.
        if existing.source != "direct" and m.source == "direct":
            # Replace, but keep enrichment from prior entry
            m.pricing_completion = m.pricing_completion or existing.pricing_completion
            m.context_length = m.context_length or existing.context_length
            by_id[m.id] = m
        else:
            existing.pricing_completion = existing.pricing_completion or m.pricing_completion
            existing.context_length = existing.context_length or m.context_length
            existing.created = existing.created or m.created

    return list(by_id.values())
