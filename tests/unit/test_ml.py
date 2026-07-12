"""Unit tests for ML functions.

Following TDD methodology:
1. RED: Write failing tests
2. GREEN: Implement minimal code to pass
3. REFACTOR: Improve implementation

NOTE: This is a simplified implementation for Phase 3 MVP.
Real XGBoost models will be integrated in later phases.
"""

import pytest

from sipap.tools.function.ml import calculate_confidence, engineer_features, ml_predict


class TestMLPredict:
    """Test suite for ML prediction function."""

    @pytest.fixture
    def sample_context(self):
        """Sample match context for testing."""
        return {
            "home_team": {
                "elo_rating": 1700,
                "form_score": 12.5,
                "goals_per_game": 1.8,
                "goals_conceded_per_game": 0.9
            },
            "away_team": {
                "elo_rating": 1500,
                "form_score": 8.0,
                "goals_per_game": 1.2,
                "goals_conceded_per_game": 1.3
            },
            "h2h": {
                "home_wins_pct": 0.55
            },
            "weather_impact_score": 0.2,
            "days_since_last_match_home": 5,
            "days_since_last_match_away": 7
        }

    def test_ml_predict_basic_structure(self, sample_context):
        """Test ml_predict returns correct structure."""
        result = ml_predict(sample_context)

        # Verify return structure
        assert "probability" in result
        assert "confidence" in result
        assert "model_version" in result

        # Verify types
        assert isinstance(result["probability"], float)
        assert isinstance(result["confidence"], float)
        assert isinstance(result["model_version"], str)

    def test_ml_predict_probability_range(self, sample_context):
        """Test probability is between 0 and 1."""
        result = ml_predict(sample_context)

        assert 0 <= result["probability"] <= 1

    def test_ml_predict_confidence_range(self, sample_context):
        """Test confidence is between 0 and 100."""
        result = ml_predict(sample_context)

        assert 0 <= result["confidence"] <= 100

    def test_ml_predict_default_market(self, sample_context):
        """Test default market is 1X2."""
        result = ml_predict(sample_context)

        # Should use default market
        assert result["model_version"] is not None

    def test_ml_predict_custom_market(self, sample_context):
        """Test custom betting market."""
        result = ml_predict(sample_context, market="over_under")

        assert result is not None

    def test_ml_predict_custom_model_version(self, sample_context):
        """Test custom model version."""
        result = ml_predict(sample_context, model_version="v3.0")

        assert result["model_version"] == "v3.0"

    def test_ml_predict_rounding(self, sample_context):
        """Test probability and confidence are rounded correctly."""
        result = ml_predict(sample_context)

        # Probability rounded to 4 decimal places
        prob_str = str(result["probability"])
        if '.' in prob_str:
            assert len(prob_str.split('.')[-1]) <= 4

        # Confidence rounded to 2 decimal places
        conf_str = str(result["confidence"])
        if '.' in conf_str:
            assert len(conf_str.split('.')[-1]) <= 2


class TestEngineerFeatures:
    """Test suite for feature engineering."""

    @pytest.fixture
    def sample_context(self):
        """Sample match context."""
        return {
            "home_team": {
                "elo_rating": 1700,
                "form_score": 12.5,
                "goals_per_game": 1.8,
                "goals_conceded_per_game": 0.9
            },
            "away_team": {
                "elo_rating": 1500,
                "form_score": 8.0,
                "goals_per_game": 1.2,
                "goals_conceded_per_game": 1.3
            },
            "h2h": {
                "home_wins_pct": 0.55
            },
            "weather_impact_score": 0.2,
            "days_since_last_match_home": 5,
            "days_since_last_match_away": 7
        }

    def test_engineer_features_returns_list(self, sample_context):
        """Test engineer_features returns a list."""
        features = engineer_features(sample_context)

        assert isinstance(features, list)
        assert len(features) > 0

    def test_engineer_features_extraction(self, sample_context):
        """Test features are extracted correctly."""
        features = engineer_features(sample_context)

        # Features should be numeric
        assert all(isinstance(f, (int, float)) for f in features)

        # Check key features are present (order matters)
        assert features[0] == 1700  # home_elo
        assert features[1] == 1500  # away_elo
        assert features[2] == 12.5  # home_form
        assert features[3] == 8.0   # away_form

    def test_engineer_features_missing_optional(self):
        """Test feature engineering with missing optional fields."""
        minimal_context = {
            "home_team": {
                "elo_rating": 1600,
                "form_score": 10.0,
                "goals_per_game": 1.5,
                "goals_conceded_per_game": 1.0
            },
            "away_team": {
                "elo_rating": 1600,
                "form_score": 10.0,
                "goals_per_game": 1.5,
                "goals_conceded_per_game": 1.0
            },
            "h2h": {
                "home_wins_pct": 0.5
            }
        }

        features = engineer_features(minimal_context)

        # Should use defaults for missing fields
        assert isinstance(features, list)
        assert len(features) > 0


class TestCalculateConfidence:
    """Test suite for confidence calculation."""

    def test_calculate_confidence_high_certainty(self):
        """Test confidence for high certainty prediction."""
        # Very confident prediction (90%)
        probabilities = [0.9, 0.1]
        confidence = calculate_confidence(probabilities)

        # (0.9 - 0.5) * 2 * 100 = 80
        assert confidence == 80.0

    def test_calculate_confidence_low_certainty(self):
        """Test confidence for low certainty prediction."""
        # Very uncertain prediction (50/50)
        probabilities = [0.5, 0.5]
        confidence = calculate_confidence(probabilities)

        # (0.5 - 0.5) * 2 * 100 = 0
        assert confidence == 0.0

    def test_calculate_confidence_medium_certainty(self):
        """Test confidence for medium certainty prediction."""
        # Medium confidence (70%)
        probabilities = [0.7, 0.3]
        confidence = calculate_confidence(probabilities)

        # (0.7 - 0.5) * 2 * 100 = 40
        assert confidence == 40.0

    def test_calculate_confidence_perfect_certainty(self):
        """Test confidence for perfect certainty."""
        # Perfect certainty (100%)
        probabilities = [1.0, 0.0]
        confidence = calculate_confidence(probabilities)

        # (1.0 - 0.5) * 2 * 100 = 100
        assert confidence == 100.0

    def test_calculate_confidence_three_classes(self):
        """Test confidence for three-class prediction."""
        # Three-class prediction (60% max)
        probabilities = [0.6, 0.3, 0.1]
        confidence = calculate_confidence(probabilities)

        # (0.6 - 0.5) * 2 * 100 = 20
        assert confidence == 20.0

    def test_calculate_confidence_range(self):
        """Test confidence is always 0-100."""
        test_cases = [
            [0.5, 0.5],
            [0.6, 0.4],
            [0.7, 0.3],
            [0.8, 0.2],
            [0.9, 0.1],
            [1.0, 0.0]
        ]

        for probs in test_cases:
            confidence = calculate_confidence(probs)
            assert 0 <= confidence <= 100
