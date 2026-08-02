"""Soccer betting market definitions and registry.

Comprehensive registry of all soccer betting markets with:
- Market codes and names
- Possible outcomes per market
- User-friendly name variations
- Market categories and groupings

This module makes betting markets easy to interpret, validate, and use
throughout the SIPAP prediction system.
"""

from enum import Enum
from typing import Any


class MarketCategory(str, Enum):
    """Market categories for grouping."""

    MAIN = "main"  # Core markets (1X2, BTTS, Totals)
    HALFTIME = "halftime"  # Half-time related markets
    COMBINATIONS = "combinations"  # Combined outcome markets
    TEAM_SPECIFIC = "team_specific"  # Home/Away specific markets
    ADVANCED = "advanced"  # Complex multi-outcome markets


class Market:
    """Betting market definition.

    Attributes:
        code: Unique market code (e.g., "1X2", "BTTS", "OU2.5")
        name: Display name (e.g., "Match Result", "Both Teams To Score")
        outcomes: List of possible outcomes (e.g., ["Home", "Draw", "Away"])
        category: Market category for grouping
        description: Human-readable description
        aliases: Alternative names users might use
    """

    def __init__(
        self,
        code: str,
        name: str,
        outcomes: list[str],
        category: MarketCategory,
        description: str,
        aliases: list[str] | None = None,
    ):
        self.code = code
        self.name = name
        self.outcomes = outcomes
        self.category = category
        self.description = description
        self.aliases = aliases or []

    def __repr__(self) -> str:
        return f"Market(code={self.code!r}, name={self.name!r}, outcomes={len(self.outcomes)})"


# ============================================================================
# Market Definitions
# ============================================================================

# Main Markets
MARKET_1X2 = Market(
    code="1X2",
    name="Match Result",
    outcomes=["Home Win", "Draw", "Away Win"],
    category=MarketCategory.MAIN,
    description="Full-time match result",
    aliases=["match result", "full time result", "winner", "match winner"],
)

MARKET_DNB = Market(
    code="DNB",
    name="Draw No Bet",
    outcomes=["Home Win", "Away Win"],
    category=MarketCategory.MAIN,
    description="Match result with draw refunded",
    aliases=["draw no bet"],
)

MARKET_BTTS = Market(
    code="BTTS",
    name="Both Teams To Score",
    outcomes=["Yes", "No"],
    category=MarketCategory.MAIN,
    description="Both teams score at least one goal",
    aliases=["both teams to score", "gg/ng", "gg", "btts", "both score"],
)

MARKET_DC = Market(
    code="DC",
    name="Double Chance",
    outcomes=["1X", "12", "X2"],
    category=MarketCategory.MAIN,
    description="Bet on two outcomes (1X=Home/Draw, 12=Home/Away, X2=Draw/Away)",
    aliases=["double chance"],
)

# Total Goals Markets
MARKET_OU05 = Market(
    code="OU0.5",
    name="Total Goals Over/Under 0.5",
    outcomes=["Over 0.5", "Under 0.5"],
    category=MarketCategory.MAIN,
    description="More than 1 goal or 0 goals (Over 0.5 = at least 1 goal)",
    aliases=["over 0.5", "under 0.5", "over under 0.5"],
)

MARKET_OU15 = Market(
    code="OU1.5",
    name="Total Goals Over/Under 1.5",
    outcomes=["Over 1.5", "Under 1.5"],
    category=MarketCategory.MAIN,
    description="More than 2 goals or less than 2 goals (Over 1.5 = at least 2 goals)",
    aliases=["over 1.5", "under 1.5", "over under 1.5"],
)

MARKET_OU25 = Market(
    code="OU2.5",
    name="Total Goals Over/Under 2.5",
    outcomes=["Over 2.5", "Under 2.5"],
    category=MarketCategory.MAIN,
    description="More than 3 goals or less than 3 goals (Over 2.5 = at least 3 goals)",
    aliases=["over 2.5", "under 2.5", "over under 2.5", "o2.5", "u2.5"],
)

MARKET_OU35 = Market(
    code="OU3.5",
    name="Total Goals Over/Under 3.5",
    outcomes=["Over 3.5", "Under 3.5"],
    category=MarketCategory.MAIN,
    description="More than 4 goals or less than 4 goals (Over 3.5 = at least 4 goals)",
    aliases=["over 3.5", "under 3.5", "over under 3.5"],
)

