"""Runtime model registry: persistence, generation policy, succession.

The registry is the source of truth for which models the app exposes via
/api/config. It is written to data/model_registry.json (atomic) and refreshed
either at boot (sync if missing, async otherwise) or on demand via the
REFRESH endpoint.

Generation policy: within each (provider, family) group, only models matching
the max major version are kept. Older majors are evicted. Models with
family='other' are pinned and never auto-evicted.

Succession: when a default ministry member or PM is evicted, find a successor
in the same (provider, family, tier). Personas migrate to the successor.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .model_discovery import DiscoveredModel
from .model_taxonomy import ParsedModel, parse_model, is_evictable


REGISTRY_PATH = Path(__file__).parent.parent / "data" / "model_registry.json"

# Suffixes that mark a feature/preview variant of an otherwise-identical model.
# Within a (provider, family, tier, version) group, two IDs that differ only by
# one of these suffixes collapse to one survivor (the canonical / base form).
_VARIANT_SUFFIXES = (
    "-customtools",
    "-experimental",
    "-with-thinking",
    "-with-search",
)


def _canonical_id(model_id: str) -> str:
    """Strip a single trailing variant suffix from a model id, if present."""
    for suffix in _VARIANT_SUFFIXES:
        if model_id.endswith(suffix):
            return model_id[: -len(suffix)]
    return model_id


@dataclass
class RegistryModel:
    """A model entry persisted in the registry."""
    id: str
    provider: str
    family: str
    tier: str
    version: List[int]              # JSON-serializable form of version tuple
    source: str                     # "direct" | "openrouter" | "yaml_override"
    pricing_completion: Optional[float] = None
    context_length: Optional[int] = None
    smoke_tested_at: Optional[str] = None
    pinned: bool = False            # True for yaml overrides + family='other'

    @classmethod
    def from_discovered(cls, d: DiscoveredModel) -> "RegistryModel":
        p = d.parsed or parse_model(d.id)
        return cls(
            id=d.id,
            provider=p.provider or d.provider,
            family=p.family,
            tier=p.tier,
            version=list(p.version),
            source=d.source,
            pricing_completion=d.pricing_completion,
            context_length=d.context_length,
            pinned=not is_evictable(p),
        )


@dataclass
class Eviction:
    """An evicted model and the reason."""
    id: str
    reason: str
    superseded_by: List[str] = field(default_factory=list)


@dataclass
class Registry:
    """Top-level registry document."""
    generated_at: str
    models: List[RegistryModel] = field(default_factory=list)
    evicted: List[Eviction] = field(default_factory=list)
    succession: Dict[str, str] = field(default_factory=dict)  # old_id -> new_id
    smoke_failures: List[str] = field(default_factory=list)

    def model_ids(self) -> List[str]:
        return [m.id for m in self.models]


# ---------------------------------------------------------------------------
# Generation policy
# ---------------------------------------------------------------------------

def compute_current_generation(
    discovered: List[DiscoveredModel],
) -> Tuple[List[DiscoveredModel], List[Eviction]]:
    """
    Apply current-gen policy in three passes:

    1. Per (provider, family, tier): keep only the max version. Older
       versions are evicted as superseded.
    2. Within each survivor set, collapse variant suffixes (-customtools,
       -experimental, etc.) so feature-flag variants don't bloat the registry.
    3. Per (provider, family): drop any non-pinned model whose major lags
       the family-wide max-major by 2+ — catches genuinely legacy models
       (e.g. gpt-3.5-turbo-instruct) that survive only because their tier
       has no younger sibling.

    Pinned models (family='other' or no version) bypass all three passes.

    Returns:
        (kept, evicted) — kept is the candidate registry; evicted lists what
        was dropped along with what superseded it.
    """
    evicted: List[Eviction] = []

    pinned: List[DiscoveredModel] = []
    grouped: Dict[Tuple[str, str, str], List[DiscoveredModel]] = {}

    for d in discovered:
        p = d.parsed or parse_model(d.id)
        d.parsed = p
        if not is_evictable(p):
            pinned.append(d)
            continue
        key = (p.provider or d.provider, p.family, p.tier)
        grouped.setdefault(key, []).append(d)

    kept: List[DiscoveredModel] = list(pinned)

    # Pass 1: max-version-per-tier
    for (provider, family, tier), group in grouped.items():
        max_version = max(d.parsed.version for d in group)
        survivors = [d for d in group if d.parsed.version == max_version]
        losers = [d for d in group if d.parsed.version != max_version]

        # Pass 2: variant-suffix dedupe within survivors
        survivors, variant_evicted = _dedupe_variants(survivors)
        evicted.extend(variant_evicted)

        kept.extend(survivors)

        survivor_ids = [d.id for d in survivors]
        tier_label = tier or "default"
        version_label = ".".join(str(n) for n in max_version)
        for loser in losers:
            loser_version = ".".join(str(n) for n in loser.parsed.version)
            evicted.append(Eviction(
                id=loser.id,
                reason=f"superseded: {provider}/{family} {tier_label} current is {version_label}, this is {loser_version}",
                superseded_by=survivor_ids,
            ))

    # Pass 3: legacy-major drop (across tiers within a family)
    kept, legacy_evicted = _drop_legacy_majors(kept, pinned_ids={d.id for d in pinned})
    evicted.extend(legacy_evicted)

    return kept, evicted


def _dedupe_variants(
    survivors: List[DiscoveredModel],
) -> Tuple[List[DiscoveredModel], List[Eviction]]:
    """
    Within a survivor list (already filtered to one (provider, family, tier,
    version) group), collapse models that share a canonical id.

    Tie-break: prefer the model whose id equals its canonical form (i.e. no
    variant suffix); otherwise the shortest id wins.
    """
    by_canonical: Dict[str, List[DiscoveredModel]] = {}
    for d in survivors:
        by_canonical.setdefault(_canonical_id(d.id), []).append(d)

    kept: List[DiscoveredModel] = []
    evicted: List[Eviction] = []
    for canonical, variants in by_canonical.items():
        if len(variants) == 1:
            kept.append(variants[0])
            continue
        # Prefer exact canonical match, then shortest id.
        winner = next((v for v in variants if v.id == canonical), None)
        if winner is None:
            winner = min(variants, key=lambda v: len(v.id))
        kept.append(winner)
        for v in variants:
            if v.id == winner.id:
                continue
            evicted.append(Eviction(
                id=v.id,
                reason=f"variant of {winner.id}",
                superseded_by=[winner.id],
            ))
    return kept, evicted


# Family majors more than this many behind the family-wide max are dropped
# as legacy. Diff of 2 keeps last-gen tier holdouts (e.g. grok-3-mini next to
# grok-4) but drops genuine legacy (gpt-3.5-* next to gpt-5.x).
_LEGACY_MAJOR_LAG = 2


def _drop_legacy_majors(
    kept: List[DiscoveredModel],
    pinned_ids: set[str],
) -> Tuple[List[DiscoveredModel], List[Eviction]]:
    """
    For each (provider, family) group across the kept set, compute the
    family-wide max major and drop non-pinned models whose major lags by
    >= _LEGACY_MAJOR_LAG.
    """
    family_max_major: Dict[Tuple[str, str], int] = {}
    for d in kept:
        if d.id in pinned_ids:
            continue
        if not d.parsed.version:
            continue
        key = (d.parsed.provider or d.provider, d.parsed.family)
        family_max_major[key] = max(family_max_major.get(key, 0), d.parsed.major)

    survivors: List[DiscoveredModel] = []
    evicted: List[Eviction] = []
    for d in kept:
        if d.id in pinned_ids:
            survivors.append(d)
            continue
        if not d.parsed.version:
            survivors.append(d)
            continue
        key = (d.parsed.provider or d.provider, d.parsed.family)
        max_major = family_max_major.get(key, 0)
        if max_major - d.parsed.major >= _LEGACY_MAJOR_LAG:
            evicted.append(Eviction(
                id=d.id,
                reason=f"legacy: {key[0]}/{key[1]} current major is {max_major}, this is {d.parsed.major}",
                superseded_by=[],
            ))
            continue
        survivors.append(d)
    return survivors, evicted


# ---------------------------------------------------------------------------
# Succession (default ministry members + PM)
# ---------------------------------------------------------------------------

def find_successor(
    old_id: str,
    candidates: List[RegistryModel],
) -> Optional[str]:
    """
    Pick a replacement for an evicted model from the kept set.

    Strategy: same (provider, family, tier) → highest version only. Returns
    None if no exact tier match exists.

    We deliberately do NOT fall back to same (provider, family) at any tier:
    crossing tiers is a meaningful change in capability (e.g. "" → "nano"
    is a downgrade). The caller handles None by keeping the original ID
    pending operator review.
    """
    p = parse_model(old_id)
    if p.family == "other":
        return None

    same_tier = [
        m for m in candidates
        if m.provider == (p.provider or m.provider)
        and m.family == p.family
        and m.tier == p.tier
    ]
    if same_tier:
        return _highest_version(same_tier).id

    return None


def _highest_version(models: List[RegistryModel]) -> RegistryModel:
    """Pick the model with the highest version tuple."""
    return max(models, key=lambda m: tuple(m.version))


def compute_succession(
    evicted: List[Eviction],
    kept_models: List[RegistryModel],
    default_ids: List[str],
) -> Dict[str, str]:
    """
    For each evicted model that appears in default_ids, find a successor.
    Returns mapping {old_id: new_id} (only entries where a successor exists).
    """
    evicted_ids = {e.id for e in evicted}
    succession: Dict[str, str] = {}
    for old_id in default_ids:
        if old_id not in evicted_ids:
            continue
        new_id = find_successor(old_id, kept_models)
        if new_id and new_id != old_id:
            succession[old_id] = new_id
    return succession


def apply_succession_to_personas(
    persona_map: Dict[str, str],
    succession: Dict[str, str],
) -> Dict[str, str]:
    """Carry persona bindings from old IDs to their successors."""
    out = dict(persona_map)
    for old_id, new_id in succession.items():
        if old_id in out and new_id not in out:
            out[new_id] = out[old_id]
            del out[old_id]
    return out


def apply_succession_to_list(model_list: List[str], succession: Dict[str, str]) -> List[str]:
    """Replace evicted IDs in a list with their successors. Drop entries with no successor."""
    out = []
    seen = set()
    for mid in model_list:
        target = succession.get(mid, mid)
        if target in seen:
            continue
        # If the original was evicted and has no successor, drop it.
        if mid in succession or target == mid:
            seen.add(target)
            out.append(target)
    return out


# ---------------------------------------------------------------------------
# YAML overrides
# ---------------------------------------------------------------------------

def merge_yaml_overrides(
    kept: List[DiscoveredModel],
    overrides: List[str],
) -> List[DiscoveredModel]:
    """
    Add user-pinned model IDs from yaml that aren't already present.
    Overrides are always retained across refreshes.
    """
    existing_ids = {d.id for d in kept}
    merged = list(kept)
    for mid in overrides:
        if mid in existing_ids:
            continue
        # Build a synthetic DiscoveredModel for the override.
        synthetic = DiscoveredModel(
            id=mid,
            provider=mid.split("/")[0] if "/" in mid else "",
            source="yaml_override",
        )
        synthetic.with_parsed()
        merged.append(synthetic)
    return merged


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_registry(path: Path = REGISTRY_PATH) -> Optional[Registry]:
    """Load registry from disk. Returns None if file doesn't exist or is corrupt."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return Registry(
            generated_at=data.get("generated_at", ""),
            models=[RegistryModel(**m) for m in data.get("models", [])],
            evicted=[Eviction(**e) for e in data.get("evicted", [])],
            succession=data.get("succession", {}),
            smoke_failures=data.get("smoke_failures", []),
        )
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        print(f"[Registry] Failed to load {path}: {e}")
        return None


def save_registry(registry: Registry, path: Path = REGISTRY_PATH) -> None:
    """Atomically write registry to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": registry.generated_at,
        "models": [asdict(m) for m in registry.models],
        "evicted": [asdict(e) for e in registry.evicted],
        "succession": registry.succession,
        "smoke_failures": registry.smoke_failures,
    }
    # Atomic: write to temp, rename.
    fd, tmp = tempfile.mkstemp(prefix=".registry-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=False)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
