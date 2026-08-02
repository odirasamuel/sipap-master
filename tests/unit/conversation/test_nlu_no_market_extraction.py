"""Unit tests verifying NLU does NOT extract markets from user messages.

Markets are NOT part of user input - they are system decisions based on EV/confidence.
Users express intent and quality, system picks best market per fixture.
"""

import pytest

from sipap.conversation.nlu_agent import NLUAgent


class TestNLUNoMarketExtraction:
    """Test that NLU does NOT extract markets from user messages."""

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

    @pytest.mark.asyncio
    async def test_markets_not_extracted_with_leagues(self, nlu):
        """Test that league-specific request has markets=None."""
        message = "20 odds in Premier League and LaLiga"
        intent = await nlu.parse_user_message(message)

        assert intent.markets is None, "Markets should NOT be extracted"
        assert "Premier League" in intent.leagues
        assert "LaLiga" in intent.leagues

    @pytest.mark.asyncio
    async def test_markets_not_extracted_even_if_market_terms_present(self, nlu):
        """Test that even if message contains market-like terms, markets remain None.

        Users might say "both teams score" or "over goals" as description,
        but system should NOT interpret this as market selection.
        """
        messages = [
            "Show me games where both teams will score",
            "I want high-scoring matches with many goals",
            "Give me safe odds with low risk",
        ]

        for message in messages:
            intent = await nlu.parse_user_message(message)
            assert intent.markets is None, f"Markets should NOT be extracted from: {message}"

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
    """Test that NLU focuses on user intent, not market selection."""

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

    @pytest.mark.asyncio
    async def test_extracts_leagues(self, nlu):
        """Test that NLU extracts league filters."""
        message = "20 odds in Premier League, LaLiga, and Bundesliga"
        intent = await nlu.parse_user_message(message)

        assert "Premier League" in intent.leagues
        assert "LaLiga" in intent.leagues
        assert "Bundesliga" in intent.leagues
        assert intent.markets is None

    @pytest.mark.asyncio
    async def test_extracts_date_range(self, nlu):
        """Test that NLU extracts date filters."""
        message = "30 odds today"
        intent = await nlu.parse_user_message(message)

        assert intent.date_range is not None
        assert intent.markets is None
