"""Orchestrates a refresh cycle: discover → policy → smoke-test → persist.

Used both at boot (sync if no registry exists, async otherwise) and from the
manual REFRESH endpoint.

Smoke test runs only against *new* models (those not already in the registry)
so an established model isn't repeatedly re-validated and we don't burn API
calls on every refresh.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from . import config as cfg
from .model_discovery import (
    DiscoveredModel,
    discover_all,
    merge_enrichment,
)
from .model_registry import (
    Eviction,
    Registry,
    RegistryModel,
    apply_succession_to_list,
    apply_succession_to_personas,
    compute_current_generation,
    compute_succession,
    load_registry,
    merge_yaml_overrides,
    now_iso,
    save_registry,
)
from .model_taxonomy import is_evictable
from .openrouter import query_model


# Reasoning models warrant a longer smoke-test timeout.
_REASONING_HINTS = ("reasoning", "thinking", "deepseek-v4", "kimi-k2.5", "gpt-5.2", "grok-4", "nemotron", "glm-5")

# Cap concurrent smoke-test requests to avoid hitting OS file descriptor limits
# (macOS default ulimit is 256). 16 concurrent httpx clients is comfortably
# under that even with multiple connections each.
_SMOKE_CONCURRENCY = 16


def _smoke_timeout_for(model_id: str, default: float, reasoning: float) -> float:
    lid = model_id.lower()
    return reasoning if any(hint in lid for hint in _REASONING_HINTS) else default


async def smoke_test_model(model_id: str, timeout: float) -> Tuple[str, bool, Optional[str]]:
    """Returns (model_id, ok, error_msg)."""
    try:
        resp = await query_model(
            model_id,
            [{"role": "user", "content": "Say OK"}],
            timeout=timeout,
            max_retries=0,
        )
        ok = bool(resp and resp.get("content"))
        return (model_id, ok, None if ok else "empty response")
    except Exception as e:
        return (model_id, False, str(e))


async def smoke_test_new(
    candidate_ids: List[str],
    default_timeout: float,
    reasoning_timeout: float,
    concurrency: int = _SMOKE_CONCURRENCY,
) -> Tuple[Set[str], Dict[str, str]]:
    """
    Smoke-test a list of model IDs in parallel, capped at `concurrency`
    simultaneous requests to stay under OS FD limits.

    Returns:
        (passed_ids, failure_map_id_to_error)
    """
    if not candidate_ids:
        return set(), {}

    semaphore = asyncio.Semaphore(concurrency)

    async def _gated(mid: str):
        async with semaphore:
            return await smoke_test_model(
                mid,
                _smoke_timeout_for(mid, default_timeout, reasoning_timeout),
            )

    tasks = [_gated(mid) for mid in candidate_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    passed: Set[str] = set()
    failures: Dict[str, str] = {}
    for idx, res in enumerate(results):
        mid = candidate_ids[idx]
        if isinstance(res, Exception):
            failures[mid] = str(res)
            continue
        _, ok, err = res
        if ok:
            passed.add(mid)
        else:
            failures[mid] = err or "smoke-test failed"

    return passed, failures


@dataclass
class RefreshDiff:
    """Result of a refresh cycle, returned to API callers."""
    added: List[str] = field(default_factory=list)
    removed: List[Eviction] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)
    succession: Dict[str, str] = field(default_factory=dict)
    smoke_failures: Dict[str, str] = field(default_factory=dict)
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": [{"id": e.id, "reason": e.reason, "superseded_by": e.superseded_by} for e in self.removed],
            "kept": self.kept,
            "succession": self.succession,
            "smoke_failures": self.smoke_failures,
            "generated_at": self.generated_at,
        }


async def run_refresh() -> RefreshDiff:
    """
    Full refresh cycle. Reads provider config from ministry_config.yaml,
    discovers, applies policy, smoke-tests new entries, persists registry,
    and returns a diff.
    """
    discovery_cfg = cfg.DISCOVERY_CONFIG
    if not discovery_cfg.get("enabled", True):
        print("[Refresh] discovery disabled in config")
        # Return current registry as no-op diff
        existing = load_registry()
        return RefreshDiff(
            added=[],
            removed=[],
            kept=existing.model_ids() if existing else [],
            succession={},
            smoke_failures={},
            generated_at=existing.generated_at if existing else now_iso(),
        )

    provider_configs = discovery_cfg.get("providers", {})
    smoke_cfg = discovery_cfg.get("smoke_test", {})
    default_timeout = float(smoke_cfg.get("timeout_seconds", 10))
    reasoning_timeout = float(smoke_cfg.get("reasoning_timeout_seconds", 60))

    overrides: List[str] = cfg._yaml_config.get("available_models_overrides", []) or []
    denylist: Set[str] = set(cfg._yaml_config.get("available_models_denylist", []) or [])

    # 1. Discover everything in parallel
    discovered = await discover_all(provider_configs)

    # 2. Dedupe, fold enrichment data
    deduped = merge_enrichment(discovered)

    # 2a. OpenRouter is enrichment-only — never an originator of new model IDs.
    # Otherwise its 300+ marketplace catalog floods the registry. We keep
    # OpenRouter entries that *also* exist via direct discovery (they were
    # already merged in step 2) and drop the rest.
    direct_ids = {d.id for d in deduped if d.source == "direct"}
    deduped = [d for d in deduped if d.source == "direct" or d.id in direct_ids]

    # 2c. Apply user-configured deny-list. Catches IDs that providers expose
    # but our call path can't route (e.g. NIM lists a model OpenRouter doesn't carry).
    if denylist:
        before = len(deduped)
        deduped = [d for d in deduped if d.id not in denylist]
        print(f"[Refresh] denylist filtered {before - len(deduped)} models")

    # 2b. Drop models we can't classify into a known family. These are mostly
    # provider-hosted third-party models (NVIDIA hosts mistral/llama/etc.,
    # OpenAI catalog includes embeddings/dall-e/whisper). Users can always
    # pin specific IDs via available_models_overrides.
    classified = [d for d in deduped if is_evictable(d.parsed)]
    print(f"[Refresh] discovery yielded {len(deduped)} models, {len(classified)} classified into known families")

    # 3. Apply current-gen policy
    kept_discovered, evicted = compute_current_generation(classified)

    # 4. Merge in user-pinned overrides
    kept_discovered = merge_yaml_overrides(kept_discovered, overrides)

    # 5. Smoke-test only new entries
    existing_registry = load_registry()
    existing_ids: Set[str] = set(existing_registry.model_ids()) if existing_registry else set()
    candidate_ids = [d.id for d in kept_discovered if d.id not in existing_ids]
    print(f"[Refresh] {len(candidate_ids)} new models to smoke-test")
    passed, failures = await smoke_test_new(candidate_ids, default_timeout, reasoning_timeout)

    # 6. Drop failed candidates from kept set
    failed_ids = set(failures.keys())
    kept_final = [d for d in kept_discovered if d.id not in failed_ids]

    # 7. Build registry models
    registry_models = [RegistryModel.from_discovered(d) for d in kept_final]
    # Mark smoke-tested timestamp on freshly-passed models
    now = now_iso()
    for rm in registry_models:
        if rm.id in passed:
            rm.smoke_tested_at = now
        elif existing_registry:
            # Carry forward prior smoke-test timestamp
            for prior in existing_registry.models:
                if prior.id == rm.id and prior.smoke_tested_at:
                    rm.smoke_tested_at = prior.smoke_tested_at
                    break

    # 8. Compute succession for default ministry members + PM
    default_ids = list(set(cfg.DEFAULT_MINISTRY_MODELS + [cfg.DEFAULT_PRIME_MINISTER]))
    succession = compute_succession(evicted, registry_models, default_ids)

    # 9. Persist
    new_registry = Registry(
        generated_at=now,
        models=registry_models,
        evicted=evicted,
        succession=succession,
        smoke_failures=list(failures.keys()),
    )
    save_registry(new_registry)

    # 10. Build diff
    new_ids = {m.id for m in registry_models}
    added = sorted(new_ids - existing_ids)
    return RefreshDiff(
        added=added,
        removed=evicted,
        kept=sorted(new_ids),
        succession=succession,
        smoke_failures=failures,
        generated_at=now,
    )


def get_active_registry() -> Optional[Registry]:
    """Convenience accessor used by API endpoints."""
    return load_registry()


def effective_defaults() -> Tuple[List[str], Dict[str, str], str]:
    """
    Apply the registry's succession map to the YAML defaults.

    Returns:
        (ministry_models, model_personas, prime_minister)
    """
    registry = load_registry()
    if registry is None or not registry.succession:
        return cfg.DEFAULT_MINISTRY_MODELS, cfg.DEFAULT_MODEL_PERSONAS, cfg.DEFAULT_PRIME_MINISTER

    succ = registry.succession
    ministry_models = apply_succession_to_list(cfg.DEFAULT_MINISTRY_MODELS, succ)
    personas = apply_succession_to_personas(cfg.DEFAULT_MODEL_PERSONAS, succ)
    prime_minister = succ.get(cfg.DEFAULT_PRIME_MINISTER, cfg.DEFAULT_PRIME_MINISTER)
    return ministry_models, personas, prime_minister


def effective_available_models() -> List[str]:
    """Models exposed via /api/config — registry if present, else YAML fallback."""
    registry = load_registry()
    if registry is None or not registry.models:
        return cfg.AVAILABLE_MODELS
    return [m.id for m in registry.models]
