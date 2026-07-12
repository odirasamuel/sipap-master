"""Integration tests for end-to-end prediction pipeline.

Tests the complete flow:
1. Context aggregation from MCP servers
2. Context quality validation
3. Ensemble prediction generation
4. Expected value calculation
5. Quality gates application
6. Prediction persistence
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sipap.core.orchestrator import MainOrchestrator
from sipap.sports.soccer.orchestrator import SoccerOrchestrator


@pytest.fixture
def mock_mcp_factory():
    """Mock MCPFactory with test data."""
    with patch("sipap.core.orchestrator.SoccerOrchestrator") as mock:
        # Create mock orchestrator
        orchestrator = MagicMock(spec=SoccerOrchestrator)

        # Mock aggregate_context
        orchestrator.aggregate_context = AsyncMock(
            return_value={
                "match_id": "test_match",
                "fixture": {"home": "Team A", "away": "Team B"},
                "home_team": {
                    "name": "Team A",
                    "stats": {"goals": 25, "conceded": 10},
                    "form": ["W", "W", "D", "W", "L"],
                    "injuries": [],
                },
                "away_team": {
                    "name": "Team B",
                    "stats": {"goals": 18, "conceded": 15},
                    "form": ["L", "L", "W", "D", "D"],
                    "injuries": ["Player X"],
                },
                "head_to_head": {"matches": 5, "home_wins": 3},
                "odds": {"Home Win": 2.0, "Draw": 3.5, "Away Win": 4.0},
                "weather": {"condition": "clear", "temperature": 20},
            }
        )

        # Mock validate_context_quality
        orchestrator.validate_context_quality.return_value = {
            "status": "PASSED",
            "reason": "All quality checks passed",
            "missing_critical": [],
            "missing_optional": [],
            "data_completeness": 100.0,
        }

        # Mock _calculate_ensemble
        orchestrator._calculate_ensemble.return_value = {
            "market": "1X2",
            "outcome": "Home Win",
            "probability": 0.60,
            "confidence": 75.0,
            "reasoning": "Ensemble prediction favors home team",
            "evidence": ["Home team in better form", "H2H favors home team"],
            "agent_predictions": [],
        }

        # Mock calculate_expected_value
        orchestrator.calculate_expected_value.return_value = {
            "expected_value": 0.20,
            "edge": 0.10,
            "is_positive_ev": True,
            "our_probability": 0.60,
            "implied_probability": 0.50,
            "odds": 2.0,
            "recommendation": "PLACE BET - Positive expected value",
        }

        # Mock _apply_quality_gates
        orchestrator._apply_quality_gates.return_value = {
            "market": "1X2",
            "outcome": "Home Win",
            "probability": 0.60,
            "confidence": 75.0,
            "quality_gate": "PASSED",
            "recommendation": "Prediction ready for user",
            "reasoning": "Ensemble prediction favors home team",
            "evidence": ["Home team in better form", "H2H favors home team"],
            "expected_value": {
                "expected_value": 0.20,
                "is_positive_ev": True,
            },
        }

        # Mock save_prediction
        orchestrator.save_prediction = AsyncMock(
            return_value={
                "status": "SUCCESS",
                "prediction_id": "test_prediction_123",
                "message": "Prediction saved",
            }
        )

        mock.return_value = orchestrator
        yield mock


@pytest.mark.asyncio
async def test_end_to_end_prediction_pipeline(mock_mcp_factory):
    """
    Test complete prediction pipeline from request to response.

    Verifies:
    1. Context aggregation works
    2. Context validation passes
    3. Ensemble calculation completes
    4. EV calculation returns valid result
    5. Quality gates are applied
    6. Prediction is saved
    """
    # Initialize orchestrator
    orchestrator = MainOrchestrator()

    # Generate prediction
    result = await orchestrator.predict(
        sport="soccer",
        match_id="test_match",
        market="1X2",
    )

    # Verify result structure
    assert result is not None
    assert "quality_gate" in result
    assert "recommendation" in result
    assert "expected_value" in result

    # Verify quality gate passed
    assert result["quality_gate"] == "PASSED"

    # Verify EV is positive
    assert result["expected_value"]["is_positive_ev"] is True

    # Verify save result is included
    assert "save_result" in result
    assert result["save_result"]["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_prediction_with_insufficient_data():
    """
    Test prediction fails gracefully when data quality is insufficient.

    Verifies:
    1. Context validation detects missing data
    2. Prediction fails with proper error message
    3. Recommendation is to skip bet
    """
    with patch("sipap.core.orchestrator.SoccerOrchestrator") as mock:
        orchestrator_instance = MagicMock(spec=SoccerOrchestrator)

        # Mock aggregate_context with missing critical data
        orchestrator_instance.aggregate_context = AsyncMock(
            return_value={
                "match_id": "test_match",
                "fixture": None,  # Missing critical data
                "home_team": {"name": "Team A"},
                "away_team": {"name": "Team B"},
            }
        )

        # Mock validate_context_quality to fail
        orchestrator_instance.validate_context_quality.return_value = {
            "status": "FAILED",
            "reason": "Missing critical fields: fixture, odds",
            "missing_critical": ["fixture", "odds"],
            "data_completeness": 40.0,
        }

        mock.return_value = orchestrator_instance

        orchestrator = MainOrchestrator()
        result = await orchestrator.predict(
            sport="soccer",
            match_id="test_match",
            market="1X2",
        )

        # Verify failure
        assert result["status"] == "FAILED"
        assert "Insufficient data quality" in result["recommendation"]


@pytest.mark.asyncio
async def test_prediction_quality_gates_enforcement():
    """
    Test quality gates properly reject low-confidence predictions.

    Verifies:
    1. Low confidence triggers quality gate failure
    2. Recommendation is to skip bet
    """
    with patch("sipap.core.orchestrator.SoccerOrchestrator") as mock:
        orchestrator_instance = MagicMock(spec=SoccerOrchestrator)

        # Mock successful context aggregation
        orchestrator_instance.aggregate_context = AsyncMock(
            return_value={
                "match_id": "test_match",
                "fixture": {"home": "Team A", "away": "Team B"},
                "odds": {"Home Win": 2.0},
            }
        )

        orchestrator_instance.validate_context_quality.return_value = {
            "status": "PASSED",
            "data_completeness": 100.0,
        }

        # Mock low-confidence ensemble
        orchestrator_instance._calculate_ensemble.return_value = {
            "outcome": "Home Win",
            "probability": 0.45,  # Below 50% threshold
            "confidence": 40.0,  # Below 55% threshold
        }

        orchestrator_instance.calculate_expected_value.return_value = {
            "expected_value": -0.10,
            "is_positive_ev": False,
        }

        # Mock quality gate failure
        orchestrator_instance._apply_quality_gates.return_value = {
            "quality_gate": "FAILED",
            "reason": "Confidence below threshold (55%)",
            "recommendation": "Do not place bet",
            "expected_value": {"is_positive_ev": False},
        }

        orchestrator_instance.save_prediction = AsyncMock(
            return_value={"status": "SUCCESS"}
        )

        mock.return_value = orchestrator_instance

        orchestrator = MainOrchestrator()
        result = await orchestrator.predict(
            sport="soccer",
            match_id="test_match",
            market="1X2",
        )

        # Verify quality gate failed
        assert result["quality_gate"] == "FAILED"
        assert "Do not place bet" in result["recommendation"]


@pytest.mark.asyncio
async def test_prediction_unsupported_sport():
    """
    Test proper error handling for unsupported sports.

    Verifies:
    1. ValueError is raised for unsupported sport
    2. Error message lists available sports
    """
    orchestrator = MainOrchestrator()

    with pytest.raises(ValueError) as exc_info:
        await orchestrator.predict(
            sport="cricket",  # Not supported
            match_id="test_match",
            market="Winner",
        )

    assert "not supported" in str(exc_info.value)
    assert "soccer" in str(exc_info.value)


@pytest.mark.asyncio
async def test_expected_value_calculation():
    """
    Test expected value calculation with various scenarios.

    Verifies:
    1. +EV detected when our probability > implied probability
    2. -EV detected when our probability < implied probability
    3. Edge is calculated correctly
    """
    orchestrator = SoccerOrchestrator()

    # Test Case 1: Strong +EV
    prediction = {"outcome": "Home Win", "probability": 0.70}
    odds = {"Home Win": 2.0}  # Implied prob = 0.50

    ev = orchestrator.calculate_expected_value(prediction, odds)

    assert ev["is_positive_ev"] is True
    assert ev["expected_value"] > 0
    assert ev["edge"] == pytest.approx(0.20, abs=0.01)

    # Test Case 2: -EV
    prediction = {"outcome": "Home Win", "probability": 0.40}
    odds = {"Home Win": 2.0}  # Implied prob = 0.50

    ev = orchestrator.calculate_expected_value(prediction, odds)

    assert ev["is_positive_ev"] is False
    assert ev["expected_value"] < 0
    assert ev["edge"] < 0


def test_orchestrator_supports_multiple_sports():
    """
    Test that MainOrchestrator tracks supported sports correctly.

    Verifies:
    1. Supported sports list is accurate
    2. Soccer is included
    """
    orchestrator = MainOrchestrator()
    sports = orchestrator.get_supported_sports()

    assert "soccer" in sports
    assert len(sports) >= 1
