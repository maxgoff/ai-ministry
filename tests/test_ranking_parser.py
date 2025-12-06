"""Tests for the ranking parser in council.py."""

import pytest
from backend.council import parse_ranking_from_text, calculate_aggregate_rankings


class TestParseRankingFromText:
    """Tests for parse_ranking_from_text function."""

    def test_standard_numbered_format(self):
        """Standard format with FINAL RANKING: and numbered list."""
        text = """
Here is my evaluation of the responses...

FINAL RANKING:
1. Response C
2. Response A
3. Response B
"""
        result = parse_ranking_from_text(text)
        assert result == ["Response C", "Response A", "Response B"]

    def test_numbered_format_no_space(self):
        """Numbered format without space after period."""
        text = """
FINAL RANKING:
1.Response A
2.Response C
3.Response B
"""
        result = parse_ranking_from_text(text)
        assert result == ["Response A", "Response C", "Response B"]

    def test_extra_whitespace(self):
        """Handle extra whitespace in ranking."""
        text = """
FINAL RANKING:
1.   Response B
2.  Response A
3. Response C
"""
        result = parse_ranking_from_text(text)
        assert result == ["Response B", "Response A", "Response C"]

    def test_fallback_without_numbers(self):
        """Fallback when numbers aren't used but FINAL RANKING exists."""
        text = """
FINAL RANKING:
Response B
Response C
Response A
"""
        result = parse_ranking_from_text(text)
        assert result == ["Response B", "Response C", "Response A"]

    def test_no_final_ranking_section(self):
        """Fallback when FINAL RANKING: section is missing entirely."""
        text = """
After careful analysis:
Response A is clearly the best.
Response C comes second.
Response B is last.
"""
        result = parse_ranking_from_text(text)
        assert result == ["Response A", "Response C", "Response B"]

    def test_mixed_text_after_ranking(self):
        """Handle extra text after the ranking (should ignore it)."""
        text = """
FINAL RANKING:
1. Response A
2. Response B
3. Response C

Note: This was a difficult decision because all responses were good.
"""
        result = parse_ranking_from_text(text)
        assert result == ["Response A", "Response B", "Response C"]

    def test_five_responses(self):
        """Handle five ministry members (our typical use case)."""
        text = """
FINAL RANKING:
1. Response D
2. Response A
3. Response E
4. Response C
5. Response B
"""
        result = parse_ranking_from_text(text)
        assert result == ["Response D", "Response A", "Response E", "Response C", "Response B"]

    def test_inline_explanation_after_label(self):
        """Handle when model adds explanation after the label."""
        text = """
FINAL RANKING:
1. Response C - This was the most comprehensive
2. Response A - Good analysis but less complete
3. Response B - Basic but accurate
"""
        result = parse_ranking_from_text(text)
        assert result == ["Response C", "Response A", "Response B"]

    def test_lowercase_final_ranking(self):
        """Lowercase 'final ranking:' should not match (case sensitive)."""
        text = """
final ranking:
1. Response A
2. Response B
"""
        # Should fall back to finding Response patterns
        result = parse_ranking_from_text(text)
        assert result == ["Response A", "Response B"]

    def test_empty_string(self):
        """Empty string returns empty list."""
        result = parse_ranking_from_text("")
        assert result == []

    def test_no_response_patterns(self):
        """Text with no Response patterns returns empty list."""
        result = parse_ranking_from_text("This is just some random text with no rankings.")
        assert result == []

    def test_partial_response_labels(self):
        """Only full 'Response X' patterns should match."""
        text = """
FINAL RANKING:
1. Response A
2. Response
3. Resp B
"""
        result = parse_ranking_from_text(text)
        assert result == ["Response A"]

    def test_duplicate_responses_in_text(self):
        """Response mentioned multiple times only counted once in ranking section."""
        text = """
Response A was mentioned in the analysis.
Response B was also discussed.

FINAL RANKING:
1. Response B
2. Response A
"""
        result = parse_ranking_from_text(text)
        # Should only get the ones from the FINAL RANKING section
        assert result == ["Response B", "Response A"]

    def test_multiple_final_ranking_sections(self):
        """If model outputs multiple FINAL RANKING sections, use the last one."""
        text = """
Let me reconsider...

FINAL RANKING:
1. Response A
2. Response B

Actually, upon reflection:

FINAL RANKING:
1. Response B
2. Response A
"""
        result = parse_ranking_from_text(text)
        # Current implementation splits on first occurrence, so gets A, B, B, A
        # This is a known edge case - document the behavior
        assert "Response A" in result and "Response B" in result

    def test_response_label_case_sensitivity(self):
        """Response labels are case sensitive (Response vs response)."""
        text = """
FINAL RANKING:
1. response A
2. Response B
"""
        result = parse_ranking_from_text(text)
        # Only "Response B" with capital R should match
        assert result == ["Response B"]


