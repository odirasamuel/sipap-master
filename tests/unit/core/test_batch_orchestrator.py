"""Unit tests for BatchOrchestrator.

Tests the batch prediction pipeline with accumulated odds logic.

Following TDD methodology - these tests are written BEFORE implementation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sipap.core.batch_orchestrator import BatchOrchestrator
from sipap.conversation import RequestIntent


class TestBatchOrchestratorInit:
    """Test BatchOrchestrator initialization."""

    def test_initialization(self):
        """Test that BatchOrchestrator initializes correctly."""
        main_orch = MagicMock()
        mcp_factory = MagicMock()
        logger = MagicMock()

        orchestrator = BatchOrchestrator(
            main_orchestrator=main_orch,
            mcp_factory=mcp_factory,
            logger=logger,
        )

        assert orchestrator.orchestrator == main_orch
        assert orchestrator.mcp_factory == mcp_factory
        assert orchestrator.logger == logger
        assert "highest" in orchestrator.quality_thresholds
        assert "high" in orchestrator.quality_thresholds
        assert "medium" in orchestrator.quality_thresholds

    def test_quality_thresholds_mapping(self):
        """Test that quality thresholds are correctly defined."""
        orchestrator = BatchOrchestrator(
            main_orchestrator=MagicMock(),
            mcp_factory=MagicMock(),
            logger=MagicMock(),
        )

        # Highest: >70% confidence, >10% EV
        assert orchestrator.quality_thresholds["highest"]["min_confidence"] == 0.70
        assert orchestrator.quality_thresholds["highest"]["min_ev"] == 0.10

        # High: >60% confidence, >5% EV
        assert orchestrator.quality_thresholds["high"]["min_confidence"] == 0.60
        assert orchestrator.quality_thresholds["high"]["min_ev"] == 0.05

        # Medium: >55% confidence, >0% EV
        assert orchestrator.quality_thresholds["medium"]["min_confidence"] == 0.55
        assert orchestrator.quality_thresholds["medium"]["min_ev"] == 0.00


class TestBatchOrchestratorAccumulation:
    """Test accumulated odds algorithm."""

    @pytest.fixture
    def orchestrator(self):
        """Create BatchOrchestrator instance for testing."""
        return BatchOrchestrator(
            main_orchestrator=MagicMock(),
            mcp_factory=MagicMock(),
            logger=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_process_batch_request_basic(self, orchestrator):
        """Test basic batch prediction request with target_odds=20."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=20.0,
            accumulation_mode=True,
            quality_threshold="high",
            original_query="I need 20 odds",
            extracted_entities={},
        )

        # Mock get_filtered_matches to return fixtures
        orchestrator._get_filtered_matches = AsyncMock(
            return_value=[
                {"id": "match1", "home_team": "Arsenal", "away_team": "Chelsea"},
                {"id": "match2", "home_team": "Barcelona", "away_team": "Madrid"},
                {"id": "match3", "home_team": "Bayern", "away_team": "Dortmund"},
            ]
        )

        # Mock predict_fixture to return analysis with bookmaker odds
        orchestrator._predict_fixture = AsyncMock(
            side_effect=[
                {
                    "fixture": {"id": "match1"},
                    "market_code": "1X2",
                    "market_name": "Match Result",
                    "best_outcome": "Home Win",
                    "bookmaker_odd": 2.5,
                    "confidence": 0.75,
                    "ev": 0.08,
                    "markets_evaluated": 44,
                },
                {
                    "fixture": {"id": "match2"},
                    "market_code": "BTTS",
                    "market_name": "Both Teams To Score",
                    "best_outcome": "Yes",
                    "bookmaker_odd": 3.0,
                    "confidence": 0.72,
                    "ev": 0.10,
                    "markets_evaluated": 44,
                },
                {
                    "fixture": {"id": "match3"},
                    "market_code": "OU2.5",
                    "market_name": "Total Goals Over/Under 2.5",
                    "best_outcome": "Over 2.5",
                    "bookmaker_odd": 14.5,
                    "confidence": 0.70,
                    "ev": 0.12,
                    "markets_evaluated": 44,
                },
            ]
        )

        result = await orchestrator.process_batch_request(intent, user_id="test_user")

        # Should accumulate until >= 20.0
        assert result["accumulated_odds"] >= 20.0
        assert result["target_odds"] == 20.0
        assert len(result["selections"]) == 3  # All 3 fixtures needed
        assert result["selections"][0]["bookmaker_odd"] == 2.5
        assert result["selections"][1]["bookmaker_odd"] == 3.0
        assert result["selections"][2]["bookmaker_odd"] == 14.5
        # Sum: 2.5 + 3.0 + 14.5 = 20.0

    @pytest.mark.asyncio
    async def test_process_batch_request_stops_at_target(self, orchestrator):
        """Test that accumulation stops when target is reached."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=10.0,
            accumulation_mode=True,
            quality_threshold="high",
            original_query="I need 10 odds",
            extracted_entities={},
        )

        # Mock 5 fixtures, but should only need 2-3 to reach 10.0
        orchestrator._get_filtered_matches = AsyncMock(
            return_value=[
                {"id": f"match{i}"} for i in range(5)
            ]
        )

        # Mock predictions with odds that sum > 10 after 3 fixtures
        orchestrator._predict_fixture = AsyncMock(
            side_effect=[
                {"fixture": {"id": "match0"}, "market_code": "1X2", "market_name": "Match Result", "best_outcome": "Home Win", "bookmaker_odd": 2.5, "confidence": 0.75, "ev": 0.08, "markets_evaluated": 44},
                {"fixture": {"id": "match1"}, "market_code": "BTTS", "market_name": "Both Teams To Score", "best_outcome": "Yes", "bookmaker_odd": 3.0, "confidence": 0.72, "ev": 0.10, "markets_evaluated": 44},
                {"fixture": {"id": "match2"}, "market_code": "OU2.5", "market_name": "Total Goals Over/Under 2.5", "best_outcome": "Over 2.5", "bookmaker_odd": 5.0, "confidence": 0.70, "ev": 0.12, "markets_evaluated": 44},
                # Should not reach these:
                {"fixture": {"id": "match3"}, "market_code": "1X2", "market_name": "Match Result", "best_outcome": "Draw", "bookmaker_odd": 2.0, "confidence": 0.68, "ev": 0.05, "markets_evaluated": 44},
                {"fixture": {"id": "match4"}, "market_code": "OU2.5", "market_name": "Total Goals Over/Under 2.5", "best_outcome": "Under 2.5", "bookmaker_odd": 1.8, "confidence": 0.65, "ev": 0.03, "markets_evaluated": 44},
            ]
        )

        result = await orchestrator.process_batch_request(intent, user_id="test_user")

        # Should stop at 3 fixtures (2.5 + 3.0 + 5.0 = 10.5 >= 10.0)
        assert result["accumulated_odds"] >= 10.0
        assert len(result["selections"]) == 3
        assert result["accumulated_odds"] == 10.5

    @pytest.mark.asyncio
    async def test_process_batch_request_quality_filtering(self, orchestrator):
        """Test that quality threshold filters out low-confidence predictions."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=20.0,
            accumulation_mode=True,
            quality_threshold="highest",  # >70% confidence, >10% EV
            original_query="I need 20 sure odds",
            extracted_entities={},
        )

        orchestrator._get_filtered_matches = AsyncMock(
            return_value=[{"id": f"match{i}"} for i in range(10)]
        )

        # Mix of high and low quality predictions
        orchestrator._predict_fixture = AsyncMock(
            side_effect=[
                # Pass quality (conf=0.75, ev=0.12)
                {"fixture": {"id": "match0"}, "market_code": "1X2", "market_name": "Match Result", "best_outcome": "Home Win", "bookmaker_odd": 2.5, "confidence": 0.75, "ev": 0.12, "markets_evaluated": 44},
                # Fail (conf=0.65 < 0.70)
                {"fixture": {"id": "match1"}, "market_code": "BTTS", "market_name": "Both Teams To Score", "best_outcome": "Yes", "bookmaker_odd": 3.0, "confidence": 0.65, "ev": 0.15, "markets_evaluated": 44},
                # Pass (conf=0.72, ev=0.11)
                {"fixture": {"id": "match2"}, "market_code": "OU2.5", "market_name": "Total Goals Over/Under 2.5", "best_outcome": "Over 2.5", "bookmaker_odd": 5.0, "confidence": 0.72, "ev": 0.11, "markets_evaluated": 44},
                # Fail (ev=0.08 < 0.10)
                {"fixture": {"id": "match3"}, "market_code": "1X2", "market_name": "Match Result", "best_outcome": "Draw", "bookmaker_odd": 2.0, "confidence": 0.75, "ev": 0.08, "markets_evaluated": 44},
                # Pass (conf=0.71, ev=0.10)
                {"fixture": {"id": "match4"}, "market_code": "OU2.5", "market_name": "Total Goals Over/Under 2.5", "best_outcome": "Under 2.5", "bookmaker_odd": 12.5, "confidence": 0.71, "ev": 0.10, "markets_evaluated": 44},
            ]
        )

        result = await orchestrator.process_batch_request(intent, user_id="test_user")

        # Should only include fixtures that passed quality gates
        # match0 (2.5) + match2 (5.0) + match4 (12.5) = 20.0
        assert result["accumulated_odds"] == 20.0
        assert len(result["selections"]) == 3
        assert all(s["confidence"] >= 0.70 for s in result["selections"])
        assert all(s["ev"] >= 0.10 for s in result["selections"])

    @pytest.mark.asyncio
    async def test_process_batch_request_fewer_than_target(self, orchestrator):
        """Test handling when not enough fixtures meet quality threshold."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=50.0,
            accumulation_mode=True,
            quality_threshold="highest",
            original_query="I need 50 sure odds",
            extracted_entities={},
        )

        # Only 2 fixtures available
        orchestrator._get_filtered_matches = AsyncMock(
            return_value=[
                {"id": "match1"},
                {"id": "match2"},
            ]
        )

        orchestrator._predict_fixture = AsyncMock(
            side_effect=[
                {"fixture": {"id": "match1"}, "market_code": "1X2", "market_name": "Match Result", "best_outcome": "Home Win", "bookmaker_odd": 2.5, "confidence": 0.75, "ev": 0.12, "markets_evaluated": 44},
                {"fixture": {"id": "match2"}, "market_code": "BTTS", "market_name": "Both Teams To Score", "best_outcome": "Yes", "bookmaker_odd": 3.0, "confidence": 0.72, "ev": 0.10, "markets_evaluated": 44},
            ]
        )

        result = await orchestrator.process_batch_request(intent, user_id="test_user")

        # Should return what's available (5.5 < 50.0)
        assert result["accumulated_odds"] == 5.5
        assert result["accumulated_odds"] < result["target_odds"]
        assert len(result["selections"]) == 2
        assert result.get("warning") is not None  # Should warn user

    @pytest.mark.asyncio
    async def test_process_batch_request_with_league_filter(self, orchestrator):
        """Test batch request with league filtering."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=20.0,
            accumulation_mode=True,
            leagues=["Premier League", "LaLiga"],
            quality_threshold="high",
            original_query="20 odds in Premier League and LaLiga",
            extracted_entities={},
        )

        orchestrator._get_filtered_matches = AsyncMock(return_value=[])
        orchestrator._predict_fixture = AsyncMock()

        await orchestrator.process_batch_request(intent, user_id="test_user")

        # Verify _get_filtered_matches was called with correct league filter
        orchestrator._get_filtered_matches.assert_called_once()
        call_kwargs = orchestrator._get_filtered_matches.call_args[1]
        assert call_kwargs["leagues"] == ["Premier League", "LaLiga"]

    @pytest.mark.asyncio
    async def test_process_batch_request_with_date_filter(self, orchestrator):
        """Test batch request with date range filtering."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=20.0,
            accumulation_mode=True,
            date_range={"start": "2026-08-03", "end": "2026-08-10"},
            quality_threshold="high",
            original_query="20 odds between 3rd-10th August",
            extracted_entities={},
        )

        orchestrator._get_filtered_matches = AsyncMock(return_value=[])
        orchestrator._predict_fixture = AsyncMock()

        await orchestrator.process_batch_request(intent, user_id="test_user")

        # Verify _get_filtered_matches was called with correct date filter
        orchestrator._get_filtered_matches.assert_called_once()
        call_kwargs = orchestrator._get_filtered_matches.call_args[1]
        assert call_kwargs["date_range"] == {"start": "2026-08-03", "end": "2026-08-10"}


class TestBatchOrchestratorMarketSelection:
    """Test multi-market evaluation in batch predictions.

    CRITICAL: System evaluates ALL markets per fixture and selects best one.
    Users do NOT specify markets - they only express intent and quality.
    """

    @pytest.fixture
    def orchestrator(self):
        """Create BatchOrchestrator instance for testing."""
        return BatchOrchestrator(
            main_orchestrator=MagicMock(),
            mcp_factory=MagicMock(),
            logger=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_predict_fixture_evaluates_all_markets(self, orchestrator):
        """Test that _predict_fixture evaluates ALL markets and selects best EV."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=10.0,
            accumulation_mode=True,
            markets=None,  # Users don't specify markets
            quality_threshold="high",
            original_query="10 odds with best outcomes",
            extracted_entities={},
        )

        orchestrator._get_filtered_matches = AsyncMock(
            return_value=[{"id": "match1", "home_team": "Arsenal", "away_team": "Chelsea"}]
        )

        # Mock _predict_fixture to return multi-market evaluation result
        orchestrator._predict_fixture = AsyncMock(
            return_value={
                "fixture": {"id": "match1"},
                "market_code": "BTTS",  # System selected BTTS
                "market_name": "Both Teams To Score",
                "best_outcome": "Yes",
                "bookmaker_odd": 10.5,
                "confidence": 0.75,
                "ev": 0.12,  # BTTS had highest EV
                "markets_evaluated": 44,  # All 44 markets evaluated
            }
        )

        result = await orchestrator.process_batch_request(intent, user_id="test_user")

        # Verify market selection is in response
        assert len(result["selections"]) == 1
        selection = result["selections"][0]
        assert "market_code" in selection
        assert "market_name" in selection
        assert selection["market_code"] == "BTTS"
        assert selection["market_name"] == "Both Teams To Score"
        assert selection["markets_evaluated"] == 44

    @pytest.mark.asyncio
    async def test_system_selects_market_with_highest_ev(self, orchestrator):
        """Test that system selects market with highest EV, not user preference."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=20.0,
            accumulation_mode=True,
            markets=None,  # No user market preference
            quality_threshold="high",
            original_query="20 odds with highest positive outcome",
            extracted_entities={},
        )

        orchestrator._get_filtered_matches = AsyncMock(
            return_value=[
                {"id": "match1"},
                {"id": "match2"},
            ]
        )

        # Mock: match1 best market is BTTS (EV=+0.15)
        #       match2 best market is OU2.5 (EV=+0.20)
        orchestrator._predict_fixture = AsyncMock(
            side_effect=[
                {
                    "fixture": {"id": "match1"},
                    "market_code": "BTTS",
                    "market_name": "Both Teams To Score",
                    "best_outcome": "Yes",
                    "bookmaker_odd": 2.5,
                    "confidence": 0.75,
                    "ev": 0.15,
                    "markets_evaluated": 44,
                },
                {
                    "fixture": {"id": "match2"},
                    "market_code": "OU2.5",
                    "market_name": "Total Goals Over/Under 2.5",
                    "best_outcome": "Over 2.5",
                    "bookmaker_odd": 18.0,
                    "confidence": 0.72,
                    "ev": 0.20,
                    "markets_evaluated": 44,
                },
            ]
        )

        result = await orchestrator.process_batch_request(intent, user_id="test_user")

        # Verify different markets selected for different fixtures
        assert len(result["selections"]) == 2
        assert result["selections"][0]["market_code"] == "BTTS"
        assert result["selections"][1]["market_code"] == "OU2.5"

    @pytest.mark.asyncio
    async def test_market_explanation_included_in_response(self, orchestrator):
        """Test that market code and name are included for user understanding."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=10.0,
            accumulation_mode=True,
            quality_threshold="high",
            original_query="10 odds",
            extracted_entities={},
        )

        orchestrator._get_filtered_matches = AsyncMock(
            return_value=[{"id": "match1"}]
        )

        orchestrator._predict_fixture = AsyncMock(
            return_value={
                "fixture": {"id": "match1"},
                "market_code": "1X2",
                "market_name": "Match Result",
                "best_outcome": "Home Win",
                "bookmaker_odd": 10.5,
                "confidence": 0.75,
                "ev": 0.08,
                "markets_evaluated": 44,
            }
        )

        result = await orchestrator.process_batch_request(intent, user_id="test_user")

        # Verify market explanation fields exist
        selection = result["selections"][0]
        assert "market_code" in selection, "Market code required for system tracking"
        assert "market_name" in selection, "Market name required for user understanding"
        assert isinstance(selection["market_name"], str)
        assert len(selection["market_name"]) > 0

    @pytest.mark.asyncio
    async def test_no_market_parameter_passed_to_predict_fixture(self, orchestrator):
        """Test that _predict_fixture is called WITHOUT market parameter.

        This verifies the paradigm shift: system evaluates ALL markets internally,
        not a single user-specified market.
        """
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=10.0,
            accumulation_mode=True,
            markets=None,
            quality_threshold="high",
            original_query="10 odds",
            extracted_entities={},
        )

        orchestrator._get_filtered_matches = AsyncMock(
            return_value=[{"id": "match1"}]
        )

        orchestrator._predict_fixture = AsyncMock(
            return_value={
                "fixture": {"id": "match1"},
                "market_code": "1X2",
                "market_name": "Match Result",
                "best_outcome": "Home Win",
                "bookmaker_odd": 10.5,
                "confidence": 0.75,
                "ev": 0.08,
                "markets_evaluated": 44,
            }
        )

        await orchestrator.process_batch_request(intent, user_id="test_user")

        # Verify _predict_fixture called without market parameter
        call_args = orchestrator._predict_fixture.call_args
        _, kwargs = call_args
        assert "market" not in kwargs, "Market parameter should NOT be passed (evaluates all internally)"


