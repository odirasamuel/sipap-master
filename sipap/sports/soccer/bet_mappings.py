"""Market code to API-Football bet ID mappings.

This module provides mappings between SIPAP's 44 market codes and
API-Football's bet type IDs, enabling odds fetching for any market.

API-Football Bet IDs Reference:
- 1: Match Winner (1X2)
- 2: Home/Away (no draw)
- 3: Second Half Winner
- 4: Asian Handicap
- 5: Goals Over/Under
- 6: Goals Over/Under First Half
- 7: HT/FT Double
- 8: Both Teams To Score
- 9: Exact Score
- 10: Draw No Bet
- 11: Winning Margin
- 12: Double Chance
- 13: First Half Winner (HT_1X2)
- 14: Team To Score First
- 15: Team To Score Last
- 16: Total - Home
- 17: Total - Away
- And 30+ more...
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BetMapping:
    """Maps a SIPAP market code to API-Football bet configuration.

    Attributes:
        market_code: SIPAP market code (e.g., "1X2", "BTTS", "OU2.5")
        bet_id: API-Football bet type ID
        outcome_mapping: Maps SIPAP outcome names to API-Football values
        line: Goal line for Over/Under markets (e.g., 2.5 for OU2.5)
    """

    market_code: str
    bet_id: int
    outcome_mapping: dict[str, str]
    line: float | None = None

    def get_api_outcome(self, sipap_outcome: str) -> str | None:
        """Convert SIPAP outcome to API-Football value.

        Args:
            sipap_outcome: SIPAP outcome code (e.g., "Home Win", "Over 2.5")

        Returns:
            API-Football value string or None if not mapped
        """
        return self.outcome_mapping.get(sipap_outcome)


# ============================================================================
# Core Market Mappings
# ============================================================================

MARKET_TO_BET_ID: dict[str, BetMapping] = {
    # -------------------------------------------------------------------------
    # Main Markets (9)
    # -------------------------------------------------------------------------
    "1X2": BetMapping(
        market_code="1X2",
        bet_id=1,
        outcome_mapping={
            "Home Win": "Home",
            "Draw": "Draw",
            "Away Win": "Away",
        },
    ),
    "DNB": BetMapping(
        market_code="DNB",
        bet_id=10,
        outcome_mapping={
            "Home Win": "Home",
            "Away Win": "Away",
        },
    ),
    "BTTS": BetMapping(
        market_code="BTTS",
        bet_id=8,
        outcome_mapping={
            "Yes": "Yes",
            "No": "No",
        },
    ),
    "DC": BetMapping(
        market_code="DC",
        bet_id=12,
        outcome_mapping={
            "1X": "Home/Draw",
            "12": "Home/Away",
            "X2": "Draw/Away",
        },
    ),
    # Over/Under Goals (all use bet_id=5, different lines)
    "OU0.5": BetMapping(
        market_code="OU0.5",
        bet_id=5,
        outcome_mapping={"Over 0.5": "Over 0.5", "Under 0.5": "Under 0.5"},
        line=0.5,
    ),
    "OU1.5": BetMapping(
        market_code="OU1.5",
        bet_id=5,
        outcome_mapping={"Over 1.5": "Over 1.5", "Under 1.5": "Under 1.5"},
        line=1.5,
    ),
    "OU2.5": BetMapping(
        market_code="OU2.5",
        bet_id=5,
        outcome_mapping={"Over 2.5": "Over 2.5", "Under 2.5": "Under 2.5"},
        line=2.5,
    ),
    "OU3.5": BetMapping(
        market_code="OU3.5",
        bet_id=5,
        outcome_mapping={"Over 3.5": "Over 3.5", "Under 3.5": "Under 3.5"},
        line=3.5,
    ),
    "OU4.5": BetMapping(
        market_code="OU4.5",
        bet_id=5,
        outcome_mapping={"Over 4.5": "Over 4.5", "Under 4.5": "Under 4.5"},
        line=4.5,
    ),
    # -------------------------------------------------------------------------
    # Halftime Markets (5)
    # -------------------------------------------------------------------------
    "HT_1X2": BetMapping(
        market_code="HT_1X2",
        bet_id=13,
        outcome_mapping={
            "1HT": "Home",
            "XHT": "Draw",
            "2HT": "Away",
        },
    ),
    "HT_DC": BetMapping(
        market_code="HT_DC",
        bet_id=12,  # Uses Double Chance bet type with HT context
        outcome_mapping={
            "1X": "Home/Draw",
            "12": "Home/Away",
            "X2": "Draw/Away",
        },
    ),
    # HT Over/Under (use bet_id=6 for first half goals)
    "HT_OU0.5": BetMapping(
        market_code="HT_OU0.5",
        bet_id=6,
        outcome_mapping={"Over 0.5": "Over 0.5", "Under 0.5": "Under 0.5"},
        line=0.5,
    ),
    "HT_OU1.5": BetMapping(
        market_code="HT_OU1.5",
        bet_id=6,
        outcome_mapping={"Over 1.5": "Over 1.5", "Under 1.5": "Under 1.5"},
        line=1.5,
    ),
    "HT_OU2.5": BetMapping(
        market_code="HT_OU2.5",
        bet_id=6,
        outcome_mapping={"Over 2.5": "Over 2.5", "Under 2.5": "Under 2.5"},
        line=2.5,
    ),
    # -------------------------------------------------------------------------
    # 2nd Half Markets (4)
    # -------------------------------------------------------------------------
    "2H_DC": BetMapping(
        market_code="2H_DC",
        bet_id=12,  # Double Chance for 2nd half
        outcome_mapping={
            "1X": "Home/Draw",
            "12": "Home/Away",
            "X2": "Draw/Away",
        },
    ),
    "2H_OU0.5": BetMapping(
        market_code="2H_OU0.5",
        bet_id=5,  # Full match O/U (2H-specific not available)
        outcome_mapping={"Over 0.5": "Over 0.5", "Under 0.5": "Under 0.5"},
        line=0.5,
    ),
    "2H_OU1.5": BetMapping(
        market_code="2H_OU1.5",
        bet_id=5,
        outcome_mapping={"Over 1.5": "Over 1.5", "Under 1.5": "Under 1.5"},
        line=1.5,
    ),
    "2H_OU2.5": BetMapping(
        market_code="2H_OU2.5",
        bet_id=5,
        outcome_mapping={"Over 2.5": "Over 2.5", "Under 2.5": "Under 2.5"},
        line=2.5,
    ),
    # -------------------------------------------------------------------------
    # Team-Specific Markets (6)
    # -------------------------------------------------------------------------
    "HOME_SCORE": BetMapping(
        market_code="HOME_SCORE",
        bet_id=16,  # Total - Home
        outcome_mapping={
            "Yes": "Over 0.5",
            "No": "Under 0.5",
        },
        line=0.5,
    ),
    "AWAY_SCORE": BetMapping(
        market_code="AWAY_SCORE",
        bet_id=17,  # Total - Away
        outcome_mapping={
            "Yes": "Over 0.5",
            "No": "Under 0.5",
        },
        line=0.5,
    ),
    "HOME_TO_SCORE": BetMapping(
        market_code="HOME_TO_SCORE",
        bet_id=16,
        outcome_mapping={
            "Yes": "Over 0.5",
            "No": "Under 0.5",
        },
        line=0.5,
    ),
    "AWAY_TO_SCORE": BetMapping(
        market_code="AWAY_TO_SCORE",
        bet_id=17,
        outcome_mapping={
            "Yes": "Over 0.5",
            "No": "Under 0.5",
        },
        line=0.5,
    ),
    "HOME_WIN_HALF": BetMapping(
        market_code="HOME_WIN_HALF",
        bet_id=1,  # Use 1X2 as proxy
        outcome_mapping={
            "Yes": "Home",
            "No": "Away",
        },
    ),
    "AWAY_WIN_HALF": BetMapping(
        market_code="AWAY_WIN_HALF",
        bet_id=1,
        outcome_mapping={
            "Yes": "Away",
            "No": "Home",
        },
    ),
    # -------------------------------------------------------------------------
    # HT/FT Market (1)
    # -------------------------------------------------------------------------
    "HT/FT": BetMapping(
        market_code="HT/FT",
        bet_id=7,  # HT/FT Double
        outcome_mapping={
            "1/1": "Home/Home",
            "1/X": "Home/Draw",
            "1/2": "Home/Away",
            "X/1": "Draw/Home",
            "X/X": "Draw/Draw",
            "X/2": "Draw/Away",
            "2/1": "Away/Home",
            "2/X": "Away/Draw",
            "2/2": "Away/Away",
        },
    ),
    # -------------------------------------------------------------------------
    # Combination Markets - these may not have direct API odds
    # Fall back to component market odds
    # -------------------------------------------------------------------------
    "1X2_OU1.5": BetMapping(
        market_code="1X2_OU1.5",
        bet_id=1,  # Use 1X2 odds as base
        outcome_mapping={
            "1&Over": "Home",
            "1&Under": "Home",
            "X&Over": "Draw",
            "X&Under": "Draw",
            "2&Over": "Away",
            "2&Under": "Away",
        },
    ),
    "1X2_OU2.5": BetMapping(
        market_code="1X2_OU2.5",
        bet_id=1,
        outcome_mapping={
            "1&Over": "Home",
            "1&Under": "Home",
            "X&Over": "Draw",
            "X&Under": "Draw",
            "2&Over": "Away",
            "2&Under": "Away",
        },
    ),
    "1X2_BTTS": BetMapping(
        market_code="1X2_BTTS",
        bet_id=1,
        outcome_mapping={
            "1&GG": "Home",
            "1&NG": "Home",
            "X&GG": "Draw",
            "X&NG": "Draw",
            "2&GG": "Away",
            "2&NG": "Away",
        },
    ),
    # -------------------------------------------------------------------------
    # Chance Mix Markets (OR logic) - use component odds
    # -------------------------------------------------------------------------
    "CHANCEMIX_1X2_OU15": BetMapping(
        market_code="CHANCEMIX_1X2_OU15",
        bet_id=1,
        outcome_mapping={
            "1orOver": "Home",
            "XorOver": "Draw",
            "2orOver": "Away",
            "1orUnder": "Home",
            "XorUnder": "Draw",
            "2orUnder": "Away",
        },
    ),
    "CHANCEMIX_1X2_OU25": BetMapping(
        market_code="CHANCEMIX_1X2_OU25",
        bet_id=1,
        outcome_mapping={
            "1orOver": "Home",
            "XorOver": "Draw",
            "2orOver": "Away",
            "1orUnder": "Home",
            "XorUnder": "Draw",
            "2orUnder": "Away",
        },
    ),
    "CHANCEMIX_1X2_OU35": BetMapping(
        market_code="CHANCEMIX_1X2_OU35",
        bet_id=1,
        outcome_mapping={
            "1orOver": "Home",
            "XorOver": "Draw",
            "2orOver": "Away",
            "1orUnder": "Home",
            "XorUnder": "Draw",
            "2orUnder": "Away",
        },
    ),
    # -------------------------------------------------------------------------
    # Advanced Markets (1)
    # -------------------------------------------------------------------------
    "MULTI_GOAL": BetMapping(
        market_code="MULTI_GOAL",
        bet_id=5,  # Use O/U as proxy
        outcome_mapping={
            "0-1 goals": "Under 1.5",
            "2-3 goals": "Over 1.5",
            "4-5 goals": "Over 3.5",
            "6+ goals": "Over 5.5",
        },
        line=2.5,
    ),
}


def get_bet_mapping(market_code: str) -> BetMapping | None:
    """Get bet mapping for a market code.

    Args:
        market_code: SIPAP market code (e.g., "1X2", "BTTS", "OU2.5")

    Returns:
        BetMapping instance or None if not found
    """
    return MARKET_TO_BET_ID.get(market_code)


def get_supported_markets() -> list[str]:
    """Get list of all supported market codes.

    Returns:
        List of market code strings
    """
    return list(MARKET_TO_BET_ID.keys())


def has_direct_odds(market_code: str) -> bool:
    """Check if a market has direct odds available from API-Football.

    Some markets (like combination markets) don't have direct odds
    and need to be calculated from component markets.

    Args:
        market_code: SIPAP market code

    Returns:
        True if direct odds available, False otherwise
    """
    # These markets have direct odds from bookmakers
    direct_odds_markets = {
        "1X2", "DNB", "BTTS", "DC",
        "OU0.5", "OU1.5", "OU2.5", "OU3.5", "OU4.5",
        "HT_1X2", "HT_OU0.5", "HT_OU1.5",
        "HT/FT",
    }
    return market_code in direct_odds_markets


# ============================================================================
# API-Football Bet ID Reference
# ============================================================================

API_FOOTBALL_BET_IDS: dict[int, str] = {
    1: "Match Winner",
    2: "Home/Away",
    3: "Second Half Winner",
    4: "Asian Handicap",
    5: "Goals Over/Under",
    6: "Goals Over/Under First Half",
    7: "HT/FT Double",
    8: "Both Teams Score",
    9: "Exact Score",
    10: "Draw No Bet",
    11: "Winning Margin",
    12: "Double Chance",
    13: "First Half Winner",
    14: "Team To Score First",
    15: "Team To Score Last",
    16: "Total - Home",
    17: "Total - Away",
    18: "Handicap Result",
    19: "Correct Score - First Half",
    20: "Team To Score in Both Halves",
    21: "Clean Sheet - Home",
    22: "Clean Sheet - Away",
    23: "Win To Nil - Home",
    24: "Win To Nil - Away",
    25: "Correct Score - Second Half",
    26: "Win Either Half - Home",
    27: "Win Either Half - Away",
    28: "Exact Goals Number",
    29: "Score/No Score",
    30: "First/Last Goal",
    31: "Home Team Score a Goal",
    32: "Away Team Score a Goal",
    33: "Corners Over/Under",
    34: "Cards Over/Under",
    35: "Both Teams Score - First Half",
    36: "Both Teams Score - Second Half",
    37: "Home Team Goals Over/Under - First Half",
    38: "Away Team Goals Over/Under - First Half",
    39: "Odd/Even",
    40: "Home Win - Both Teams Score",
    # ... additional bet types
}
