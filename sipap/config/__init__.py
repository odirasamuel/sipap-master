"""SIPAP Configuration Module.

Re-exports configuration from sipap-common for backwards compatibility.

IMPORTANT: Do NOT create duplicate files here. All league mappings, country data,
and sports configuration should live in sipap-common and be imported here.
"""

# Import from sipap-common (single source of truth)
from sipap_common.data import (
    COUNTRY_TO_LEAGUES,
    COUNTRY_VARIANTS,
    LEAGUE_ALIASES,
    PARTIAL_MATCH_PATTERNS,
    extract_country_from_query,
    find_league_matches,
    find_similar_leagues,
    get_leagues_for_country,
    resolve_league_alias,
)

__all__ = [
    "COUNTRY_TO_LEAGUES",
    "COUNTRY_VARIANTS",
    "LEAGUE_ALIASES",
    "PARTIAL_MATCH_PATTERNS",
    "extract_country_from_query",
    "find_league_matches",
    "find_similar_leagues",
    "get_leagues_for_country",
    "resolve_league_alias",
]