class TestBatchOrchestratorErrorHandling:
    """Test error handling in BatchOrchestrator."""

    @pytest.fixture
    def orchestrator(self):
        """Create BatchOrchestrator instance for testing."""
        return BatchOrchestrator(
            main_orchestrator=MagicMock(),
            mcp_factory=MagicMock(),
            logger=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_handle_no_fixtures_found(self, orchestrator):
        """Test handling when no fixtures match filters."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=20.0,
            accumulation_mode=True,
            leagues=["NonExistentLeague"],
            quality_threshold="high",
            original_query="20 odds in fake league",
            extracted_entities={},
        )

        orchestrator._get_filtered_matches = AsyncMock(return_value=[])

        result = await orchestrator.process_batch_request(intent, user_id="test_user")

        assert result["error"] is not None
        assert "No fixtures found" in result["error"]
        assert result["accumulated_odds"] == 0.0
        assert len(result["selections"]) == 0

    @pytest.mark.asyncio
    async def test_handle_prediction_failure(self, orchestrator):
        """Test handling when prediction fails for a fixture."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=10.0,
            accumulation_mode=True,
            quality_threshold="high",
            original_query="10 odds",
            extracted_entities={},
        )

        orchestrator._get_filtered_matches = AsyncMock(
            return_value=[{"id": "match1"}, {"id": "match2"}]
        )

        # First prediction succeeds, second fails
        orchestrator._predict_fixture = AsyncMock(
            side_effect=[
                {"fixture": {"id": "match1"}, "market_code": "1X2", "market_name": "Match Result", "best_outcome": "Home Win", "bookmaker_odd": 2.5, "confidence": 0.75, "ev": 0.08, "markets_evaluated": 44},
                Exception("Prediction failed"),
            ]
        )

        result = await orchestrator.process_batch_request(intent, user_id="test_user")

        # Should continue with successful predictions
        assert len(result["selections"]) == 1
        assert result["accumulated_odds"] == 2.5
        # Should have warning about failed predictions
        assert "failures" in result or result.get("warning") is not None