MARKET_OU45 = Market(
    code="OU4.5",
    name="Total Goals Over/Under 4.5",
    outcomes=["Over 4.5", "Under 4.5"],
    category=MarketCategory.MAIN,
    description="More than 5 goals or less than 5 goals (Over 4.5 = at least 5 goals)",
    aliases=["over 4.5", "under 4.5", "over under 4.5"],
)

# Half-Time Markets
MARKET_HT_1X2 = Market(
    code="HT_1X2",
    name="Half-Time Result",
    outcomes=["1HT", "XHT", "2HT"],
    category=MarketCategory.HALFTIME,
    description="Result at half-time (1HT=Home, XHT=Draw, 2HT=Away)",
    aliases=["half time result", "ht result", "1x2 ht", "halftime"],
)

MARKET_HT_DC = Market(
    code="HT_DC",
    name="Half-Time Double Chance",
    outcomes=["1X", "12", "X2"],
    category=MarketCategory.HALFTIME,
    description="Double chance at half-time",
    aliases=["half time double chance", "ht double chance"],
)

MARKET_HT_OU05 = Market(
    code="HT_OU0.5",
    name="Half-Time Total Goals Over/Under 0.5",
    outcomes=["Over 0.5", "Under 0.5"],
    category=MarketCategory.HALFTIME,
    description="Half-time goals over/under 0.5",
    aliases=["ht over 0.5", "ht under 0.5", "half time over 0.5"],
)

MARKET_HT_OU15 = Market(
    code="HT_OU1.5",
    name="Half-Time Total Goals Over/Under 1.5",
    outcomes=["Over 1.5", "Under 1.5"],
    category=MarketCategory.HALFTIME,
    description="Half-time goals over/under 1.5",
    aliases=["ht over 1.5", "ht under 1.5", "half time over 1.5"],
)

MARKET_HT_OU25 = Market(
    code="HT_OU2.5",
    name="Half-Time Total Goals Over/Under 2.5",
    outcomes=["Over 2.5", "Under 2.5"],
    category=MarketCategory.HALFTIME,
    description="Half-time goals over/under 2.5",
    aliases=["ht over 2.5", "ht under 2.5", "half time over 2.5"],
)

# Half-Time/Full-Time
MARKET_HTFT = Market(
    code="HT/FT",
    name="Half-Time/Full-Time",
    outcomes=[
        "1/1", "1/X", "1/2",
        "X/1", "X/X", "X/2",
        "2/1", "2/X", "2/2",
    ],
    category=MarketCategory.COMBINATIONS,
    description="Result at HT and FT (e.g., 1/1 = Home leading at HT, Home wins FT)",
    aliases=["half time full time", "ht ft", "ht/ft"],
)

# Team-Specific Markets
MARKET_HOME_SCORE = Market(
    code="HOME_SCORE",
    name="Home Team To Score",
    outcomes=["Yes", "No"],
    category=MarketCategory.TEAM_SPECIFIC,
    description="Home team scores at least one goal",
    aliases=["home to score", "home team to score"],
)

MARKET_AWAY_SCORE = Market(
    code="AWAY_SCORE",
    name="Away Team To Score",
    outcomes=["Yes", "No"],
    category=MarketCategory.TEAM_SPECIFIC,
    description="Away team scores at least one goal",
    aliases=["away to score", "away team to score"],
)

MARKET_HOME_WIN_HALF = Market(
    code="HOME_WIN_HALF",
    name="Home To Win Either Half",
    outcomes=["Yes", "No"],
    category=MarketCategory.TEAM_SPECIFIC,
    description="Home team wins at least one half",
    aliases=["home to win either half", "home win half"],
)

MARKET_AWAY_WIN_HALF = Market(
    code="AWAY_WIN_HALF",
    name="Away To Win Either Half",
    outcomes=["Yes", "No"],
    category=MarketCategory.TEAM_SPECIFIC,
    description="Away team wins at least one half",
    aliases=["away to win either half", "away win half"],
)

# Combination Markets (1X2 & Totals)
MARKET_1X2_OU15 = Market(
    code="1X2_OU1.5",
    name="1X2 & Total Goals 1.5",
    outcomes=["1&Over", "1&Under", "X&Over", "X&Under", "2&Over", "2&Under"],
    category=MarketCategory.COMBINATIONS,
    description="Match result combined with over/under 1.5 goals",
    aliases=["1x2 and over under 1.5", "result and total 1.5"],
)

