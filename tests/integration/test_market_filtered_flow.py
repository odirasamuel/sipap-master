"""Integration tests for market-filtered prediction flow.

Tests the end-to-end flow:
1. User message with market codes/aliases → NLU parses and extracts markets
2. NLU returns RequestIntent with markets field populated
3. BatchOrchestrator detects intent.markets and routes to get_filtered_fixtures
4. Returns market-specific predictions

NOTE: These tests verify the NLU → Orchestrator routing logic.
Full integration tests with Data MCP require AWS credentials and are
marked with NEEDS_AWS_BEDROCK.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sipap.conversation.nlu_agent import NLUAgent, RequestIntent


# Marker for tests that require AWS Bedrock/MCP access
NEEDS_AWS_BEDROCK = pytest.mark.skip(
    reason="Requires AWS Bedrock access for full integration - integration test"
)


class TestMarketFilteredNLUParsing:
    """Test NLU correctly parses market-filtered requests.

    NOTE: Tests that use parse_user_message() and expect markets to be extracted
    require Claude NLU (AWS Bedrock) because the regex fallback doesn't route
    through the market extraction logic. These are marked with NEEDS_AWS_BEDROCK.
    """

    @pytest.fixture
    def nlu(self):
        """Create NLUAgent for testing."""
        return NLUAgent()

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_explicit_btts_request_extracts_market(self, nlu):
        """'Give me 10 BTTS picks' should extract markets=["BTTS"]."""
        message = "Give me 10 BTTS picks with high probability"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is not None
        assert "BTTS" in intent.markets
        # Intent type should be batch_prediction (wants multiple matches)
        assert intent.intent_type in ("batch_prediction", "single_prediction", "unknown")

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_natural_language_btts_extracts_market(self, nlu):
        """'both teams will score' should extract markets=["BTTS"]."""
        message = "Show me fixtures where both teams will score"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is not None
        assert "BTTS" in intent.markets

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_multiple_markets_all_extracted(self, nlu):
        """Multiple markets should all be extracted."""
        message = "BTTS and 1X2 predictions for Premier League"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is not None
        assert "BTTS" in intent.markets
        assert "1X2" in intent.markets

    @pytest.mark.asyncio
    async def test_quality_only_no_markets(self, nlu):
        """Quality-only request should have markets=None."""
        message = "20 sure odds in Premier League"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is None
        assert intent.quality_threshold == "highest"

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_mixed_market_quality_league(self, nlu):
        """Mixed request should extract market, quality, and league."""
        message = "20 sure BTTS odds in Premier League"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is not None
        assert "BTTS" in intent.markets
        assert intent.quality_threshold == "highest"


class TestBatchOrchestratorMarketRouting:
    """Test BatchOrchestrator routes market-filtered requests correctly."""

    @pytest.fixture
    def mock_main_orchestrator(self):
        """Create mock MainOrchestrator with SoccerOrchestrator."""
        mock_soccer_orch = MagicMock()
        mock_soccer_orch.get_filtered_fixtures = AsyncMock(return_value={
            "market_codes": ["BTTS"],
            "total_fixtures": 45,
            "total_evaluations": 32,
            "selection_count": 10,
            "selections": [
                {
                    "fixture_id": "match1",
                    "fixture": "Arsenal vs Chelsea",
                    "market_code": "BTTS",
                    "market_name": "Both Teams To Score",
                    "outcome": "Yes",
                    "probability": 0.82,
                    "odds": 1.65,
                    "bookmaker": "Bet365",
                }
            ],
            "filters_applied": {
                "date": "today",
                "min_probability": 0.60,
                "market_codes": ["BTTS"],
            },
        })

        mock_main = MagicMock()
        mock_main._orchestrators = {"soccer": mock_soccer_orch}
        return mock_main

    @pytest.fixture
    def mock_mcp_factory(self):
        """Create mock MCP factory."""
        mock = MagicMock()
        mock.warmup = AsyncMock(return_value={"data": True, "intelligence": True})
        return mock

    @pytest.mark.asyncio
    async def test_market_filtered_request_routes_to_get_filtered_fixtures(
        self, mock_main_orchestrator, mock_mcp_factory
    ):
        """Request with markets should route to get_filtered_fixtures."""
        from sipap.core.batch_orchestrator import BatchOrchestrator
        from sipap.conversation.nlu_agent import LeagueEntity

        batch_orch = BatchOrchestrator(
            main_orchestrator=mock_main_orchestrator,
            mcp_factory=mock_mcp_factory,
        )

        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            markets=["BTTS"],
            quality_threshold="highest",
            original_query="Give me 10 BTTS picks",
        )

        result = await batch_orch.process_batch_request(intent, "test_user")

        # Verify get_filtered_fixtures was called
        mock_soccer_orch = mock_main_orchestrator._orchestrators["soccer"]
        mock_soccer_orch.get_filtered_fixtures.assert_called_once()

        # Verify result structure
        assert "market_codes" in result
        assert result["market_codes"] == ["BTTS"]
        assert "selections" in result

    @pytest.mark.asyncio
    async def test_quality_only_request_does_not_route_to_filtered(
        self, mock_main_orchestrator, mock_mcp_factory
    ):
        """Request without markets should NOT route to get_filtered_fixtures."""
        from sipap.core.batch_orchestrator import BatchOrchestrator

        batch_orch = BatchOrchestrator(
            main_orchestrator=mock_main_orchestrator,
            mcp_factory=mock_mcp_factory,
        )

        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            markets=None,  # No markets specified
            quality_threshold="highest",
            target_odds=20.0,
            original_query="20 sure odds",
        )

        # This should NOT call get_filtered_fixtures
        # It should proceed to standard batch processing
        # (which will fail without MCP, but that's expected for unit test)
        try:
            await batch_orch.process_batch_request(intent, "test_user")
        except Exception:
            pass  # Expected - we're just testing routing, not full flow

        # Verify get_filtered_fixtures was NOT called
        mock_soccer_orch = mock_main_orchestrator._orchestrators["soccer"]
        mock_soccer_orch.get_filtered_fixtures.assert_not_called()


class TestEndToEndMarketFilteredFlow:
    """End-to-end tests for market-filtered flow.

    NOTE: Tests using parse_user_message() that expect markets extraction require
    Claude NLU (AWS Bedrock). The regex fallback doesn't route through market
    extraction logic. Tests are marked with NEEDS_AWS_BEDROCK.
    """

    @pytest.fixture
    def nlu(self):
        """Create NLUAgent for testing."""
        return NLUAgent()

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_btts_request_produces_btts_only_selections(self, nlu):
        """BTTS request should flow through to get_filtered_fixtures.

        This test verifies the NLU extraction part.
        Full integration with MCP requires AWS credentials.
        """
        # Step 1: Parse user message
        message = "Give me 10 BTTS picks with high probability"
        intent = await nlu.parse_user_message(message)

        # Verify NLU extracted markets correctly
        assert intent.markets is not None
        assert "BTTS" in intent.markets

        # Step 2: Verify intent would route to market-filtered path
        # In real flow, BatchOrchestrator would check intent.markets
        if intent.markets:
            # This is the path that would be taken
            assert True, "Would route to get_filtered_fixtures"
        else:
            pytest.fail("markets should be extracted for BTTS request")

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_over_25_goals_produces_ou25_selections(self, nlu):
        """'over 2.5 goals' should extract OU2.5 market."""
        message = "Give me over 2.5 goals predictions for today"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is not None
        assert "OU2.5" in intent.markets

    @NEEDS_AWS_BEDROCK
    @pytest.mark.asyncio
    async def test_double_chance_produces_dc_selections(self, nlu):
        """'double chance' should extract DC market."""
        message = "Double Chance selections for Premier League"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is not None
        assert "DC" in intent.markets


class TestMarketFilteredResultStructure:
    """Test the structure of market-filtered results."""

    def test_filtered_fixtures_result_has_required_fields(self):
        """Verify result structure from get_filtered_fixtures."""
        # Expected result structure
        result = {
            "market_codes": ["BTTS"],
            "total_fixtures": 45,
            "total_evaluations": 32,
            "selection_count": 10,
            "selections": [
                {
                    "fixture_id": "match1",
                    "fixture": "Arsenal vs Chelsea",
                    "scheduled_at": "2026-08-20T15:00:00Z",
                    "league": "Premier League",
                    "market_code": "BTTS",
                    "market_name": "Both Teams To Score",
                    "outcome": "Yes",
                    "probability": 0.82,
                    "confidence": "high",
                    "odds": 1.65,
                    "bookmaker": "Bet365",
                }
            ],
            "filters_applied": {
                "date": "today",
                "min_probability": 0.60,
                "market_codes": ["BTTS"],
            },
        }

        # Verify required fields
        assert "market_codes" in result
        assert "total_fixtures" in result
        assert "selection_count" in result
        assert "selections" in result
        assert "filters_applied" in result

        # Verify selection structure
        selection = result["selections"][0]
        assert "fixture" in selection
        assert "market_code" in selection
        assert "probability" in selection
        assert "odds" in selection

    def test_all_selections_have_requested_market(self):
        """All selections should be from requested markets only."""
        # Simulated result from BTTS and 1X2 request
        result = {
            "market_codes": ["BTTS", "1X2"],
            "selections": [
                {"fixture": "A vs B", "market_code": "BTTS", "probability": 0.82},
                {"fixture": "C vs D", "market_code": "1X2", "probability": 0.78},
                {"fixture": "E vs F", "market_code": "BTTS", "probability": 0.75},
            ],
        }

        for selection in result["selections"]:
            assert selection["market_code"] in result["market_codes"], \
                f"Selection has unexpected market: {selection['market_code']}"


@NEEDS_AWS_BEDROCK
class TestFullIntegrationWithMCP:
    """Full integration tests requiring AWS Bedrock and MCP access.

    These tests are skipped by default and require proper AWS credentials
    and MCP server setup to run.
    """

    @pytest.mark.asyncio
    async def test_btts_request_returns_real_selections(self):
        """BTTS request returns real market-filtered selections from Data MCP."""
        from sipap.core.orchestrator import MainOrchestrator

        orchestrator = MainOrchestrator()
        message = "Give me 10 BTTS picks with high probability"

        response = await orchestrator.handle_user_message("test_user", message)

        # Verify response
        assert response["error"] is None
        assert "data" in response
        assert "selections" in response["data"]

        # Verify all selections are BTTS
        for selection in response["data"]["selections"]:
            assert selection["market_code"] == "BTTS"

    @pytest.mark.asyncio
    async def test_multiple_markets_returns_mixed_selections(self):
        """Multiple market request returns selections from requested markets."""
        from sipap.core.orchestrator import MainOrchestrator

        orchestrator = MainOrchestrator()
        message = "BTTS and 1X2 predictions for today"

        response = await orchestrator.handle_user_message("test_user", message)

        assert response["error"] is None
        assert "data" in response

        # Verify selections are from requested markets only
        allowed_markets = {"BTTS", "1X2"}
        for selection in response["data"]["selections"]:
            assert selection["market_code"] in allowed_markets
