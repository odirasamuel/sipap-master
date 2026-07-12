"""Unit tests for statistical analysis functions.

Following TDD methodology:
1. RED: Write failing tests
2. GREEN: Implement minimal code to pass
3. REFACTOR: Improve implementation
"""

from sipap.tools.function.statistical import elo_rating, form_score, poisson_model, xg_calculator


class TestPoissonModel:
    """Test suite for Poisson model predictions."""

    def test_poisson_model_basic_calculation(self):
        """Test basic Poisson model calculation."""
        result = poisson_model(
            home_avg_goals=1.8,
            away_avg_goals=1.2,
            league_avg_goals=1.5
        )

        # Verify return structure
        assert "home_win" in result
        assert "draw" in result
        assert "away_win" in result
        assert "home_xg" in result
        assert "away_xg" in result

        # Verify probabilities sum to 1
        assert abs(result["home_win"] + result["draw"] + result["away_win"] - 1.0) < 0.01

        # Verify probabilities are between 0 and 1
        assert 0 <= result["home_win"] <= 1
        assert 0 <= result["draw"] <= 1
        assert 0 <= result["away_win"] <= 1

    def test_poisson_model_home_advantage(self):
        """Test that home advantage is applied correctly."""
        result = poisson_model(
            home_avg_goals=1.5,
            away_avg_goals=1.5,
            league_avg_goals=1.5
        )

        # Home xG should be higher due to 1.3x home advantage
        assert result["home_xg"] > result["away_xg"]
        assert result["home_xg"] == round(1.5 * 1.3, 2)
        assert result["away_xg"] == 1.5

    def test_poisson_model_strong_home_team(self):
        """Test prediction for strong home team vs weak away team."""
        result = poisson_model(
            home_avg_goals=2.5,
            away_avg_goals=0.8,
            league_avg_goals=1.5
        )

        # Home win should be most likely outcome
        assert result["home_win"] > result["draw"]
        assert result["home_win"] > result["away_win"]

    def test_poisson_model_strong_away_team(self):
        """Test prediction for weak home team vs strong away team."""
        result = poisson_model(
            home_avg_goals=0.8,
            away_avg_goals=2.5,
            league_avg_goals=1.5
        )

        # Away win should be most likely outcome (even with home advantage)
        assert result["away_win"] > result["draw"]
        # Note: Strong away team can still beat home advantage

    def test_poisson_model_default_league_average(self):
        """Test that default league average is used correctly."""
        result = poisson_model(
            home_avg_goals=1.5,
            away_avg_goals=1.5
        )

        # Verify it uses default league_avg_goals=1.5
        assert result["home_xg"] == round(1.5 * 1.3, 2)
        assert result["away_xg"] == 1.5

    def test_poisson_model_rounding(self):
        """Test that probabilities are rounded correctly."""
        result = poisson_model(
            home_avg_goals=1.7,
            away_avg_goals=1.3,
            league_avg_goals=1.5
        )

        # Verify rounding to 4 decimal places for probabilities
        assert len(str(result["home_win"]).split('.')[-1]) <= 4
        assert len(str(result["draw"]).split('.')[-1]) <= 4
        assert len(str(result["away_win"]).split('.')[-1]) <= 4

        # Verify rounding to 2 decimal places for xG
        assert len(str(result["home_xg"]).split('.')[-1]) <= 2
        assert len(str(result["away_xg"]).split('.')[-1]) <= 2


