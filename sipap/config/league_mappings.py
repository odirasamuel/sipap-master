"""League and Competition Mappings Configuration.

Comprehensive mappings for 380 competitions covering:
- Country-to-leagues mapping
- Competition name aliases and variations
- Partial name matching

Used by orchestrator for interpreting user queries like:
- "Romania matches" → Liga I, Liga II, Cupa României, Supercupa
- "Europa League" → UEFA Europa League
- "EPL" → Premier League
- "Cupa României" → Cupa României (Romania Cup)
"""

# Country to leagues mapping (all countries with their competitions)
COUNTRY_TO_LEAGUES: dict[str, list[str]] = {
    # A
    "albania": ["Superliga", "Super Cup", "Cup"],
    "algeria": ["Ligue 1", "Ligue 2", "Super Cup", "Coupe de la Ligue", "Coupe Nationale"],
    "andorra": ["1a Divisió", "2a Divisió"],
    "argentina": [
        "Liga Profesional Argentina",
        "Copa de la Liga Profesional",
        "Copa de la Superliga",
        "Copa Argentina",
        "Primera Nacional",
    ],
    "armenia": ["Premier League", "Super Cup", "Cup"],
    "australia": ["A-League"],
    "austria": ["Bundesliga", "2. Liga", "Cup"],
    "azerbaijan": ["Premyer Liqa", "Cup"],

    # B
    "belarus": ["Premier League", "1. Division", "Coppa", "Super Cup"],
    "belgium": ["Jupiler Pro League", "Challenger Pro League", "Cup", "Super Cup"],
    "bolivia": ["Primera División", "Copa de la División Profesional"],
    "bosnia": ["Premijer Liga", "Cup", "Super Cup"],
    "brazil": [
        "Serie A",
        "Serie B",
        "Serie C",
        "Serie D",
        "Supercopa do Brasil",
        "Copa Do Brasil",
    ],
    "bulgaria": ["First League", "Second League", "Cup", "Super Cup"],

    # C
    "canada": ["Canadian Premier League", "Canadian Championship"],
    "chile": [
        "Primera División",
        "Segunda División",
        "Primera B",
        "Copa De La Liga",
        "Copa Chile",
        "Super Cup",
    ],
    "china": ["Super League", "League One", "League Two", "FA Cup", "Super Cup"],
    "colombia": ["Superliga", "Primera A", "Primera B", "Copa Colombia"],
    "costa-rica": ["Primera División", "Copa Costa Rica", "Supercopa"],
    "costa rica": ["Primera División", "Copa Costa Rica", "Supercopa"],
    "croatia": ["HNL", "First NL", "Cup", "Super Cup"],
    "cyprus": ["1. Division", "2. Division", "Cup", "Super Cup"],
    "czech-republic": ["Czech Liga", "FNL", "Cup", "Super Cup"],
    "czech republic": ["Czech Liga", "FNL", "Cup", "Super Cup"],
    "czechia": ["Czech Liga", "FNL", "Cup", "Super Cup"],

    # D
    "denmark": ["Superliga", "1. Division", "DBU Pokalen"],

    # E
    "ecuador": ["Liga Pro", "Liga Pro Serie B", "Copa Ecuador"],
    "egypt": ["Premier League", "Second League", "League Cup", "Cup"],
    "england": [
        "Premier League",
        "Championship",
        "League One",
        "League Two",
        "National League",
        "National League - North",
        "National League - South",
        "Women's Championship",
        "WSL Cup",
        "EFL Trophy",
        "FA Cup",
        "FA Trophy",
        "FA WSL",
        "League Cup",
        "National League Cup",
        "Community Shield",
        "Community Shield Women",
    ],
    "estonia": ["Meistriliiga", "Esiliiga A", "Cup"],

    # F
    "finland": ["Veikkausliiga", "Ykkösliiga", "Suomen Cup", "League Cup"],
    "france": [
        "Ligue 1",
        "Ligue 2",
        "National 1",
        "Coupe de France",
        "Coupe de la Ligue",
        "Feminine Division 1",
        "Trophée des Champions",
    ],

    # G
    "georgia": ["Erovnuli Liga", "Erovnuli Liga 2", "David Kipiani Cup", "Super Cup"],
    "germany": [
        "Bundesliga",
        "2. Bundesliga",
        "3. Liga",
        "DFB Pokal",
        "Super Cup",
        "Frauen Bundesliga",
        "DFB Pokal - Women",
    ],
    "greece": ["Super League 1", "Super League 2", "Super Cup", "Cup"],

    # H
    "honduras": ["Liga Nacional"],
    "hungary": ["NB I", "NB II", "Magyar Kupa"],

    # I
    "iceland": ["1. Deild", "2. Deild", "Cup", "League Cup", "Super Cup"],
    "indonesia": ["Liga 1", "Liga 2"],
    "iran": ["Persian Gulf Pro League", "Azadegan League", "Hazfi Cup", "Super Cup"],
    "ireland": [
        "Premier Division",
        "First Division",
        "League Cup",
        "FAI President's Cup",
        "FAI Cup",
    ],
    "israel": ["Ligat Ha'al", "Liga Leumit", "State Cup", "Super Cup"],
    "italy": [
        "Serie A",
        "Serie B",
        "Serie C - Girone A",
        "Serie C - Girone B",
        "Serie C - Girone C",
        "Coppa Italia",
        "Super Cup",
        "Serie A Women",
        "Serie A Cup Women",
        "Coppa Italia Women",
    ],

    # J
    "japan": ["J1 League", "J2 League", "J-League Cup", "Emperor Cup", "Super Cup"],

    # K
    "kazakhstan": ["Premier League", "1. Division", "Cup", "Super Cup"],
    "kuwait": ["Premier League", "Crown Prince Cup", "Emir Cup", "Super Cup"],

    # L
    "lithuania": ["A Lyga", "1 Lyga", "Cup", "Super Cup"],

    # M
    "malaysia": ["Super League", "Premier League", "Malaysia Cup", "FA Cup"],
    "mexico": ["Liga MX", "Copa por México", "Copa MX", "Campeón de Campeones"],
    "moldova": ["Super Liga", "Cupa"],
    "morocco": ["Botola Pro", "Botola 2", "Cup"],

    # N
    "netherlands": [
        "Eredivisie",
        "Eerste Divisie",
        "KNVB Beker",
        "Super Cup",
        "Eredivisie Women",
        "Super Cup Women",
    ],
    "northern-ireland": ["Premiership", "Championship", "Irish Cup", "League Cup"],
    "northern ireland": ["Premiership", "Championship", "Irish Cup", "League Cup"],
    "norway": ["Eliteserien", "1. Division", "NM Cupen", "Super Cup"],

    # P
    "paraguay": [
        "Division Profesional - Clausura",
        "Division Profesional - Apertura",
        "Copa Paraguay",
        "Supercopa",
    ],
    "peru": [
        "Primera División",
        "Segunda División",
        "Supercopa",
        "Copa De La Liga",
        "Copa Perú",
    ],
    "poland": ["Ekstraklasa", "I Liga", "Cup", "Super Cup"],
    "portugal": [
        "Primeira Liga",
        "Segunda Liga",
        "Taça da Liga",
        "Taça de Portugal",
        "Super Cup",
    ],

    # Q
    "qatar": [
        "Stars League",
        "Second Division",
        "Qatar Cup",
        "QSL Cup",
        "Emir Cup",
        "QFA Cup",
    ],

    # R
    "romania": ["Liga I", "Liga II", "Cupa României", "Supercupa"],
    "russia": ["Premier League", "First League", "Cup", "Super Cup"],

    # S
    "saudi-arabia": [
        "Pro League",
        "Division 1",
        "Crown Prince Cup",
        "Super Cup",
        "King's Cup",
    ],
    "saudi arabia": [
        "Pro League",
        "Division 1",
        "Crown Prince Cup",
        "Super Cup",
        "King's Cup",
    ],
    "scotland": [
        "Premiership",
        "Championship",
        "League One",
        "League Two",
        "FA Cup",
        "League Cup",
        "Challenge Cup",
    ],
    "serbia": ["Super Liga", "Prva Liga", "Cup"],
    "slovakia": ["Super Liga", "2. liga", "Cup"],
    "slovenia": ["1. SNL", "2. SNL", "Cup"],
    "south-africa": ["Premier Soccer League", "League Cup", "8 Cup"],
    "south africa": ["Premier Soccer League", "League Cup", "8 Cup"],
    "south-korea": ["K League 1", "K League 2", "FA Cup"],
    "south korea": ["K League 1", "K League 2", "FA Cup"],
    "korea": ["K League 1", "K League 2", "FA Cup"],
    "spain": [
        "La Liga",
        "Segunda División",
        "Primera División Femenina",
        "Copa del Rey",
        "Super Cup",
        "Supercopa Femenina",
    ],
    "sweden": ["Allsvenskan", "Superettan", "Svenska Cupen"],
    "switzerland": ["Super League", "Challenge League", "Schweizer Cup"],

    # T
    "thailand": ["Thai League 1", "FA Cup", "League Cup"],
    "tunisia": ["Ligue 1", "Ligue 2", "Super Cup", "Cup"],
    "turkey": ["Süper Lig", "1. Lig", "Türkiye Kupası", "Super Cup"],

    # U
    "usa": ["Major League Soccer"],
    "united states": ["Major League Soccer"],
    "ukraine": ["Premier League", "Persha Liga", "Cup", "Super Cup"],
    "united-arab-emirates": ["Pro League", "League Cup", "Super Cup"],
    "united arab emirates": ["Pro League", "League Cup", "Super Cup"],
    "uae": ["Pro League", "League Cup", "Super Cup"],
    "uruguay": [
        "Primera División - Clausura",
        "Primera División - Apertura",
        "Segunda División",
        "Copa Uruguay",
        "Super Copa",
    ],

    # V
    "venezuela": ["Primera División", "Segunda División", "Copa Venezuela", "Supercopa"],

    # W
    "wales": ["Premier League", "League Cup", "Welsh Cup"],
}

