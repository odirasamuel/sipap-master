"""
Simple API-Football client for odds fetching.

This client provides direct access to API-Football's odds endpoint
without depending on sipap_data_mcp.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Bookmaker IDs by priority (most reliable first)
# Based on bet coverage: Bet365 (102), Betano (88), 1xBet (83)
PREFERRED_BOOKMAKERS = [8, 32, 11, 2, 7, 4]  # Bet365, Betano, 1xBet, Marathonbet, William Hill, Pinnacle

# Market name mappings to API-Football bet IDs
MARKET_BET_IDS = {
    "1X2": 1,       # Match Winner
    "DC": 12,       # Double Chance
    "BTTS": 8,      # Both Teams Score
    "OU2.5": 5,     # Goals Over/Under 2.5
    "OU1.5": 5,     # Goals Over/Under 1.5
    "OU3.5": 5,     # Goals Over/Under 3.5
    "DNB": 7,       # Draw No Bet
    "HT_FT": 14,    # Half Time / Full Time
    "CS": 10,       # Correct Score
}

# Outcome mappings from our codes to API values
OUTCOME_MAPPINGS = {
    "1X2": {
        "Home": "Home",
        "Draw": "Draw",
        "Away": "Away",
        "1": "Home",
        "X": "Draw",
        "2": "Away",
        # Handle variations from market evaluator
        "Home Win": "Home",
        "Away Win": "Away",
        "home": "Home",
        "away": "Away",
        "draw": "Draw",
    },
    "DC": {
        "1X": "Home/Draw",
        "12": "Home/Away",
        "X2": "Draw/Away",
        "Home/Draw": "Home/Draw",
        "Home/Away": "Home/Away",
        "Draw/Away": "Draw/Away",
    },
    "BTTS": {
        "Yes": "Yes",
        "No": "No",
        "yes": "Yes",
        "no": "No",
    },
    "OU2.5": {
        "Over": "Over 2.5",
        "Under": "Under 2.5",
        "over": "Over 2.5",
        "under": "Under 2.5",
    },
}


class APIFootballOddsClient:
    """Simple client for fetching odds from API-Football."""

    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str | None = None):
        """Initialize the client.

        Args:
            api_key: API-Football API key. If not provided, reads from
                     API_FOOTBALL_KEY environment variable.
        """
        self.api_key = api_key or os.environ.get("API_FOOTBALL_KEY", "")
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Initialize the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={"x-apisports-key": self.api_key},
                timeout=30.0,
            )

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_odds(
        self,
        fixture_id: int,
        bookmaker_id: int | None = None,
    ) -> dict[str, Any]:
        """Fetch odds for a fixture.

        Args:
            fixture_id: API-Football fixture ID
            bookmaker_id: Optional specific bookmaker ID

        Returns:
            API response with odds data
        """
        if not self._client:
            await self.connect()

        params: dict[str, Any] = {"fixture": fixture_id}
        if bookmaker_id:
            params["bookmaker"] = bookmaker_id

        try:
            response = await self._client.get("/odds", params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Failed to fetch odds for fixture {fixture_id}: {e}")
            return {"response": []}

    async def get_odds_for_market(
        self,
        fixture_id: int,
        market_code: str,
        outcome_code: str,
    ) -> dict[str, Any]:
        """Get best odds for a specific market and outcome.

        Args:
            fixture_id: API-Football fixture ID
            market_code: Market code (e.g., "1X2", "DC", "BTTS")
            outcome_code: Outcome code (e.g., "Home", "Away", "Yes")

        Returns:
            Dictionary with best_odds, bookmaker, and all_odds
        """
        bet_id = MARKET_BET_IDS.get(market_code)
        if not bet_id:
            logger.debug(f"No bet ID mapping for market {market_code}")
            return {"best_odds": 0.0, "bookmaker": "", "all_odds": []}

        # Map outcome to API format
        outcome_map = OUTCOME_MAPPINGS.get(market_code, {})
        api_outcome = outcome_map.get(outcome_code, outcome_code)

        # Fetch odds
        response = await self.get_odds(fixture_id)

        if not response.get("response"):
            return {"best_odds": 0.0, "bookmaker": "", "all_odds": []}

        fixture_odds = response["response"][0]
        bookmakers = fixture_odds.get("bookmakers", [])

        best_odds = 0.0
        best_bookmaker = ""
        all_odds = []

        # Check preferred bookmakers first, then others
        bookmaker_list = sorted(
            bookmakers,
            key=lambda b: (
                PREFERRED_BOOKMAKERS.index(b["id"])
                if b["id"] in PREFERRED_BOOKMAKERS
                else 999
            ),
        )

        for bookmaker in bookmaker_list:
            for bet in bookmaker.get("bets", []):
                if bet["id"] != bet_id:
                    continue

                for value in bet.get("values", []):
                    if value["value"] == api_outcome:
                        try:
                            odd = float(value["odd"])
                            all_odds.append({
                                "bookmaker": bookmaker["name"],
                                "bookmaker_id": bookmaker["id"],
                                "odd": odd,
                            })

                            # Track best odds
                            if odd > best_odds:
                                best_odds = odd
                                best_bookmaker = bookmaker["name"]
                        except (ValueError, TypeError):
                            continue

        return {
            "best_odds": best_odds,
            "bookmaker": best_bookmaker,
            "all_odds": all_odds,
        }


async def get_fixture_odds(
    fixture_id: int,
    market_code: str,
    outcome_code: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Convenience function to get odds for a single market.

    Args:
        fixture_id: API-Football fixture ID
        market_code: Market code (e.g., "1X2", "DC")
        outcome_code: Outcome code (e.g., "Home", "Away")
        api_key: Optional API key (uses env var if not provided)

    Returns:
        Dictionary with best_odds, bookmaker, and all_odds
    """
    client = APIFootballOddsClient(api_key)
    try:
        await client.connect()
        return await client.get_odds_for_market(fixture_id, market_code, outcome_code)
    finally:
        await client.close()