class TestXGCalculator:
    """Test suite for expected goals calculator."""

    def test_xg_calculator_single_shot(self):
        """Test xG calculation for single shot."""
        shots = [{"location": "box"}]
        result = xg_calculator(shots, league_avg_conversion=0.10)

        # Box shot should have 0.12 xG
        assert result == 0.12

    def test_xg_calculator_multiple_shots(self):
        """Test xG calculation for multiple shots."""
        shots = [
            {"location": "box"},
            {"location": "box"},
            {"location": "six_yard"}
        ]
        result = xg_calculator(shots)

        # 0.12 + 0.12 + 0.35 = 0.59
        assert result == 0.59

    def test_xg_calculator_header_penalty(self):
        """Test xG calculation with header penalty."""
        shots = [
            {"location": "box", "header": True}
        ]
        result = xg_calculator(shots)

        # 0.12 * 0.7 = 0.084 → rounds to 0.08
        assert result == 0.08

    def test_xg_calculator_volley_penalty(self):
        """Test xG calculation with volley penalty."""
        shots = [
            {"location": "box", "volley": True}
        ]
        result = xg_calculator(shots)

        # 0.12 * 0.8 = 0.096 → rounds to 0.10
        assert result == 0.10

    def test_xg_calculator_penalty_location(self):
        """Test xG calculation for penalty."""
        shots = [{"location": "penalty"}]
        result = xg_calculator(shots)

        assert result == 0.76

    def test_xg_calculator_outside_box(self):
        """Test xG calculation for outside box shot."""
        shots = [{"location": "outside_box"}]
        result = xg_calculator(shots)

        assert result == 0.03

    def test_xg_calculator_unknown_location(self):
        """Test xG calculation for unknown location."""
        shots = [{"location": "unknown"}]
        result = xg_calculator(shots)

        # Unknown location defaults to 0.05
        assert result == 0.05

    def test_xg_calculator_missing_location(self):
        """Test xG calculation when location is missing."""
        shots = [{}]
        result = xg_calculator(shots)

        # Missing location defaults to "box" → 0.12
        assert result == 0.12

    def test_xg_calculator_empty_shots(self):
        """Test xG calculation with no shots."""
        shots = []
        result = xg_calculator(shots)

        assert result == 0.0

    def test_xg_calculator_complex_scenario(self):
        """Test xG calculation for complex scenario."""
        shots = [
            {"location": "penalty"},  # 0.76
            {"location": "six_yard", "header": True},  # 0.35 * 0.7 = 0.245
            {"location": "box"},  # 0.12
            {"location": "outside_box", "volley": True},  # 0.03 * 0.8 = 0.024
        ]
        result = xg_calculator(shots)

        # Total: 0.76 + 0.245 + 0.12 + 0.024 = 1.149 → rounds to 1.15
        assert result == 1.15


class TestEloRating:
    """Test suite for Elo rating calculations."""

    def test_elo_rating_equal_teams(self):
        """Test Elo calculation for equal teams."""
        result = elo_rating(team_elo=1500, opponent_elo=1500)

        # Equal teams should have 50% win probability
        assert result["win_probability"] == 0.5
        assert result["elo_difference"] == 0
        assert result["team_elo"] == 1500
        assert result["opponent_elo"] == 1500

    def test_elo_rating_stronger_team(self):
        """Test Elo calculation for stronger team."""
        result = elo_rating(team_elo=1700, opponent_elo=1500)

        # Stronger team should have >50% win probability
        assert result["win_probability"] > 0.5
        assert result["elo_difference"] == 200

    def test_elo_rating_weaker_team(self):
        """Test Elo calculation for weaker team."""
        result = elo_rating(team_elo=1300, opponent_elo=1500)

        # Weaker team should have <50% win probability
        assert result["win_probability"] < 0.5
        assert result["elo_difference"] == -200

    def test_elo_rating_large_difference(self):
        """Test Elo calculation for large rating difference."""
        result = elo_rating(team_elo=2000, opponent_elo=1200)

        # Very strong team should have very high win probability
        assert result["win_probability"] > 0.95
        assert result["elo_difference"] == 800

    def test_elo_rating_formula_accuracy(self):
        """Test Elo formula accuracy."""
        result = elo_rating(team_elo=1600, opponent_elo=1500)

        # Manual calculation: 1 / (1 + 10^((-100)/400))
        # = 1 / (1 + 10^(-0.25))
        # = 1 / (1 + 0.5623...)
        # ≈ 0.6400
        expected_prob = 1 / (1 + 10 ** ((-100) / 400))
        assert result["win_probability"] == round(expected_prob, 4)

    def test_elo_rating_rounding(self):
        """Test that win probability is rounded correctly."""
        result = elo_rating(team_elo=1555, opponent_elo=1444)

        # Verify rounding to 4 decimal places
        assert len(str(result["win_probability"]).split('.')[-1]) <= 4


