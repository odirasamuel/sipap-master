"""Soccer sports module.

Provides soccer-specific functionality including:
- Market definitions (1X2, BTTS, Over/Under, etc.)
- Market registry and lookup
"""

from sipap.sports.soccer.markets import (
    Market,
    MarketCategory,
    MarketRegistry,
    get_market,
    REGISTRY,
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
)

__all__ = [
    "Market",
    "MarketCategory",
    "MarketRegistry",
    "get_market",
    "REGISTRY",
    "MARKET_1X2",
    "MARKET_DNB",
    "MARKET_BTTS",
    "MARKET_DC",
    "MARKET_OU05",
    "MARKET_OU15",
    "MARKET_OU25",
    "MARKET_OU35",
    "MARKET_OU45",
]