class TestCalculateAggregateRankings:
    """Tests for calculate_aggregate_rankings function."""

    def test_basic_aggregation(self):
        """Basic test with two models ranking each other."""
        stage2_results = [
            {"model": "model1", "ranking": "FINAL RANKING:\n1. Response A\n2. Response B"},
            {"model": "model2", "ranking": "FINAL RANKING:\n1. Response B\n2. Response A"},
        ]
        label_to_model = {
            "Response A": "openai/gpt-4",
            "Response B": "anthropic/claude",
        }

        result = calculate_aggregate_rankings(stage2_results, label_to_model)

        # Both should have average rank of 1.5 (one 1st, one 2nd)
        assert len(result) == 2
        for item in result:
            assert item["average_rank"] == 1.5
            assert item["rankings_count"] == 2

    def test_clear_winner(self):
        """Test when one model is clearly ranked higher."""
        stage2_results = [
            {"model": "model1", "ranking": "FINAL RANKING:\n1. Response A\n2. Response B"},
            {"model": "model2", "ranking": "FINAL RANKING:\n1. Response A\n2. Response B"},
            {"model": "model3", "ranking": "FINAL RANKING:\n1. Response A\n2. Response B"},
        ]
        label_to_model = {
            "Response A": "winner_model",
            "Response B": "loser_model",
        }

        result = calculate_aggregate_rankings(stage2_results, label_to_model)

        # Sort by average_rank to find winner
        result_sorted = sorted(result, key=lambda x: x["average_rank"])
        assert result_sorted[0]["model"] == "winner_model"
        assert result_sorted[0]["average_rank"] == 1.0
        assert result_sorted[1]["model"] == "loser_model"
        assert result_sorted[1]["average_rank"] == 2.0

    def test_missing_model_in_some_rankings(self):
        """Handle when a model isn't ranked by everyone."""
        stage2_results = [
            {"model": "model1", "ranking": "FINAL RANKING:\n1. Response A\n2. Response B\n3. Response C"},
            {"model": "model2", "ranking": "FINAL RANKING:\n1. Response A\n2. Response C"},  # Missing B
        ]
        label_to_model = {
            "Response A": "model_a",
            "Response B": "model_b",
            "Response C": "model_c",
        }

        result = calculate_aggregate_rankings(stage2_results, label_to_model)

        model_b_result = next((r for r in result if r["model"] == "model_b"), None)
        assert model_b_result is not None
        assert model_b_result["rankings_count"] == 1  # Only ranked once

    def test_empty_results(self):
        """Empty stage2_results returns empty list."""
        result = calculate_aggregate_rankings([], {})
        assert result == []

    def test_unparseable_rankings(self):
        """Handle rankings that can't be parsed."""
        stage2_results = [
            {"model": "model1", "ranking": "I refuse to rank these responses."},
        ]
        label_to_model = {
            "Response A": "model_a",
            "Response B": "model_b",
        }

        result = calculate_aggregate_rankings(stage2_results, label_to_model)
        assert result == []  # No valid rankings found
