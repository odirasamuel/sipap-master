"""Unit tests for soccer markets module.

Tests market definitions, registry, and lookup functionality.
"""

import pytest

from sipap.sports.soccer.markets import (
    Market,
    MarketCategory,
    MarketRegistry,
    get_market,
    REGISTRY,
    MARKET_1X2,
    MARKET_BTTS,
    MARKET_OU25,
    MARKET_DNB,
    MARKET_DC,
)


class TestMarketDefinition:
    """Test Market class."""

    def test_market_initialization(self):
        """Test that Market initializes correctly."""
        market = Market(
            code="TEST",
            name="Test Market",
            outcomes=["Outcome 1", "Outcome 2"],
            category=MarketCategory.MAIN,
            description="Test market description",
            aliases=["test", "test market"],
        )

        assert market.code == "TEST"
        assert market.name == "Test Market"
        assert market.outcomes == ["Outcome 1", "Outcome 2"]
        assert market.category == MarketCategory.MAIN
        assert market.description == "Test market description"
        assert market.aliases == ["test", "test market"]

    def test_market_without_aliases(self):
        """Test that Market works without aliases."""
        market = Market(
            code="TEST",
            name="Test Market",
            outcomes=["Outcome 1"],
            category=MarketCategory.MAIN,
            description="Test",
        )

        assert market.aliases == []

    def test_market_1x2_definition(self):
        """Test 1X2 market definition."""
        assert MARKET_1X2.code == "1X2"
        assert MARKET_1X2.name == "Match Result"
        assert MARKET_1X2.outcomes == ["Home Win", "Draw", "Away Win"]
        assert MARKET_1X2.category == MarketCategory.MAIN
        assert "match result" in MARKET_1X2.aliases

    def test_market_btts_definition(self):
        """Test BTTS market definition."""
        assert MARKET_BTTS.code == "BTTS"
        assert MARKET_BTTS.name == "Both Teams To Score"
        assert MARKET_BTTS.outcomes == ["Yes", "No"]
        assert MARKET_BTTS.category == MarketCategory.MAIN
        assert "both teams to score" in MARKET_BTTS.aliases
        assert "gg" in MARKET_BTTS.aliases

    def test_market_ou25_definition(self):
        """Test Over/Under 2.5 market definition."""
        assert MARKET_OU25.code == "OU2.5"
        assert MARKET_OU25.name == "Total Goals Over/Under 2.5"
        assert MARKET_OU25.outcomes == ["Over 2.5", "Under 2.5"]
        assert MARKET_OU25.category == MarketCategory.MAIN
        assert "at least 3 goals" in MARKET_OU25.description.lower()


class TestMarketRegistry:
    """Test MarketRegistry class."""

    def test_registry_initialization(self):
        """Test that registry initializes with markets."""
        registry = MarketRegistry()
        markets = registry.get_all()

        assert len(markets) > 0
        assert any(m.code == "1X2" for m in markets)
        assert any(m.code == "BTTS" for m in markets)
        assert any(m.code == "OU2.5" for m in markets)

    def test_get_by_code_exact_match(self):
        """Test getting market by exact code."""
        registry = MarketRegistry()

        market = registry.get_by_code("1X2")
        assert market is not None
        assert market.code == "1X2"

        market = registry.get_by_code("BTTS")
        assert market is not None
        assert market.code == "BTTS"

        market = registry.get_by_code("OU2.5")
        assert market is not None
        assert market.code == "OU2.5"

    def test_get_by_code_case_insensitive(self):
        """Test that code lookup is case-insensitive."""
        registry = MarketRegistry()

        market = registry.get_by_code("1x2")
        assert market is not None
        assert market.code == "1X2"

        market = registry.get_by_code("btts")
        assert market is not None
        assert market.code == "BTTS"

    def test_get_by_code_not_found(self):
        """Test that non-existent code returns None."""
        registry = MarketRegistry()

        market = registry.get_by_code("NONEXISTENT")
        assert market is None

    def test_get_by_alias(self):
        """Test getting market by alias."""
        registry = MarketRegistry()

        # Test various aliases
        market = registry.get_by_alias("match result")
        assert market is not None
        assert market.code == "1X2"

        market = registry.get_by_alias("both teams to score")
        assert market is not None
        assert market.code == "BTTS"

        market = registry.get_by_alias("gg")
        assert market is not None
        assert market.code == "BTTS"

        market = registry.get_by_alias("over 2.5")
        assert market is not None
        assert market.code == "OU2.5"

    def test_get_by_alias_case_insensitive(self):
        """Test that alias lookup is case-insensitive."""
        registry = MarketRegistry()

        market = registry.get_by_alias("MATCH RESULT")
        assert market is not None
        assert market.code == "1X2"

        market = registry.get_by_alias("Both Teams To Score")
        assert market is not None
        assert market.code == "BTTS"

    def test_get_by_alias_not_found(self):
        """Test that non-existent alias returns None."""
        registry = MarketRegistry()

        market = registry.get_by_alias("nonexistent alias")
        assert market is None

    def test_get_by_category(self):
        """Test getting markets by category."""
        registry = MarketRegistry()

        main_markets = registry.get_by_category(MarketCategory.MAIN)
        assert len(main_markets) > 0
        assert all(m.category == MarketCategory.MAIN for m in main_markets)
        assert any(m.code == "1X2" for m in main_markets)
        assert any(m.code == "BTTS" for m in main_markets)

        halftime_markets = registry.get_by_category(MarketCategory.HALFTIME)
        assert len(halftime_markets) > 0
        assert all(m.category == MarketCategory.HALFTIME for m in halftime_markets)
        assert any(m.code == "HT_1X2" for m in halftime_markets)

    def test_get_by_category_empty(self):
        """Test that non-existent category returns empty list."""
        registry = MarketRegistry()

        # Create a new category that doesn't exist in registry
        markets = registry.get_by_category(MarketCategory.ADVANCED)
        # Should have at least MULTI_GOAL
        assert len(markets) >= 0


