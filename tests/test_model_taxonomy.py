"""Tests for backend/model_taxonomy.py — covers tier-ordering bug fixes."""

from backend.model_taxonomy import parse_model


class TestTierParsing:
    def test_non_reasoning_beats_reasoning(self):
        """Fix #1: non-reasoning must NOT match the substring 'reasoning'."""
        p = parse_model("xai/grok-4.20-0309-non-reasoning")
        assert p.tier == "non-reasoning"

    def test_reasoning_still_matches_when_pure(self):
        p = parse_model("xai/grok-4.20-0309-reasoning")
        assert p.tier == "reasoning"

    def test_non_thinking_beats_thinking(self):
        p = parse_model("moonshotai/kimi-k3-non-thinking")
        assert p.tier == "non-thinking"

    def test_thinking_still_matches_when_pure(self):
        p = parse_model("moonshotai/kimi-k2-thinking")
        assert p.tier == "thinking"

    def test_non_fast_beats_fast(self):
        p = parse_model("xai/grok-4-1-non-fast")
        assert p.tier == "non-fast"

    def test_fast_still_matches_when_pure(self):
        p = parse_model("xai/grok-4-1-fast")
        assert p.tier == "fast"


class TestFamilyAndVersion:
    def test_claude_opus(self):
        p = parse_model("anthropic/claude-opus-4-7")
        assert p.family == "claude"
        assert p.tier == "opus"
        assert p.version == (4, 7)

    def test_gpt_no_tier(self):
        p = parse_model("openai/gpt-5.2")
        assert p.family == "gpt"
        assert p.tier == ""
        assert p.version == (5, 2)

    def test_unknown_is_other(self):
        p = parse_model("randomprovider/some-weird-model-x9")
        assert p.family == "other"
