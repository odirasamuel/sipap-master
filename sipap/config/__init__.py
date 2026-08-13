"""SIPAP Configuration Module.

Contains configuration files for:
- League and competition mappings (380 competitions)
- Country-to-leagues mappings
- Competition name aliases and variations
"""

from sipap.config.league_mappings import (
    COUNTRY_TO_LEAGUES,
    LEAGUE_ALIASES,
    PARTIAL_MATCH_PATTERNS,
    find_league_matches,
    get_leagues_for_country,
    resolve_league_alias,
)

__all__ = [
    "COUNTRY_TO_LEAGUES",
    "LEAGUE_ALIASES",
    "PARTIAL_MATCH_PATTERNS",
    "find_league_matches",
    "get_leagues_for_country",
    "resolve_league_alias",
]
