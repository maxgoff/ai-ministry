"""Tests for backend/model_registry.py policy fixes (succession, variant
dedupe, legacy filter)."""

from backend.model_discovery import DiscoveredModel
from backend.model_registry import (
    RegistryModel,
    compute_current_generation,
    find_successor,
)
from backend.model_taxonomy import parse_model


def _disc(model_id: str) -> DiscoveredModel:
    """Build a DiscoveredModel with parsed metadata populated."""
    d = DiscoveredModel(id=model_id, provider=model_id.split("/")[0], source="direct")
    d.parsed = parse_model(model_id)
    return d


def _reg(model_id: str) -> RegistryModel:
    p = parse_model(model_id)
    return RegistryModel(
        id=model_id,
        provider=p.provider,
        family=p.family,
        tier=p.tier,
        version=list(p.version),
        source="direct",
    )


class TestSuccession:
    def test_no_cross_tier_fallback(self):
        """Fix #2: tier='' must NOT promote to tier='nano'."""
        candidates = [_reg("openai/gpt-5.4-nano")]
        result = find_successor("openai/gpt-5.2", candidates)
        assert result is None

    def test_same_tier_succession_works(self):
        candidates = [_reg("anthropic/claude-opus-4-7")]
        result = find_successor("anthropic/claude-opus-4", candidates)
        assert result == "anthropic/claude-opus-4-7"

    def test_no_match_returns_none(self):
        candidates = [_reg("anthropic/claude-sonnet-4-6")]
        result = find_successor("anthropic/claude-opus-4", candidates)
        assert result is None


class TestVariantDedupe:
    def test_customtools_variant_evicted(self):
        """Fix #3: -customtools collapses to canonical preview."""
        models = [
            _disc("google/gemini-3.1-pro-preview"),
            _disc("google/gemini-3.1-pro-preview-customtools"),
        ]
        kept, evicted = compute_current_generation(models)
        kept_ids = {m.id for m in kept}
        assert "google/gemini-3.1-pro-preview" in kept_ids
        assert "google/gemini-3.1-pro-preview-customtools" not in kept_ids
        assert any(
            e.id == "google/gemini-3.1-pro-preview-customtools"
            and "variant of" in e.reason
            for e in evicted
        )

    def test_no_dedupe_when_only_variant_exists(self):
        models = [_disc("google/gemini-3.1-pro-preview-customtools")]
        kept, evicted = compute_current_generation(models)
        assert len(kept) == 1
        assert kept[0].id == "google/gemini-3.1-pro-preview-customtools"


class TestLegacyMajorFilter:
    def test_gpt_3_5_dropped_when_gpt_5_present(self):
        """Fix #4: gpt-3.5-turbo-instruct dropped when gpt-5.x current."""
        models = [
            _disc("openai/gpt-5.4-nano"),
            _disc("openai/gpt-3.5-turbo-instruct"),
        ]
        kept, evicted = compute_current_generation(models)
        kept_ids = {m.id for m in kept}
        assert "openai/gpt-5.4-nano" in kept_ids
        assert "openai/gpt-3.5-turbo-instruct" not in kept_ids
        assert any(
            e.id == "openai/gpt-3.5-turbo-instruct" and "legacy" in e.reason
            for e in evicted
        )

    def test_one_major_lag_is_ok(self):
        """grok-3-mini stays alongside grok-4 (lag of 1 < threshold of 2)."""
        models = [
            _disc("xai/grok-4-0709"),
            _disc("xai/grok-3-mini"),
        ]
        kept, _ = compute_current_generation(models)
        kept_ids = {m.id for m in kept}
        assert "xai/grok-4-0709" in kept_ids
        assert "xai/grok-3-mini" in kept_ids


class TestTierDiversityPreserved:
    def test_opus_sonnet_haiku_all_kept(self):
        models = [
            _disc("anthropic/claude-opus-4-7"),
            _disc("anthropic/claude-sonnet-4-6"),
            _disc("anthropic/claude-haiku-4-5"),
        ]
        kept, _ = compute_current_generation(models)
        kept_ids = {m.id for m in kept}
        assert kept_ids == {
            "anthropic/claude-opus-4-7",
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-haiku-4-5",
        }

    def test_old_opus_evicted_by_new_opus(self):
        models = [
            _disc("anthropic/claude-opus-4-7"),
            _disc("anthropic/claude-opus-4"),
        ]
        kept, evicted = compute_current_generation(models)
        kept_ids = {m.id for m in kept}
        assert "anthropic/claude-opus-4-7" in kept_ids
        assert "anthropic/claude-opus-4" not in kept_ids
        assert any(
            e.id == "anthropic/claude-opus-4" and "superseded" in e.reason
            for e in evicted
        )
