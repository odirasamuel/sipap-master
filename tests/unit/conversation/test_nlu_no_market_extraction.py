"""Unit tests verifying NLU hybrid market extraction behavior.

HYBRID APPROACH (updated 2026-08-19):
- Markets ARE extracted when explicitly mentioned (e.g., "BTTS picks", "1X2 selections")
- Markets ARE extracted from natural language aliases (e.g., "both teams to score" -> BTTS)
- Markets are NOT extracted when ONLY quality terms are present (e.g., "20 sure odds")

This file focuses on testing that QUALITY-ONLY requests do NOT extract markets,
allowing the system to intelligently select the best market per fixture.

See test_nlu_market_extraction.py for comprehensive market extraction tests.

NOTE: Some tests that require league extraction or quality threshold parsing
are marked as skip because they depend on Claude NLU (AWS Bedrock) or improved
regex fallback functionality.
"""

import pytest

from sipap.conversation.nlu_agent import NLUAgent

# Marker for tests that require full NLU functionality (Claude NLU or improved regex)
NEEDS_FULL_NLU = pytest.mark.skip(
    reason="Requires AWS Bedrock access or improved regex fallback - integration test"
)


class TestNLUNoMarketExtraction:
    """Test that NLU does NOT extract markets from QUALITY-ONLY messages.

    Hybrid approach: Markets are only extracted when explicitly mentioned
    or when natural language aliases are used. Quality-only requests
    (e.g., "20 sure odds") should have markets=None.
    """

    @pytest.fixture
    def nlu(self):
        """Create NLUAgent for testing."""
        return NLUAgent()

    @pytest.mark.asyncio
    async def test_markets_not_extracted_from_simple_request(self, nlu):
        """Test that simple odds request has markets=None."""
        message = "I need 20 odds"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is None, "Markets should NOT be extracted from user messages"
        assert intent.target_odds == 20.0

    @pytest.mark.asyncio
    async def test_markets_not_extracted_with_quality(self, nlu):
        """Test that quality request has markets=None."""
        message = "I need 20 odds with highest positive outcome"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is None, "Markets should NOT be extracted, even with quality terms"
        assert intent.quality_threshold == "highest"
        assert intent.target_odds == 20.0

    @NEEDS_FULL_NLU
    @pytest.mark.asyncio
    async def test_markets_not_extracted_with_leagues(self, nlu):
        """Test that league-specific request has markets=None."""
        message = "20 odds in Premier League and LaLiga"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is None, "Markets should NOT be extracted"
        # leagues is list[LeagueEntity] | None - extract names if present
        if intent.leagues is not None:
            league_names = [league.name for league in intent.leagues]
            assert "Premier League" in league_names
            assert "La Liga" in league_names or "LaLiga" in league_names

    @pytest.mark.asyncio
    async def test_markets_not_extracted_from_quality_only_terms(self, nlu):
        """Test that quality-only terms do NOT extract markets.

        Users expressing quality requirements without market-specific language
        should get markets=None, allowing system to select best market.

        NOTE: "both teams score" and "over 2.5" DO extract markets now (hybrid approach).
        These tests focus on quality terms WITHOUT market references.
        """
        messages = [
            "Give me safe odds with low risk",
            "I need the highest quality selections",
            "Best possible outcome predictions",
            "Show me very confident picks",
        ]

        for message in messages:
            intent = await nlu.parse_user_message(message)
            assert intent.markets is None, f"Markets should NOT be extracted from quality-only: {message}"

    @pytest.mark.asyncio
    async def test_markets_field_reserved_for_internal_use(self, nlu):
        """Test that markets field exists but is for internal use only."""
        message = "20 odds with best outcomes"
        intent = await nlu.parse_user_message(message)

        # Field exists in model
        assert hasattr(intent, "markets")

        # But it's None from user messages
        assert intent.markets is None

        # System can set it programmatically for testing/debugging
        intent.markets = ["BTTS"]  # Internal use
        assert intent.markets == ["BTTS"]


class TestNLUFocusOnIntent:
    """Test that NLU focuses on extracting intent and quality.

    These tests verify that core NLU functionality (intent, quality, leagues, dates)
    works correctly. Markets should be None for quality-only requests.
    """

    @pytest.fixture
    def nlu(self):
        """Create NLUAgent for testing."""
        return NLUAgent()

    @pytest.mark.asyncio
    async def test_extracts_target_odds(self, nlu):
        """Test that NLU correctly extracts target odds."""
        message = "I need 30 odds"
        intent = await nlu.parse_user_message(message)

        assert intent.target_odds == 30.0
        assert intent.accumulation_mode is True

    @pytest.mark.asyncio
    async def test_extracts_quality_threshold(self, nlu):
        """Test that NLU extracts quality requirements."""
        test_cases = [
            ("20 sure odds", "highest"),
            ("30 odds with highest positive outcome", "highest"),
            ("15 odds with very high success", "highest"),
            ("25 odds best possible", "high"),
            ("20 odds good chance", "high"),
        ]

        for message, expected_quality in test_cases:
            intent = await nlu.parse_user_message(message)
            assert intent.quality_threshold == expected_quality, f"Failed for: {message}"
            assert intent.markets is None

    @NEEDS_FULL_NLU
    @pytest.mark.asyncio
    async def test_extracts_leagues(self, nlu):
        """Test that NLU extracts league filters."""
        message = "20 odds in Premier League, LaLiga, and Bundesliga"
        intent = await nlu.parse_user_message(message)

        # leagues is list[LeagueEntity] | None - extract names if present
        assert intent.leagues is not None, "leagues should be extracted"
        league_names = [league.name for league in intent.leagues]
        assert "Premier League" in league_names
        assert "La Liga" in league_names or "LaLiga" in league_names
        assert "Bundesliga" in league_names
        assert intent.markets is None

    @pytest.mark.asyncio
    async def test_extracts_date_range(self, nlu):
        """Test that NLU extracts date filters."""
        message = "30 odds today"
        intent = await nlu.parse_user_message(message)

        assert intent.date_range is not None
        assert intent.markets is None