# Competition name aliases and variations
# Maps common abbreviations/variations to canonical competition names
LEAGUE_ALIASES: dict[str, str] = {
    # English Premier League
    "epl": "Premier League",
    "premier league": "Premier League",
    "english premier league": "Premier League",
    "pl": "Premier League",

    # Spanish La Liga
    "laliga": "La Liga",
    "la liga": "La Liga",
    "spanish la liga": "La Liga",
    "primera division": "La Liga",

    # German Bundesliga
    "bundesliga": "Bundesliga",
    "german bundesliga": "Bundesliga",
    "buli": "Bundesliga",

    # Italian Serie A
    "serie a": "Serie A",
    "italian serie a": "Serie A",
    "serie b": "Serie B",

    # French Ligue 1
    "ligue 1": "Ligue 1",
    "ligue 2": "Ligue 2",
    "french ligue 1": "Ligue 1",
    "l1": "Ligue 1",

    # UEFA Competitions
    "champions league": "UEFA Champions League",
    "ucl": "UEFA Champions League",
    "uefa champions league": "UEFA Champions League",
    "europa league": "UEFA Europa League",
    "uel": "UEFA Europa League",
    "uefa europa league": "UEFA Europa League",
    "conference league": "UEFA Europa Conference League",
    "uecl": "UEFA Europa Conference League",
    "uefa europa conference league": "UEFA Europa Conference League",
    "uefa conference league": "UEFA Europa Conference League",
    "nations league": "UEFA Nations League",
    "uefa nations league": "UEFA Nations League",
    "super cup": "UEFA Super Cup",
    "uefa super cup": "UEFA Super Cup",

    # International Tournaments
    "world cup": "World Cup",
    "euro": "Euro Championship",
    "euros": "Euro Championship",
    "euro championship": "Euro Championship",
    "european championship": "Euro Championship",
    "copa america": "Copa America",
    "afcon": "Africa Cup of Nations",
    "africa cup": "Africa Cup of Nations",
    "asian cup": "Asian Cup",
    "gold cup": "CONCACAF Gold Cup",
    "concacaf gold cup": "CONCACAF Gold Cup",

    # South American Competitions
    "libertadores": "CONMEBOL Libertadores",
    "copa libertadores": "CONMEBOL Libertadores",
    "sudamericana": "CONMEBOL Sudamericana",
    "copa sudamericana": "CONMEBOL Sudamericana",

    # National Cups
    "fa cup": "FA Cup",
    "english fa cup": "FA Cup",
    "coupe de france": "Coupe de France",
    "french cup": "Coupe de France",
    "copa del rey": "Copa del Rey",
    "spanish cup": "Copa del Rey",
    "coppa italia": "Coppa Italia",
    "italian cup": "Coppa Italia",
    "dfb pokal": "DFB Pokal",
    "german cup": "DFB Pokal",
    "romania cup": "Cupa României",
    "romanian cup": "Cupa României",
    "cupa romaniei": "Cupa României",
    "cupa româniei": "Cupa României",
    "turkish cup": "Türkiye Kupası",
    "turkiye kupasi": "Türkiye Kupası",
    "turkey cup": "Türkiye Kupası",
    "egyptian cup": "Cup",  # Egypt
    "belgian cup": "Cup",  # Belgium
    "croatian cup": "Cup",  # Croatia

    # Other Leagues
    "eredivisie": "Eredivisie",
    "dutch league": "Eredivisie",
    "portuguese liga": "Primeira Liga",
    "liga nos": "Primeira Liga",
    "primeira liga": "Primeira Liga",
    "scottish premiership": "Premiership",
    "spfl": "Premiership",
    "mls": "Major League Soccer",
    "liga mx": "Liga MX",
    "mexican league": "Liga MX",
    "j-league": "J1 League",
    "j league": "J1 League",
    "j1": "J1 League",
    "j2": "J2 League",
    "k-league": "K League 1",
    "k league": "K League 1",
    "brazilian serie a": "Serie A",
    "campeonato brasileiro": "Serie A",
    "argentinian primera": "Liga Profesional Argentina",
    "superliga argentina": "Liga Profesional Argentina",
}

