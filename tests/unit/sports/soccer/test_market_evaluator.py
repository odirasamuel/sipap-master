"""Unit tests for MarketEvaluator market code filtering.

Tests the _validate_market_codes() method and market filtering functionality.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from sipap.sports.soccer.market_evaluator import MarketEvaluator


class TestValidateMarketCodes:
    """Test _validate_market_codes() method."""

    @pytest.fixture
    def evaluator(self):
        """Create MarketEvaluator with mock MCP client."""
        mock_mcp = MagicMock()
        return MarketEvaluator(mock_mcp)

    def test_validate_none_returns_none(self, evaluator):
        """None input should return None (evaluate all markets)."""
        result = evaluator._validate_market_codes(None)
        assert result is None

    def test_validate_empty_list_returns_none(self, evaluator):
        """Empty list should return None (evaluate all markets)."""
        result = evaluator._validate_market_codes([])
        assert result is None

    def test_validate_single_valid_code(self, evaluator):
        """Single valid code should be returned."""
        result = evaluator._validate_market_codes(["BTTS"])
        assert result == ["BTTS"]

    def test_validate_multiple_valid_codes(self, evaluator):
        """Multiple valid codes should all be returned."""
        result = evaluator._validate_market_codes(["BTTS", "1X2", "DC"])
        assert result is not None
        assert "BTTS" in result
        assert "1X2" in result
        assert "DC" in result
        assert len(result) == 3

    def test_validate_case_insensitive(self, evaluator):
        """Codes should be normalized to uppercase."""
        result = evaluator._validate_market_codes(["btts", "Dc", "dnb"])
        assert result is not None
        assert "BTTS" in result
        assert "DC" in result
        assert "DNB" in result

    def test_validate_mixed_case(self, evaluator):
        """Mixed case codes should work."""
        result = evaluator._validate_market_codes(["BtTs", "oU2.5"])
        assert result is not None
        assert "BTTS" in result
        assert "OU2.5" in result

    def test_validate_deduplicates(self, evaluator):
        """Duplicate codes should be deduplicated."""
        result = evaluator._validate_market_codes(["BTTS", "btts", "BTTS", "Btts"])
        assert result is not None
        assert result == ["BTTS"]

    def test_validate_deduplicates_preserves_order(self, evaluator):
        """Deduplication should preserve first occurrence order."""
        result = evaluator._validate_market_codes(["1X2", "btts", "1x2", "DC", "dc"])
        assert result is not None
        assert result == ["1X2", "BTTS", "DC"]

    def test_validate_invalid_code_raises(self, evaluator):
        """Invalid code should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            evaluator._validate_market_codes(["INVALID_CODE"])

        assert "Invalid market codes" in str(exc_info.value)
        assert "INVALID_CODE" in str(exc_info.value)

    def test_validate_mixed_valid_invalid_raises(self, evaluator):
        """Mix of valid and invalid codes should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            evaluator._validate_market_codes(["BTTS", "INVALID1", "1X2", "INVALID2"])

        error_msg = str(exc_info.value)
        assert "Invalid market codes" in error_msg
        assert "INVALID1" in error_msg
        assert "INVALID2" in error_msg

    def test_validate_strips_whitespace(self, evaluator):
        """Whitespace should be stripped from codes."""
        result = evaluator._validate_market_codes(["  BTTS  ", " 1X2 "])
        assert result is not None
        assert "BTTS" in result
        assert "1X2" in result

    def test_validate_all_main_markets(self, evaluator):
        """All main market codes should be valid."""
        main_codes = ["1X2", "DNB", "BTTS", "DC", "OU0.5", "OU1.5", "OU2.5", "OU3.5", "OU4.5"]
        result = evaluator._validate_market_codes(main_codes)
        assert result is not None
        assert len(result) == len(main_codes)

    def test_validate_halftime_markets(self, evaluator):
        """Halftime market codes should be valid."""
        ht_codes = ["HT_1X2", "HT_DC", "HT_OU0.5", "HT_OU1.5", "HT_OU2.5"]
        result = evaluator._validate_market_codes(ht_codes)
        assert result is not None
        assert len(result) == len(ht_codes)

    def test_validate_2nd_half_markets(self, evaluator):
        """2nd half market codes should be valid."""
        h2_codes = ["2H_DC", "2H_OU0.5", "2H_OU1.5", "2H_OU2.5"]
        result = evaluator._validate_market_codes(h2_codes)
        assert result is not None
        assert len(result) == len(h2_codes)

    def test_validate_combination_markets(self, evaluator):
        """Combination market codes should be valid."""
        combo_codes = ["1X2_OU2.5", "DC_BTTS", "BTTS_OU2.5"]
        result = evaluator._validate_market_codes(combo_codes)
        assert result is not None
        assert len(result) == len(combo_codes)

    def test_validate_chance_mix_markets(self, evaluator):
        """Chance mix market codes should be valid."""
        chance_codes = ["CHANCEMIX_1X2_OU25", "CHANCEMIX_BTTS_OU25"]
        result = evaluator._validate_market_codes(chance_codes)
        assert result is not None
        assert len(result) == len(chance_codes)

    def test_validate_error_message_includes_valid_examples(self, evaluator):
        """Error message should include examples of valid codes."""
        with pytest.raises(ValueError) as exc_info:
            evaluator._validate_market_codes(["NOTREAL"])

        error_msg = str(exc_info.value)
        assert "Valid codes include:" in error_msg


class TestEvaluateAllMarketsFiltering:
    """Test evaluate_all_markets() with market_codes filter.

    These tests focus on the filtering behavior - actual evaluation
    results are tested in integration tests.
    """

    @pytest.fixture
    def mock_evaluator(self):
        """Create MarketEvaluator with mocked dependencies."""
        mock_mcp = MagicMock()
        evaluator = MarketEvaluator(mock_mcp)

        # Mock _fetch_all_tool_data to return empty dict
        evaluator._fetch_all_tool_data = AsyncMock(return_value={})

        # Mock evaluation methods to avoid complex setup
        evaluator._evaluate_main_markets = MagicMock(return_value=[])
        evaluator._evaluate_halftime_markets = MagicMock(return_value=[])
        evaluator._evaluate_2nd_half_markets = MagicMock(return_value=[])
        evaluator._evaluate_team_specific_markets = MagicMock(return_value=[])
        evaluator._evaluate_htft_market = MagicMock(return_value=[])
        evaluator._evaluate_combination_and_markets = AsyncMock(return_value=[])
        evaluator._evaluate_chance_mix_markets = AsyncMock(return_value=[])
        evaluator._evaluate_advanced_markets = MagicMock(return_value=[])

        return evaluator

    @pytest.mark.asyncio
    async def test_market_codes_none_evaluates_all(self, mock_evaluator):
        """market_codes=None should evaluate all markets."""
        await mock_evaluator.evaluate_all_markets(
            home_team_id=1,
            away_team_id=2,
            league_id=39,
            market_codes=None,
        )

        # All evaluation methods should be called
        mock_evaluator._evaluate_main_markets.assert_called_once()
        mock_evaluator._evaluate_halftime_markets.assert_called_once()
        mock_evaluator._evaluate_2nd_half_markets.assert_called_once()
        mock_evaluator._evaluate_team_specific_markets.assert_called_once()
        mock_evaluator._evaluate_htft_market.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_codes_empty_evaluates_all(self, mock_evaluator):
        """market_codes=[] should evaluate all markets (same as None)."""
        await mock_evaluator.evaluate_all_markets(
            home_team_id=1,
            away_team_id=2,
            league_id=39,
            market_codes=[],
        )

        # All evaluation methods should be called
        mock_evaluator._evaluate_main_markets.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_codes_invalid_raises(self, mock_evaluator):
        """Invalid market code should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid market codes"):
            await mock_evaluator.evaluate_all_markets(
                home_team_id=1,
                away_team_id=2,
                league_id=39,
                market_codes=["INVALID"],
            )

    @pytest.mark.asyncio
    async def test_market_codes_filters_are_applied(self, mock_evaluator):
        """market_codes should filter the results."""
        from sipap.sports.soccer.market_evaluator import MarketEvaluation, MarketOutcome

        # Create mock evaluations
        btts_outcome = MarketOutcome(outcome_code="Yes", probability=0.7, weighted_probability=0.7)
        btts_eval = MarketEvaluation(
            market_code="BTTS",
            market_name="Both Teams To Score",
            outcomes=[btts_outcome],
            best_outcome=btts_outcome,
        )

        match_outcome = MarketOutcome(outcome_code="Home", probability=0.6, weighted_probability=0.6)
        match_eval = MarketEvaluation(
            market_code="1X2",
            market_name="Match Result",
            outcomes=[match_outcome],
            best_outcome=match_outcome,
        )

        dc_outcome = MarketOutcome(outcome_code="1X", probability=0.8, weighted_probability=0.8)
        dc_eval = MarketEvaluation(
            market_code="DC",
            market_name="Double Chance",
            outcomes=[dc_outcome],
            best_outcome=dc_outcome,
        )

        # Set up main markets to return all three
        mock_evaluator._evaluate_main_markets.return_value = [btts_eval, match_eval, dc_eval]

        # Filter to only BTTS
        results = await mock_evaluator.evaluate_all_markets(
            home_team_id=1,
            away_team_id=2,
            league_id=39,
            market_codes=["BTTS"],
        )

        # Should only have BTTS
        assert len(results) == 1
        assert results[0].market_code == "BTTS"

    @pytest.mark.asyncio
    async def test_market_codes_multiple_filters(self, mock_evaluator):
        """Multiple market_codes should filter to those markets."""
        from sipap.sports.soccer.market_evaluator import MarketEvaluation, MarketOutcome

        # Create mock evaluations
        btts_outcome = MarketOutcome(outcome_code="Yes", probability=0.7, weighted_probability=0.7)
        btts_eval = MarketEvaluation(
            market_code="BTTS",
            market_name="Both Teams To Score",
            outcomes=[btts_outcome],
            best_outcome=btts_outcome,
        )

        match_outcome = MarketOutcome(outcome_code="Home", probability=0.6, weighted_probability=0.6)
        match_eval = MarketEvaluation(
            market_code="1X2",
            market_name="Match Result",
            outcomes=[match_outcome],
            best_outcome=match_outcome,
        )

        dc_outcome = MarketOutcome(outcome_code="1X", probability=0.8, weighted_probability=0.8)
        dc_eval = MarketEvaluation(
            market_code="DC",
            market_name="Double Chance",
            outcomes=[dc_outcome],
            best_outcome=dc_outcome,
        )

        # Set up main markets to return all three
        mock_evaluator._evaluate_main_markets.return_value = [btts_eval, match_eval, dc_eval]

        # Filter to BTTS and DC
        results = await mock_evaluator.evaluate_all_markets(
            home_team_id=1,
            away_team_id=2,
            league_id=39,
            market_codes=["BTTS", "DC"],
        )

        # Should have BTTS and DC, but not 1X2
        assert len(results) == 2
        codes = [r.market_code for r in results]
        assert "BTTS" in codes
        assert "DC" in codes
        assert "1X2" not in codes