MARKET_1X2_OU25 = Market(
    code="1X2_OU2.5",
    name="1X2 & Total Goals 2.5",
    outcomes=["1&Over", "1&Under", "X&Over", "X&Under", "2&Over", "2&Under"],
    category=MarketCategory.COMBINATIONS,
    description="Match result combined with over/under 2.5 goals",
    aliases=["1x2 and over under 2.5", "result and total 2.5"],
)

MARKET_1X2_OU35 = Market(
    code="1X2_OU3.5",
    name="1X2 & Total Goals 3.5",
    outcomes=["1&Over", "1&Under", "X&Over", "X&Under", "2&Over", "2&Under"],
    category=MarketCategory.COMBINATIONS,
    description="Match result combined with over/under 3.5 goals",
    aliases=["1x2 and over under 3.5", "result and total 3.5"],
)

MARKET_1X2_OU45 = Market(
    code="1X2_OU4.5",
    name="1X2 & Total Goals 4.5",
    outcomes=["1&Over", "1&Under", "X&Over", "X&Under", "2&Over", "2&Under"],
    category=MarketCategory.COMBINATIONS,
    description="Match result combined with over/under 4.5 goals",
    aliases=["1x2 and over under 4.5", "result and total 4.5"],
)

# Combination Markets (1X2 & BTTS)
MARKET_1X2_BTTS = Market(
    code="1X2_BTTS",
    name="1X2 & Both Teams To Score",
    outcomes=["1&GG", "1&NG", "X&GG", "X&NG", "2&GG", "2&NG"],
    category=MarketCategory.COMBINATIONS,
    description="Match result combined with both teams to score (GG=Yes, NG=No)",
    aliases=["1x2 and btts", "result and both teams to score", "1x2 and gg/ng"],
)

# Combination Markets (Double Chance & Totals)
MARKET_DC_OU15 = Market(
    code="DC_OU1.5",
    name="Double Chance & Total Goals 1.5",
    outcomes=["1X&Over", "1X&Under", "12&Over", "12&Under", "X2&Over", "X2&Under"],
    category=MarketCategory.COMBINATIONS,
    description="Double chance combined with over/under 1.5 goals",
    aliases=["double chance and over under 1.5", "dc and total 1.5"],
)

MARKET_DC_OU25 = Market(
    code="DC_OU2.5",
    name="Double Chance & Total Goals 2.5",
    outcomes=["1X&Over", "1X&Under", "12&Over", "12&Under", "X2&Over", "X2&Under"],
    category=MarketCategory.COMBINATIONS,
    description="Double chance combined with over/under 2.5 goals",
    aliases=["double chance and over under 2.5", "dc and total 2.5"],
)

MARKET_DC_OU35 = Market(
    code="DC_OU3.5",
    name="Double Chance & Total Goals 3.5",
    outcomes=["1X&Over", "1X&Under", "12&Over", "12&Under", "X2&Over", "X2&Under"],
    category=MarketCategory.COMBINATIONS,
    description="Double chance combined with over/under 3.5 goals",
    aliases=["double chance and over under 3.5", "dc and total 3.5"],
)

# Combination Markets (Double Chance & BTTS)
MARKET_DC_BTTS = Market(
    code="DC_BTTS",
    name="Double Chance & Both Teams To Score",
    outcomes=["1X&GG", "1X&NG", "12&GG", "12&NG", "X2&GG", "X2&NG"],
    category=MarketCategory.COMBINATIONS,
    description="Double chance combined with both teams to score",
    aliases=["double chance and btts", "dc and both teams to score"],
)

# Combination Markets (BTTS & Totals)
MARKET_BTTS_OU25 = Market(
    code="BTTS_OU2.5",
    name="GG/NG & Total Goal 2.5",
    outcomes=["GG+Over", "GG+Under", "NG+Over", "NG+Under"],
    category=MarketCategory.COMBINATIONS,
    description="Both teams score AND over/under 2.5 goals (BOTH conditions must be true)",
    aliases=["btts and over under 2.5", "gg/ng and total 2.5", "gg/ng total 2.5"],
)

MARKET_BTTS_OU35 = Market(
    code="BTTS_OU3.5",
    name="GG/NG & Total Goal 3.5",
    outcomes=["GG+Over", "GG+Under", "NG+Over", "NG+Under"],
    category=MarketCategory.COMBINATIONS,
    description="Both teams score AND over/under 3.5 goals (BOTH conditions must be true)",
    aliases=["btts and over under 3.5", "gg/ng and total 3.5", "gg/ng total 3.5"],
)

