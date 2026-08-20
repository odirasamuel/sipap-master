"""Integration test for MarketEvaluator with Rayo Vallecano vs Alaves fixture.

This test uses real tool response data captured from the Data MCP to verify
the MarketEvaluator correctly evaluates all 44 markets and returns top 3.

Fixture: Rayo Vallecano vs Alaves (La Liga)
- Home Team ID: 728 (Rayo Vallecano)
- Away Team ID: 542 (Alaves)
- League ID: 140 (La Liga)
"""

import asyncio
import json
import pytest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from sipap.sports.soccer.market_evaluator import MarketEvaluator, MarketEvaluation, MarketOutcome


# Mock tool responses based on real Data MCP outputs
MOCK_TOOL_RESPONSES = {
    # H2H Full Time Result
    "get_h2h_full_time_result": {
        "tool": "get_h2h_full_time_result",
        "data": {
            "total_matches": 11,
            "home_wins": 7,
            "draws": 2,
            "away_wins": 2,
            "home_win_probability": 0.6364,
            "draw_probability": 0.1818,
            "away_win_probability": 0.1818,
            "weighted_probabilities": {
                "home_win": 0.7143,
                "draw": 0.1429,
                "away_win": 0.1429,
            },
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # H2H Goals
    "get_h2h_goals": {
        "tool": "get_h2h_goals",
        "data": {
            "total_matches": 11,
            "total_goals": 28,
            "average_goals": 2.55,
            "over_thresholds": {
                "over_0.5": {"count": 11, "probability": 1.0},
                "over_1.5": {"count": 9, "probability": 0.8182},
                "over_2.5": {"count": 6, "probability": 0.5455},
                "over_3.5": {"count": 2, "probability": 0.1818},
                "over_4.5": {"count": 1, "probability": 0.0909},
            },
            "weighted_probabilities": {
                "over_0.5": 1.0,
                "over_1.5": 0.8571,
                "over_2.5": 0.5714,
                "over_3.5": 0.2143,
                "over_4.5": 0.1071,
            },
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # BTS
    "get_bts": {
        "tool": "get_bts",
        "data": {
            "total_matches": 11,
            "bts_matches": 5,
            "bts_probability": 0.4545,
            "weighted_bts_probability": 0.5,
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # H2H Half Time Result
    "get_h2h_half_time_result": {
        "tool": "get_h2h_half_time_result",
        "data": {
            "total_matches": 11,
            "home_leading_ht_probability": 0.3636,
            "draw_ht_probability": 0.4545,
            "away_leading_ht_probability": 0.1818,
            "weighted_probabilities": {
                "home_leading_ht": 0.4286,
                "draw_ht": 0.4143,
                "away_leading_ht": 0.1571,
            },
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # Half Time Goals
    "get_half_time_goals": {
        "tool": "get_half_time_goals",
        "data": {
            "total_matches": 11,
            "total_ht_goals": {
                "over_0.5": 0.8182,
                "over_1.5": 0.4545,
                "over_2.5": 0.1818,
            },
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # 2nd Half Result
    "get_h2h_2nd_half_result": {
        "tool": "get_h2h_2nd_half_result",
        "data": {
            "total_matches": 11,
            "home_win_2h_probability": 0.4545,
            "draw_2h_probability": 0.3636,
            "away_win_2h_probability": 0.1818,
            "weighted_probabilities": {
                "home_win_2h": 0.5,
                "draw_2h": 0.3571,
                "away_win_2h": 0.1429,
            },
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # 2nd Half Goals
    "get_2nd_half_goals": {
        "tool": "get_2nd_half_goals",
        "data": {
            "total_matches": 11,
            "total_2h_goals": {
                "over_0.5": 0.9091,
                "over_1.5": 0.5455,
                "over_2.5": 0.2727,
            },
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # HT/FT Outcome
    "get_ht_ft_outcome": {
        "tool": "get_ht_ft_outcome",
        "data": {
            "total_matches": 11,
            "outcomes": [
                {"halftime": "Home", "fulltime": "Home", "count": 3, "probability": 0.2727},
                {"halftime": "Draw", "fulltime": "Home", "count": 4, "probability": 0.3636},
                {"halftime": "Away", "fulltime": "Home", "count": 0, "probability": 0.0},
                {"halftime": "Home", "fulltime": "Draw", "count": 1, "probability": 0.0909},
                {"halftime": "Draw", "fulltime": "Draw", "count": 1, "probability": 0.0909},
                {"halftime": "Away", "fulltime": "Draw", "count": 0, "probability": 0.0},
                {"halftime": "Home", "fulltime": "Away", "count": 0, "probability": 0.0},
                {"halftime": "Draw", "fulltime": "Away", "count": 0, "probability": 0.0},
                {"halftime": "Away", "fulltime": "Away", "count": 2, "probability": 0.1818},
            ],
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # Double Chance - Home
    "get_double_chance_home": {
        "tool": "get_double_chance",
        "data": {
            "perspective": "home",
            "double_chance_probability": 0.8182,
            "weighted_probability": 0.8571,
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # Double Chance - Away
    "get_double_chance_away": {
        "tool": "get_double_chance",
        "data": {
            "perspective": "away",
            "double_chance_probability": 0.3636,
            "weighted_probability": 0.2857,
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # Home To Score
    "get_home_to_score": {
        "tool": "get_home_to_score",
        "data": {
            "total_matches": 11,
            "home_scored": 9,
            "home_to_score_probability": 0.8182,
            "weighted_probability": 0.8571,
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # Away To Score
    "get_away_to_score": {
        "tool": "get_away_to_score",
        "data": {
            "total_matches": 11,
            "away_scored": 5,
            "away_to_score_probability": 0.4545,
            "weighted_probability": 0.2857,
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # Total Goals Range
    "get_total_goals_range": {
        "tool": "get_total_goals_range",
        "data": {
            "total_matches": 11,
            "goal_distribution": {
                "0-1": {"count": 2, "probability": 0.1818},
                "2-3": {"count": 7, "probability": 0.6364},
                "4-5": {"count": 1, "probability": 0.0909},
                "6+": {"count": 1, "probability": 0.0909},
            },
            "weighted_probabilities": {
                "0-1": {"probability": 0.1429},
                "2-3": {"probability": 0.6429},
                "4-5": {"probability": 0.1071},
                "6+": {"probability": 0.1071},
            },
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # Home Either Half
    "get_home_either_half_outcome": {
        "tool": "get_home_either_half_outcome",
        "data": {
            "total_matches": 11,
            "weighted_probabilities": {
                "win_either_half": 0.7643,
            },
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # Away Either Half
    "get_away_either_half_outcome": {
        "tool": "get_away_either_half_outcome",
        "data": {
            "total_matches": 11,
            "weighted_probabilities": {
                "win_either_half": 0.2857,
            },
        },
        "metadata": {"seasons_analyzed": 8, "data_quality": "medium"},
    },
    # Home Total Goals (team form)
    "get_home_total_goals": {
        "tool": "get_home_total_goals",
        "data": {
            "total_matches": 10,
            "average_goals": 1.5,
        },
        "metadata": {"seasons_analyzed": 1, "data_quality": "medium"},
    },
    # Away Total Goals (team form)
    "get_away_total_goals": {
        "tool": "get_away_total_goals",
        "data": {
            "total_matches": 10,
            "average_goals": 0.9,
        },
        "metadata": {"seasons_analyzed": 1, "data_quality": "medium"},
    },
}


def create_mock_mcp_client() -> AsyncMock:
    """Create a mock MCP client that returns appropriate tool responses."""
    mock_client = AsyncMock()

    async def mock_call_tool(tool_name: str, params: dict) -> dict:
        """Return mock response based on tool name."""
        # Handle perspective-specific double chance calls
        if tool_name == "get_double_chance":
            perspective = params.get("perspective", "home")
            key = f"get_double_chance_{perspective}"
            return MOCK_TOOL_RESPONSES.get(key, {"data": {}, "metadata": {}})

        return MOCK_TOOL_RESPONSES.get(tool_name, {"data": {}, "metadata": {}})

    mock_client.call_tool = mock_call_tool
    return mock_client


class TestMarketEvaluator:
    """Test suite for MarketEvaluator with Rayo Vallecano vs Alaves data."""

    @pytest.mark.asyncio
    async def test_evaluate_all_44_markets(self):
        """Test that all 44 markets are evaluated."""
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,  # Rayo Vallecano
            away_team_id=542,  # Alaves
            league_id=140,     # La Liga
        )

        # Should evaluate exactly 44 markets
        assert len(evaluations) == 44, f"Expected 44 markets, got {len(evaluations)}"

        # Verify each evaluation has required fields
        for eval in evaluations:
            assert isinstance(eval, MarketEvaluation)
            assert eval.market_code
            assert eval.market_name
            assert eval.outcomes
            assert eval.best_outcome
            assert isinstance(eval.best_outcome, MarketOutcome)

    @pytest.mark.asyncio
    async def test_top_3_markets_by_probability(self):
        """Test that top 3 markets are correctly ranked by probability."""
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,
            away_team_id=542,
            league_id=140,
        )

        top_3 = evaluator.get_top_markets(evaluations, top_n=3)

        # Should return exactly 3 markets
        assert len(top_3) == 3, f"Expected 3 top markets, got {len(top_3)}"

        # Should be ranked by probability (descending)
        probs = [m["probability"] for m in top_3]
        assert probs == sorted(probs, reverse=True), "Markets not sorted by probability"

        # All should have probability >= 0.5 (default threshold)
        for market in top_3:
            assert market["probability"] >= 0.5, f"Market {market['market_code']} below threshold"

        # Print top 3 for verification
        print("\n=== TOP 3 MARKETS ===")
        for m in top_3:
            print(f"Rank {m['rank']}: {m['market_name']} - {m['best_outcome']} ({m['probability']:.4f})")

    @pytest.mark.asyncio
    async def test_main_markets_1x2(self):
        """Test 1X2 market evaluation."""
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,
            away_team_id=542,
            league_id=140,
        )

        # Find 1X2 market
        ftr_eval = next((e for e in evaluations if e.market_code == "1X2"), None)
        assert ftr_eval is not None, "1X2 market not found"

        # Should have 3 outcomes
        assert len(ftr_eval.outcomes) == 3

        # Best outcome should be Home Win (highest probability)
        assert ftr_eval.best_outcome.outcome_code == "Home Win"
        assert ftr_eval.best_outcome.weighted_probability == pytest.approx(0.7143, abs=0.01)

    @pytest.mark.asyncio
    async def test_btts_market(self):
        """Test BTTS market evaluation."""
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,
            away_team_id=542,
            league_id=140,
        )

        # Find BTTS market
        btts_eval = next((e for e in evaluations if e.market_code == "BTTS"), None)
        assert btts_eval is not None, "BTTS market not found"

        # Should have 2 outcomes (Yes/No)
        assert len(btts_eval.outcomes) == 2

        # With 50% BTTS probability, outcomes should be close
        yes_outcome = next((o for o in btts_eval.outcomes if o.outcome_code == "Yes"), None)
        no_outcome = next((o for o in btts_eval.outcomes if o.outcome_code == "No"), None)
        assert yes_outcome.weighted_probability == pytest.approx(0.5, abs=0.01)
        assert no_outcome.weighted_probability == pytest.approx(0.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_halftime_double_chance(self):
        """Test Half-Time Double Chance market."""
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,
            away_team_id=542,
            league_id=140,
        )

        # Find HT_DC market
        ht_dc = next((e for e in evaluations if e.market_code == "HT_DC"), None)
        assert ht_dc is not None, "HT_DC market not found"

        # 1X outcome (home_leading + draw) should be highest
        # 0.4286 + 0.4143 = 0.8429
        one_x = next((o for o in ht_dc.outcomes if o.outcome_code == "1X"), None)
        assert one_x is not None
        assert one_x.weighted_probability == pytest.approx(0.8429, abs=0.01)

    @pytest.mark.asyncio
    async def test_chance_mix_or_logic(self):
        """Test Chance Mix markets use OR logic correctly."""
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,
            away_team_id=542,
            league_id=140,
        )

        # Find CHANCEMIX_1X2_OU25 market
        chance_mix = next(
            (e for e in evaluations if e.market_code == "CHANCEMIX_1X2_OU25"), None
        )
        assert chance_mix is not None, "CHANCEMIX_1X2_OU25 market not found"

        # OR logic: P(A OR B) = P(A) + P(B) - P(A AND B)
        # P(Home OR Over2.5) = 0.7143 + 0.5714 - (0.7143 * 0.5714) = 0.8778
        home_or_over = next((o for o in chance_mix.outcomes if o.outcome_code == "1orOver"), None)
        assert home_or_over is not None
        expected = 0.7143 + 0.5714 - (0.7143 * 0.5714)
        assert home_or_over.weighted_probability == pytest.approx(expected, abs=0.01)

    @pytest.mark.asyncio
    async def test_market_evaluation_to_dict(self):
        """Test MarketEvaluation.to_dict() serialization."""
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,
            away_team_id=542,
            league_id=140,
        )

        # Convert all to dict and verify structure
        for eval in evaluations:
            d = eval.to_dict()
            assert "market_code" in d
            assert "market_name" in d
            assert "best_outcome" in d
            assert "probability" in d
            assert "all_outcomes" in d
            assert isinstance(d["all_outcomes"], list)

    @pytest.mark.asyncio
    async def test_minimum_probability_filter(self):
        """Test that minimum probability filter works correctly."""
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,
            away_team_id=542,
            league_id=140,
        )

        # Get markets with high threshold
        top_markets = evaluator.get_top_markets(
            evaluations,
            top_n=10,
            min_probability=0.8,
        )

        # All returned markets should meet threshold
        for m in top_markets:
            assert m["probability"] >= 0.8, f"Market {m['market_code']} below 0.8 threshold"

    @pytest.mark.asyncio
    async def test_data_quality_in_results(self):
        """Test that data quality is included in results."""
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,
            away_team_id=542,
            league_id=140,
        )

        top_3 = evaluator.get_top_markets(evaluations, top_n=3)

        for market in top_3:
            assert "data_quality" in market
            assert market["data_quality"] in ["high", "medium", "low"]


def run_standalone_test():
    """Run test standalone (outside pytest)."""
    import asyncio

    async def main():
        mock_mcp = create_mock_mcp_client()
        evaluator = MarketEvaluator(mock_mcp)

        print("=" * 60)
        print("Testing MarketEvaluator with Rayo Vallecano vs Alaves")
        print("=" * 60)

        evaluations = await evaluator.evaluate_all_markets(
            home_team_id=728,
            away_team_id=542,
            league_id=140,
        )

        print(f"\nTotal markets evaluated: {len(evaluations)}")

        # Group by category
        categories = {
            "Main (1X2, DNB, BTTS, DC, OU)": [],
            "Halftime": [],
            "2nd Half": [],
            "Team Specific": [],
            "HT/FT": [],
            "Combination AND": [],
            "Chance Mix OR": [],
            "Advanced": [],
        }

        for e in evaluations:
            code = e.market_code
            if code in ["1X2", "DNB", "BTTS", "DC"] or code.startswith("OU"):
                categories["Main (1X2, DNB, BTTS, DC, OU)"].append(e)
            elif code.startswith("HT_"):
                categories["Halftime"].append(e)
            elif code.startswith("2H_"):
                categories["2nd Half"].append(e)
            elif code in ["HOME_SCORE", "AWAY_SCORE", "HOME_WIN_HALF", "AWAY_WIN_HALF", "HOME_TO_SCORE", "AWAY_TO_SCORE"]:
                categories["Team Specific"].append(e)
            elif code == "HT/FT":
                categories["HT/FT"].append(e)
            elif code.startswith("CHANCEMIX"):
                categories["Chance Mix OR"].append(e)
            elif "_" in code and not code.startswith("HT_") and not code.startswith("2H_"):
                categories["Combination AND"].append(e)
            else:
                categories["Advanced"].append(e)

        print("\n--- Markets by Category ---")
        for cat, markets in categories.items():
            print(f"\n{cat}: {len(markets)} markets")
            for m in markets[:3]:  # Show first 3 of each category
                print(f"  - {m.market_code}: {m.best_outcome.outcome_code} ({m.best_outcome.weighted_probability:.4f})")

        # Get top 3
        top_3 = evaluator.get_top_markets(evaluations, top_n=3)

        print("\n" + "=" * 60)
        print("TOP 3 MARKETS (Highest Probability)")
        print("=" * 60)
        for m in top_3:
            print(f"\nRank #{m['rank']}: {m['market_name']}")
            print(f"  Market Code: {m['market_code']}")
            print(f"  Best Outcome: {m['best_outcome']}")
            print(f"  Probability: {m['probability']:.4f} ({m['probability']*100:.2f}%)")
            print(f"  Data Quality: {m['data_quality']}")
            print(f"  Matches Analyzed: {m['matches_analyzed']}")

        return evaluations, top_3

    return asyncio.run(main())


if __name__ == "__main__":
    run_standalone_test()