# Partial name matching patterns (case-insensitive)
# Used for fuzzy matching when user mentions part of competition name
PARTIAL_MATCH_PATTERNS: dict[str, str] = {
    "europa": "UEFA Europa League",
    "conference": "UEFA Europa Conference League",
    "champions": "UEFA Champions League",
    "nations": "UEFA Nations League",
    "libertadores": "CONMEBOL Libertadores",
    "sudamericana": "CONMEBOL Sudamericana",
    "romania": "Cupa României",  # Handles "Romania Cup" → Cupa României
    "turkish": "Türkiye Kupası",
    "magyar": "Magyar Kupa",
}


def get_leagues_for_country(country_name: str) -> list[str]:
    """Get all leagues/competitions for a country.

    Args:
        country_name: Country name (case-insensitive)

    Returns:
        List of league names for that country

    Example:
        >>> get_leagues_for_country("romania")
        ['Liga I', 'Liga II', 'Cupa României', 'Supercupa']
    """
    country_lower = country_name.lower()
    return COUNTRY_TO_LEAGUES.get(country_lower, [])


def resolve_league_alias(league_query: str) -> str:
    """Resolve league alias/abbreviation to canonical name.

    Args:
        league_query: User's league query (e.g., "EPL", "Europa League")

    Returns:
        Canonical league name, or original query if no match

    Example:
        >>> resolve_league_alias("EPL")
        'Premier League'
        >>> resolve_league_alias("Europa League")
        'UEFA Europa League'
    """
    query_lower = league_query.lower()

    # Exact match in aliases
    if query_lower in LEAGUE_ALIASES:
        return LEAGUE_ALIASES[query_lower]

    # Partial match patterns
    for pattern, canonical_name in PARTIAL_MATCH_PATTERNS.items():
        if pattern in query_lower:
            return canonical_name

    # No match - return original
    return league_query