# Multi-Goal Markets
MARKET_MULTI_GOAL = Market(
    code="MULTI_GOAL",
    name="Multi Goal",
    outcomes=[
        "1-2 goals", "2-3 goals", "3-4 goals", "4-5 goals", "5-6 goals",
        "1-3 goals", "2-4 goals", "3-5 goals", "4-6 goals",
        "1-4 goals", "2-5 goals", "3-6 goals",
        "1-5 goals", "2-6 goals",
        "7+ goals",
    ],
    category=MarketCategory.ADVANCED,
    description="Exact goal range (e.g., 1-2 goals means 1 or 2 total goals in match)",
    aliases=["multi goal", "goal range", "exact goals"],
)


# Chance Mix Markets (OR logic - EITHER condition must be true)
MARKET_CHANCEMIX_1X2_OU15 = Market(
    code="CHANCEMIX_1X2_OU15",
    name="Chance Mix 1X2 or Total Goal 1.5",
    outcomes=["1orOver", "1orUnder", "XorOver", "XorUnder", "2orOver", "2orUnder"],
    category=MarketCategory.COMBINATIONS,
    description="Home Win OR Over 1.5 (at least 2 goals), Draw OR Over 1.5, etc. - EITHER condition wins",
    aliases=["chance mix total 1.5", "1x2 or total 1.5", "chance mix 1.5"],
)

MARKET_CHANCEMIX_1X2_OU25 = Market(
    code="CHANCEMIX_1X2_OU25",
    name="Chance Mix 1X2 or Total Goal 2.5",
    outcomes=["1orOver", "1orUnder", "XorOver", "XorUnder", "2orOver", "2orUnder"],
    category=MarketCategory.COMBINATIONS,
    description="Home Win OR Over 2.5 (at least 3 goals), Draw OR Over 2.5, etc. - EITHER condition wins",
    aliases=["chance mix total 2.5", "1x2 or total 2.5", "chance mix 2.5"],
)

MARKET_CHANCEMIX_1X2_OU35 = Market(
    code="CHANCEMIX_1X2_OU35",
    name="Chance Mix 1X2 or Total Goal 3.5",
    outcomes=["1orOver", "1orUnder", "XorOver", "XorUnder", "2orOver", "2orUnder"],
    category=MarketCategory.COMBINATIONS,
    description="Home Win OR Over 3.5 (at least 4 goals), Draw OR Over 3.5, etc. - EITHER condition wins",
    aliases=["chance mix total 3.5", "1x2 or total 3.5", "chance mix 3.5"],
)

MARKET_CHANCEMIX_1X2_BTTS = Market(
    code="CHANCEMIX_1X2_BTTS",
    name="Chance Mix 1X2 or GG/NG",
    outcomes=["1orGG", "XorGG", "1orNG", "2orNG", "XorNG", "2orGG"],
    category=MarketCategory.COMBINATIONS,
    description="Home Win OR Both Teams Score, Draw OR Both Teams Score, etc. - EITHER condition wins",
    aliases=["chance mix btts", "1x2 or gg", "chance mix gg/ng"],
)

MARKET_CHANCEMIX_BTTS_OU15 = Market(
    code="CHANCEMIX_BTTS_OU15",
    name="Chance Mix GG/NG or Total 1.5",
    outcomes=["GGorOver", "GGorUnder", "NGorUnder"],
    category=MarketCategory.COMBINATIONS,
    description="Both Teams Score OR Over 1.5 (at least 2 goals), Both Teams Score OR Under 1.5, etc. - EITHER condition wins",
    aliases=["chance mix gg total 1.5", "btts or total 1.5", "gg or 1.5"],
)

MARKET_CHANCEMIX_BTTS_OU25 = Market(
    code="CHANCEMIX_BTTS_OU25",
    name="Chance Mix GG/NG or Total 2.5",
    outcomes=["GGorOver", "GGorUnder", "NGorUnder", "NGorOver"],
    category=MarketCategory.COMBINATIONS,
    description="Both Teams Score OR Over 2.5 (at least 3 goals), Both Teams Score OR Under 2.5, etc. - EITHER condition wins",
    aliases=["chance mix gg total 2.5", "btts or total 2.5", "gg or 2.5"],
)