class TestFormScore:
    """Test suite for form score calculations."""

    def test_form_score_perfect_form(self):
        """Test form score for perfect form (all wins)."""
        result = form_score(recent_results=["W", "W", "W", "W", "W"])

        # Perfect form should be 15 points
        assert result["form_score"] == 15.0
        assert result["momentum"] in ["up", "stable"]
        assert result["recent_points"] == [3, 3, 3, 3, 3]

    def test_form_score_terrible_form(self):
        """Test form score for terrible form (all losses)."""
        result = form_score(recent_results=["L", "L", "L", "L", "L"])

        # Terrible form should be 0 points
        assert result["form_score"] == 0.0
        assert result["momentum"] in ["down", "stable"]
        assert result["recent_points"] == [0, 0, 0, 0, 0]

    def test_form_score_mixed_results(self):
        """Test form score for mixed results."""
        result = form_score(recent_results=["W", "D", "L", "W", "D"])

        # Verify structure
        assert "form_score" in result
        assert "momentum" in result
        assert "recent_points" in result
        assert "weighted_score" in result

        # Form score should be between 0 and 15
        assert 0 <= result["form_score"] <= 15

        assert result["recent_points"] == [3, 1, 0, 3, 1]

    def test_form_score_recent_weight(self):
        """Test that recent matches are weighted more heavily."""
        # Recent wins
        recent_wins = form_score(["W", "W", "L", "L", "L"])
        # Old wins
        old_wins = form_score(["L", "L", "L", "W", "W"])

        # Recent wins should score higher
        assert recent_wins["form_score"] > old_wins["form_score"]

    def test_form_score_momentum_up(self):
        """Test momentum calculation for improving form."""
        result = form_score(["W", "W", "L", "L", "L"])

        # Recent results (W, W) better than older (L, L, L)
        assert result["momentum"] == "up"

    def test_form_score_momentum_down(self):
        """Test momentum calculation for declining form."""
        result = form_score(["L", "L", "W", "W", "W"])

        # Recent results (L, L) worse than older (W, W, W)
        assert result["momentum"] == "down"

    def test_form_score_momentum_stable(self):
        """Test momentum calculation for stable form."""
        result = form_score(["W", "W", "W", "W", "W"])

        # All wins → stable
        assert result["momentum"] in ["stable", "up"]

    def test_form_score_short_history(self):
        """Test form score with short match history."""
        result = form_score(["W", "W"])

        # Should still calculate but momentum unknown
        assert result["form_score"] > 0
        assert result["momentum"] == "unknown"
        assert len(result["recent_points"]) == 2

    def test_form_score_single_match(self):
        """Test form score with single match."""
        result = form_score(["W"])

        assert result["form_score"] > 0
        assert result["momentum"] == "unknown"

    def test_form_score_invalid_result(self):
        """Test form score with invalid result codes."""
        result = form_score(["W", "X", "L"])  # "X" is invalid

        # Invalid results should default to 0 points
        assert result["recent_points"] == [3, 0, 0]

    def test_form_score_weighted_calculation(self):
        """Test weighted score calculation accuracy."""
        result = form_score(["W", "D", "L"])

        # Weights: [2.0, 1.5, 1.2]
        # Points: [3, 1, 0]
        # Weighted: 3*2.0 + 1*1.5 + 0*1.2 = 6.0 + 1.5 + 0 = 7.5
        assert result["weighted_score"] == 7.5

        # Max weighted: 3*2.0 + 3*1.5 + 3*1.2 = 6.0 + 4.5 + 3.6 = 14.1
        # Form score: (7.5 / 14.1) * 15 ≈ 7.98
        expected_form = (7.5 / 14.1) * 15
        assert result["form_score"] == round(expected_form, 2)
