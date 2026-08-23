"""
Simple API-Football client for odds fetching.

This client provides direct access to API-Football's odds endpoint
without depending on sipap_data_mcp.

Uses bet mappings from sipap.sports.soccer.bet_mappings for market-to-bet-id
and outcome-to-API-value translations.
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


def _get_bet_mapping(market_code: str) -> tuple[int | None, dict[str, str], float | None]:
    """Get bet ID, outcome mapping, and line for a market code.

    Uses the canonical mappings from sipap.sports.soccer.bet_mappings.

    Returns:
        Tuple of (bet_id, outcome_mapping, line) or (None, {}, None) if not found
    """
    try:
        from sipap.sports.soccer.bet_mappings import get_bet_mapping
        mapping = get_bet_mapping(market_code)
        if mapping:
            return mapping.bet_id, mapping.outcome_mapping, mapping.line
    except ImportError:
        logger.debug("bet_mappings not available, using fallback")

    # Fallback mappings for core markets if bet_mappings not available
    FALLBACK_MAPPINGS = {
        "1X2": (1, {"Home Win": "Home", "Draw": "Draw", "Away Win": "Away", "Home": "Home", "Away": "Away"}, None),
        "DC": (12, {"1X": "Home/Draw", "12": "Home/Away", "X2": "Draw/Away"}, None),
        "BTTS": (8, {"Yes": "Yes", "No": "No"}, None),
        "DNB": (10, {"Home Win": "Home", "Away Win": "Away", "Home": "Home", "Away": "Away"}, None),
        "OU0.5": (5, {"Over 0.5": "Over 0.5", "Under 0.5": "Under 0.5"}, 0.5),
        "OU1.5": (5, {"Over 1.5": "Over 1.5", "Under 1.5": "Under 1.5"}, 1.5),
        "OU2.5": (5, {"Over 2.5": "Over 2.5", "Under 2.5": "Under 2.5"}, 2.5),
        "OU3.5": (5, {"Over 3.5": "Over 3.5", "Under 3.5": "Under 3.5"}, 3.5),
        "OU4.5": (5, {"Over 4.5": "Over 4.5", "Under 4.5": "Under 4.5"}, 4.5),
        "HT_1X2": (13, {"1HT": "Home", "XHT": "Draw", "2HT": "Away"}, None),
        "HT/FT": (7, {"1/1": "Home/Home", "1/X": "Home/Draw", "X/X": "Draw/Draw", "2/2": "Away/Away"}, None),
    }
    return FALLBACK_MAPPINGS.get(market_code, (None, {}, None))


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
            outcome_code: Outcome code (e.g., "Home Win", "Away", "Yes")

        Returns:
            Dictionary with best_odds, bookmaker, and all_odds
        """
        # Get bet mapping from canonical source
        bet_id, outcome_map, line = _get_bet_mapping(market_code)
        if not bet_id:
            logger.warning(f"No bet ID mapping for market {market_code}")
            return {"best_odds": 0.0, "bookmaker": "", "all_odds": []}

        # Map outcome to API format using the canonical mapping
        api_outcome = outcome_map.get(outcome_code, outcome_code)
        logger.info(f"Fetching odds: {market_code}/{outcome_code} -> bet_id={bet_id}, api_outcome={api_outcome}")

        # Fetch odds
        response = await self.get_odds(fixture_id)

        if not response.get("response"):
            logger.warning(f"No odds response for fixture {fixture_id}")
            return {"best_odds": 0.0, "bookmaker": "", "all_odds": []}

        fixture_odds = response["response"][0]
        bookmakers = fixture_odds.get("bookmakers", [])

        # Log available bets for debugging DNB issue
        if bookmakers:
            first_bookmaker = bookmakers[0]
            available_bet_ids = [bet["id"] for bet in first_bookmaker.get("bets", [])]
            logger.debug(f"Fixture {fixture_id}: available bet IDs from {first_bookmaker['name']}: {available_bet_ids}")
            if bet_id not in available_bet_ids:
                logger.warning(f"Fixture {fixture_id}: bet_id={bet_id} ({market_code}) not available. Available: {available_bet_ids}")

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

        if best_odds == 0.0:
            logger.warning(
                f"No odds found for fixture {fixture_id}: {market_code}/{outcome_code} "
                f"(bet_id={bet_id}, api_outcome={api_outcome})"
            )
        else:
            logger.info(f"Found odds: {market_code}/{outcome_code} = {best_odds} @ {best_bookmaker}")

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