MARKET_CHANCEMIX_BTTS_OU35 = Market(
    code="CHANCEMIX_BTTS_OU35",
    name="Chance Mix GG/NG or Total 3.5",
    outcomes=["GGorOver", "GGorUnder", "NGorUnder", "NGorOver"],
    category=MarketCategory.COMBINATIONS,
    description="Both Teams Score OR Over 3.5 (at least 4 goals), Both Teams Score OR Under 3.5, etc. - EITHER condition wins",
    aliases=["chance mix gg total 3.5", "btts or total 3.5", "gg or 3.5"],
)


# 2nd Half Markets
MARKET_2H_DC = Market(
    code="2H_DC",
    name="2nd Half Double Chance",
    outcomes=["1X", "12", "X2"],
    category=MarketCategory.HALFTIME,
    description="2nd half: Home or Draw (1X), Either Team Wins (12), Away or Draw (X2)",
    aliases=["2nd half double chance", "second half dc", "2h dc"],
)

MARKET_2H_OU05 = Market(
    code="2H_OU0.5",
    name="2nd Half Total Goals Over/Under 0.5",
    outcomes=["Over 0.5", "Under 0.5"],
    category=MarketCategory.HALFTIME,
    description="2nd half: More than 1 goal or no goals",
    aliases=["2nd half over 0.5", "2h over 0.5", "second half total 0.5"],
)

MARKET_2H_OU15 = Market(
    code="2H_OU1.5",
    name="2nd Half Total Goals Over/Under 1.5",
    outcomes=["Over 1.5", "Under 1.5"],
    category=MarketCategory.HALFTIME,
    description="2nd half: More than 2 goals or less than 2 goals (Over 1.5 = at least 2 goals)",
    aliases=["2nd half over 1.5", "2h over 1.5", "second half total 1.5"],
)

MARKET_2H_OU25 = Market(
    code="2H_OU2.5",
    name="2nd Half Total Goals Over/Under 2.5",
    outcomes=["Over 2.5", "Under 2.5"],
    category=MarketCategory.HALFTIME,
    description="2nd half: More than 3 goals or less than 3 goals (Over 2.5 = at least 3 goals)",
    aliases=["2nd half over 2.5", "2h over 2.5", "second half total 2.5"],
)


# Simple Scoring Markets
MARKET_HOME_TO_SCORE = Market(
    code="HOME_TO_SCORE",
    name="Home To Score",
    outcomes=["Yes", "No"],
    category=MarketCategory.TEAM_SPECIFIC,
    description="Home team scores at least one goal (Yes) or not (No)",
    aliases=["home to score", "home team score", "home scores"],
)

MARKET_AWAY_TO_SCORE = Market(
    code="AWAY_TO_SCORE",
    name="Away To Score",
    outcomes=["Yes", "No"],
    category=MarketCategory.TEAM_SPECIFIC,
    description="Away team scores at least one goal (Yes) or not (No)",
    aliases=["away to score", "away team score", "away scores"],
)


# ============================================================================
# Market Registry
# ============================================================================

