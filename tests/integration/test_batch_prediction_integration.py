"""Integration tests for batch prediction flow.

Tests the end-to-end flow:
User message → NLU parsing → BatchOrchestrator → Response formatting

NOTE: These tests require full NLU functionality (Claude NLU via AWS Bedrock)
to correctly classify user intents. When AWS Bedrock is not available,
the regex fallback may misclassify intents.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sipap.core.orchestrator import MainOrchestrator


# Marker for tests that require AWS Bedrock access for NLU
NEEDS_AWS_BEDROCK = pytest.mark.skip(
    reason="Requires AWS Bedrock access for Claude NLU - integration test"
)


class TestBatchPredictionIntegration:
    """Test end-to-end batch prediction flow.

    NOTE: Tests test_handle_user_message_batch_prediction and
    test_handle_user_message_batch_prediction_exception require
    Claude NLU to correctly classify intent.
    """

    @pytest.fixture
    def orchestrator(self):
        """Create MainOrchestrator for testing."""
        logger = MagicMock()
        return MainOrchestrator(logger=logger)

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_handle_user_message_batch_prediction(self, orchestrator):
        """Test: 'I need 20 odds with highest positive outcome' → batch prediction response."""
        message = "I need 20 odds with highest positive outcome"
        user_id = "test_user_123"

        # Mock BatchOrchestrator.process_batch_request to return successful result
        mock_result = {
            "accumulated_odds": 20.3,
            "target_odds": 20.0,
            "selections": [
                {
                    "fixture": {
                        "id": "match1",
                        "home_team": {"name": "Arsenal"},
                        "away_team": {"name": "Chelsea"},
                    },
                    "market_code": "1X2",
                    "market_name": "Match Result",
                    "best_outcome": "Home Win",
                    "bookmaker_odd": 2.5,
                    "confidence": 0.75,
                    "ev": 0.08,
                    "markets_evaluated": 44,
                },
                {
                    "fixture": {
                        "id": "match2",
                        "home_team": {"name": "Barcelona"},
                        "away_team": {"name": "Real Madrid"},
                    },
                    "market_code": "BTTS",
                    "market_name": "Both Teams To Score",
                    "best_outcome": "Yes",
                    "bookmaker_odd": 3.0,
                    "confidence": 0.72,
                    "ev": 0.10,
                    "markets_evaluated": 44,
                },
                {
                    "fixture": {
                        "id": "match3",
                        "home_team": {"name": "Bayern Munich"},
                        "away_team": {"name": "Borussia Dortmund"},
                    },
                    "market_code": "OU2.5",
                    "market_name": "Total Goals Over/Under 2.5",
                    "best_outcome": "Over 2.5",
                    "bookmaker_odd": 14.8,
                    "confidence": 0.70,
                    "ev": 0.12,
                    "markets_evaluated": 44,
                },
            ],
            "filters_applied": {
                "leagues": None,
                "date_range": None,
                "quality_threshold": "highest",
                "thresholds": {"min_confidence": 0.70, "min_ev": 0.10},
            },
            "warning": None,
            "error": None,
        }

        orchestrator.batch_orchestrator.process_batch_request = AsyncMock(
            return_value=mock_result
        )

        # Call handle_user_message
        response = await orchestrator.handle_user_message(user_id, message)

        # Verify response structure
        assert response["intent"] == "batch_prediction"
        assert response["error"] is None
        assert "message" in response
        assert "data" in response

        # Verify data contains result
        assert response["data"]["accumulated_odds"] == 20.3
        assert response["data"]["target_odds"] == 20.0
        assert len(response["data"]["selections"]) == 3

        # Verify message formatting
        assert "20.3 odds" in response["message"]
        assert "3 fixtures" in response["message"]
        assert "Arsenal vs Chelsea" in response["message"]
        assert "Home Win @ 2.5" in response["message"]
        # Verify market explanation is included
        assert "Market: Match Result (1X2)" in response["message"]
        assert "Market: Both Teams To Score (BTTS)" in response["message"]
        assert "Market: Total Goals Over/Under 2.5 (OU2.5)" in response["message"]

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_handle_user_message_batch_prediction_with_filters(self, orchestrator):
        """Test batch prediction with league and date filters."""
        # Include markets (1X2, BTTS) to pass market validation
        message = "Give me 30 1X2 and BTTS odds in Premier League and LaLiga between Aug 3-10"
        user_id = "test_user_456"

        # Mock successful result with filters
        mock_result = {
            "accumulated_odds": 30.2,
            "target_odds": 30.0,
            "selections": [
                {
                    "fixture": {
                        "id": "match1",
                        "home_team": {"name": "Team A"},
                        "away_team": {"name": "Team B"},
                    },
                    "best_outcome": "Home Win",
                    "bookmaker_odd": 15.1,
                    "confidence": 0.65,
                    "ev": 0.06,
                },
                {
                    "fixture": {
                        "id": "match2",
                        "home_team": {"name": "Team C"},
                        "away_team": {"name": "Team D"},
                    },
                    "best_outcome": "BTTS Yes",
                    "bookmaker_odd": 15.1,
                    "confidence": 0.68,
                    "ev": 0.07,
                },
            ],
            "filters_applied": {
                "leagues": ["Premier League", "LaLiga"],
                "date_range": {"start": "2026-08-03", "end": "2026-08-10"},
                "quality_threshold": "high",
            },
            "warning": None,
            "error": None,
        }

        orchestrator.batch_orchestrator.process_batch_request = AsyncMock(
            return_value=mock_result
        )

        response = await orchestrator.handle_user_message(user_id, message)

        # Verify filters appear in message
        assert "Premier League" in response["message"]
        assert "LaLiga" in response["message"]
        assert "2026-08-03" in response["message"]
        assert "2026-08-10" in response["message"]

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_handle_user_message_batch_prediction_warning(self, orchestrator):
        """Test batch prediction that doesn't reach target (warning)."""
        # Include market (1X2) to pass market validation
        message = "I need 50 1X2 sure odds"
        user_id = "test_user_789"

        # Mock result with warning (target not reached)
        mock_result = {
            "accumulated_odds": 15.5,
            "target_odds": 50.0,
            "selections": [
                {
                    "fixture": {
                        "id": "match1",
                        "home_team": {"name": "Team X"},
                        "away_team": {"name": "Team Y"},
                    },
                    "best_outcome": "Home Win",
                    "bookmaker_odd": 8.0,
                    "confidence": 0.75,
                    "ev": 0.12,
                },
                {
                    "fixture": {
                        "id": "match2",
                        "home_team": {"name": "Team Z"},
                        "away_team": {"name": "Team W"},
                    },
                    "best_outcome": "Draw",
                    "bookmaker_odd": 7.5,
                    "confidence": 0.72,
                    "ev": 0.10,
                },
            ],
            "filters_applied": {
                "quality_threshold": "highest",
            },
            "warning": "Only accumulated 15.5 odds (target: 50.0). Not enough fixtures met your quality criteria (confidence >= 70%, EV >= 10%).",
            "error": None,
        }

        orchestrator.batch_orchestrator.process_batch_request = AsyncMock(
            return_value=mock_result
        )

        response = await orchestrator.handle_user_message(user_id, message)

        # Verify warning appears in message
        assert "⚠️" in response["message"]
        assert "15.5 odds" in response["message"]
        assert response["data"]["warning"] is not None

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_handle_user_message_batch_prediction_error(self, orchestrator):
        """Test batch prediction with error (no fixtures found)."""
        # Include market (BTTS) to pass market validation
        message = "Give me 20 BTTS odds in NonExistentLeague"
        user_id = "test_user_error"

        # Mock error result
        mock_result = {
            "accumulated_odds": 0.0,
            "target_odds": 20.0,
            "selections": [],
            "filters_applied": {
                "leagues": ["NonExistentLeague"],
            },
            "warning": None,
            "error": "No fixtures found matching your criteria",
        }

        orchestrator.batch_orchestrator.process_batch_request = AsyncMock(
            return_value=mock_result
        )

        response = await orchestrator.handle_user_message(user_id, message)

        # Verify error response
        assert response["error"] is not None
        assert "No fixtures found" in response["message"]
        assert "❌" in response["message"]

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_handle_user_message_batch_prediction_exception(self, orchestrator):
        """Test batch prediction with unexpected exception."""
        message = "I need 20 odds"
        user_id = "test_user_exception"

        # Mock exception
        orchestrator.batch_orchestrator.process_batch_request = AsyncMock(
            side_effect=Exception("Database connection failed")
        )

        response = await orchestrator.handle_user_message(user_id, message)

        # Verify exception handling
        assert response["error"] is not None
        assert "unexpected error" in response["message"].lower()
        assert "Database connection failed" in response["message"]