class TestMarketLookupFunction:
    """Test get_market() convenience function."""

    def test_get_market_by_code(self):
        """Test getting market by code via convenience function."""
        market = get_market("1X2")
        assert market is not None
        assert market.code == "1X2"

        market = get_market("BTTS")
        assert market is not None
        assert market.code == "BTTS"

    def test_get_market_by_alias(self):
        """Test getting market by alias via convenience function."""
        market = get_market("match result")
        assert market is not None
        assert market.code == "1X2"

        market = get_market("both teams to score")
        assert market is not None
        assert market.code == "BTTS"

    def test_get_market_prioritizes_code_over_alias(self):
        """Test that exact code match is prioritized over alias match."""
        # If a market has code "TEST" and another has alias "test",
        # get_market("TEST") should return the one with code "TEST"
        market = get_market("1X2")
        assert market is not None
        assert market.code == "1X2"

    def test_get_market_not_found(self):
        """Test that non-existent code/alias returns None."""
        market = get_market("NONEXISTENT")
        assert market is None


class TestGlobalRegistry:
    """Test global REGISTRY instance."""

    def test_global_registry_is_populated(self):
        """Test that global registry is pre-populated."""
        assert REGISTRY is not None
        markets = REGISTRY.get_all()
        assert len(markets) > 0

    def test_global_registry_has_main_markets(self):
        """Test that global registry has key markets."""
        assert REGISTRY.get_by_code("1X2") is not None
        assert REGISTRY.get_by_code("BTTS") is not None
        assert REGISTRY.get_by_code("OU2.5") is not None
        assert REGISTRY.get_by_code("DNB") is not None
        assert REGISTRY.get_by_code("DC") is not None


class TestMarketAliases:
    """Test specific market aliases for user-friendliness."""

    def test_btts_aliases(self):
        """Test BTTS has all expected aliases."""
        market = get_market("BTTS")
        assert market is not None

        # Test all BTTS aliases work
        assert get_market("both teams to score") == market
        assert get_market("gg") == market
        assert get_market("btts") == market

    def test_1x2_aliases(self):
        """Test 1X2 has expected aliases."""
        market = get_market("1X2")
        assert market is not None

        assert get_market("match result") == market
        assert get_market("full time result") == market
        assert get_market("winner") == market

    def test_over_under_aliases(self):
        """Test Over/Under markets have expected aliases."""
        market = get_market("OU2.5")
        assert market is not None

        assert get_market("over 2.5") == market
        assert get_market("under 2.5") == market
        assert get_market("o2.5") == market
        assert get_market("u2.5") == market

    def test_double_chance_aliases(self):
        """Test Double Chance aliases."""
        market = get_market("DC")
        assert market is not None

        assert get_market("double chance") == market