def find_league_matches(query: str) -> list[str]:
    """Find all possible league matches from user query.

    Checks (in order):
    1. League aliases (e.g., "EPL" → "Premier League")
    2. Country mentions (e.g., "romania" → all Romanian leagues)
    3. Direct competition name mentions (e.g., "Cupa României" matches itself)
    4. Partial matches (e.g., "europa" → "UEFA Europa League")

    Args:
        query: User's query string

    Returns:
        List of matched league names (deduplicated)

    Example:
        >>> find_league_matches("romania matches today")
        ['Liga I', 'Liga II', 'Cupa României', 'Supercupa']
        >>> find_league_matches("europa league fixtures")
        ['UEFA Europa League']
        >>> find_league_matches("EPL results")
        ['Premier League']
        >>> find_league_matches("Cupa României results")
        ['Cupa României']
    """
    query_lower = query.lower()
    matched_leagues = []

    # 1. Check league aliases FIRST (e.g., "EPL" → "Premier League", "romanian cup" → "Cupa României")
    # This allows specific competition aliases to take priority over country mentions
    # Sort aliases by length (longest first) to match most specific first
    sorted_aliases = sorted(LEAGUE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True)

    for alias, canonical in sorted_aliases:
        if alias in query_lower and canonical not in matched_leagues:
            matched_leagues.append(canonical)
            # For multi-word aliases or long aliases, return immediately to avoid partial matches
            # e.g., "europa league" should not also match "euro"
            if " " in alias or len(alias) > 6:
                return matched_leagues

    if matched_leagues:
        return matched_leagues  # Return if alias matches found

    # 2. Check country mentions (e.g., "romania" → all Romanian competitions)
    # Use word boundary matching to avoid "romanian" matching "romania"
    import re
    for country, leagues in COUNTRY_TO_LEAGUES.items():
        # Match country as whole word (with word boundaries)
        if re.search(rf'\b{re.escape(country)}\b', query_lower):
            matched_leagues.extend(leagues)
            return matched_leagues  # Return country leagues

    # 3. Check direct competition name mentions (exact or near-exact match)
    # Build list of all competition names from all countries
    all_competitions = set()
    for leagues in COUNTRY_TO_LEAGUES.values():
        all_competitions.update(leagues)

    # Sort by length (longest first) to match most specific names first
    # This prevents "Cup" from matching before "Cupa României"
    sorted_competitions = sorted(all_competitions, key=len, reverse=True)

    for competition in sorted_competitions:
        comp_lower = competition.lower()
        # Match if competition name appears as substring
        # This allows "cupa româniei results" to match "Cupa României"
        if comp_lower in query_lower and competition not in matched_leagues:
            matched_leagues.append(competition)
            # Only take the first (longest) match to avoid multiple Cup matches
            break

    return matched_leagues