class MarketRegistry:
    """Central registry of all betting markets.

    Provides lookups by:
    - Market code (e.g., "1X2", "BTTS")
    - Market name (e.g., "Match Result")
    - User-friendly aliases (e.g., "both teams to score" → BTTS)

    Example:
        >>> registry = MarketRegistry()
        >>> market = registry.get_by_code("1X2")
        >>> print(market.name)
        "Match Result"
        >>> market = registry.get_by_alias("both teams to score")
        >>> print(market.code)
        "BTTS"
    """

    def __init__(self):
        """Initialize market registry with all markets."""
        # Register all markets
        self._markets: list[Market] = [
            # Main markets
            MARKET_1X2,
            MARKET_DNB,
            MARKET_BTTS,
            MARKET_DC,
            # Total goals
            MARKET_OU05,
            MARKET_OU15,
            MARKET_OU25,
            MARKET_OU35,
            MARKET_OU45,
            # Half-time markets
            MARKET_HT_1X2,
            MARKET_HT_DC,
            MARKET_HT_OU05,
            MARKET_HT_OU15,
            MARKET_HT_OU25,
            # HT/FT
            MARKET_HTFT,
            # Team-specific
            MARKET_HOME_SCORE,
            MARKET_AWAY_SCORE,
            MARKET_HOME_WIN_HALF,
            MARKET_AWAY_WIN_HALF,
            # Combinations (1X2 & Totals)
            MARKET_1X2_OU15,
            MARKET_1X2_OU25,
            MARKET_1X2_OU35,
            MARKET_1X2_OU45,
            # Combinations (1X2 & BTTS)
            MARKET_1X2_BTTS,
            # Combinations (DC & Totals)
            MARKET_DC_OU15,
            MARKET_DC_OU25,
            MARKET_DC_OU35,
            # Combinations (DC & BTTS)
            MARKET_DC_BTTS,
            # Combinations (BTTS & Totals)
            MARKET_BTTS_OU25,
            MARKET_BTTS_OU35,
            # Chance Mix (OR logic)
            MARKET_CHANCEMIX_1X2_OU15,
            MARKET_CHANCEMIX_1X2_OU25,
            MARKET_CHANCEMIX_1X2_OU35,
            MARKET_CHANCEMIX_1X2_BTTS,
            MARKET_CHANCEMIX_BTTS_OU15,
            MARKET_CHANCEMIX_BTTS_OU25,
            MARKET_CHANCEMIX_BTTS_OU35,
            # 2nd Half markets
            MARKET_2H_DC,
            MARKET_2H_OU05,
            MARKET_2H_OU15,
            MARKET_2H_OU25,
            # Simple scoring markets
            MARKET_HOME_TO_SCORE,
            MARKET_AWAY_TO_SCORE,
            # Advanced
            MARKET_MULTI_GOAL,
        ]

        # Build lookup indices
        self._by_code: dict[str, Market] = {m.code: m for m in self._markets}

        self._by_alias: dict[str, Market] = {}
        for market in self._markets:
            # Add market code as alias (lowercase)
            self._by_alias[market.code.lower()] = market
            # Add market name as alias (lowercase)
            self._by_alias[market.name.lower()] = market
            # Add all aliases (lowercase)
            for alias in market.aliases:
                self._by_alias[alias.lower()] = market

    def get_by_code(self, code: str) -> Market | None:
        """Get market by code (case-insensitive).

        Args:
            code: Market code (e.g., "1X2", "btts", "Ou2.5")

        Returns:
            Market if found, None otherwise

        Example:
            >>> registry.get_by_code("1X2")  # Works
            >>> registry.get_by_code("1x2")  # Also works (case-insensitive)
            >>> registry.get_by_code("BTTS")  # Works
            >>> registry.get_by_code("btts")  # Also works
        """
        return self._by_code.get(code.upper())

    def get_by_alias(self, alias: str) -> Market | None:
        """Get market by user-friendly alias.

        Args:
            alias: Market alias (e.g., "both teams to score", "over 2.5")

        Returns:
            Market if found, None otherwise

        Example:
            >>> registry.get_by_alias("both teams to score")
            Market(code='BTTS', ...)
            >>> registry.get_by_alias("over 2.5")
            Market(code='OU2.5', ...)
        """
        return self._by_alias.get(alias.lower().strip())

    def get_all(self) -> list[Market]:
        """Get all registered markets.

        Returns:
            List of all markets
        """
        return self._markets.copy()

    def get_by_category(self, category: MarketCategory) -> list[Market]:
        """Get all markets in a category.

        Args:
            category: Market category

        Returns:
            List of markets in category
        """
        return [m for m in self._markets if m.category == category]

    def get_main_markets(self) -> list[Market]:
        """Get main/core betting markets.

        Returns:
            List of main markets (1X2, BTTS, Totals, etc.)
        """
        return self.get_by_category(MarketCategory.MAIN)


# Global registry instance
REGISTRY = MarketRegistry()


# ============================================================================
# Convenience Functions
# ============================================================================

def get_market(code_or_alias: str) -> Market | None:
    """Get market by code or alias.

    Args:
        code_or_alias: Market code (e.g., "1X2") or alias (e.g., "match result")

    Returns:
        Market if found, None otherwise

    Example:
        >>> market = get_market("1X2")
        >>> market = get_market("both teams to score")
        >>> market = get_market("over 2.5")
    """
    # Try exact code first
    market = REGISTRY.get_by_code(code_or_alias)
    if market:
        return market

    # Try alias
    return REGISTRY.get_by_alias(code_or_alias)


def get_all_markets() -> list[Market]:
    """Get all registered markets.

    Returns:
        List of all markets
    """
    return REGISTRY.get_all()


def get_main_markets() -> list[Market]:
    """Get main/core betting markets.

    Returns:
        List of main markets
    """
    return REGISTRY.get_main_markets()
