# Data MCP Tools Reference

**Last Updated:** 2026-08-19
**Lambda Function:** `SipapDataMcpServer`
**API Source:** API-Football (v3.football.api-sports.io)

This document provides the request/response schema for all Data MCP tools. Use this as a reference when the orchestrator calls these tools.

---

## Table of Contents

1. [Match/Fixture Tools](#matchfixture-tools)
   - [get_match_schedule](#get_match_schedule)
   - [get_match_details](#get_match_details)
   - [get_live_matches](#get_live_matches)
   - [search_fixtures](#search_fixtures)
   - [search_matches](#search_matches)
2. [Team Tools](#team-tools)
3. [Historical Tools](#historical-tools)
4. [Odds Tools](#odds-tools)
5. [Form Pattern Tools](#form-pattern-tools)
6. [Statistical Analysis Tools](#statistical-analysis-tools)

---

## Match/Fixture Tools

### get_match_schedule

Get scheduled matches for a date range, optionally filtered by league.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_match_schedule",
    "arguments": {
      "date_from": "2026-08-20",
      "date_to": "2026-08-20",
      "league_id": 140,
      "status": "scheduled"
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `date_from` | string | Yes | - | Start date (YYYY-MM-DD) |
| `date_to` | string | Yes | - | End date (YYYY-MM-DD) |
| `league_id` | integer | No | null | API-Football league ID (e.g., 140 for La Liga) |
| `status` | string | No | "scheduled" | Match status: "scheduled", "live", "finished" |

#### Response

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"matches\": [...]}"
      }
    ]
  }
}
```

**Parsed `text` content:**

```json
{
  "matches": [
    {
      "id": "1570351",
      "external_id": "1570351",
      "scheduled_at": "2026-08-20T19:00:00+00:00",
      "status": "NS",
      "home_team": "Rayo Vallecano",
      "away_team": "Alaves",
      "home_team_id": 728,
      "away_team_id": 542,
      "league": "La Liga",
      "league_id": 140,
      "home_score": null,
      "away_score": null,
      "ht_home_score": null,
      "ht_away_score": null,
      "metadata": {
        "venue": "Estadio Municipal de Butarque",
        "referee": null,
        "league_country": "Spain",
        "league_logo": "https://media.api-sports.io/football/leagues/140.png",
        "league_round": "Regular Season - 2",
        "home_team_logo": "https://media.api-sports.io/football/teams/728.png",
        "away_team_logo": "https://media.api-sports.io/football/teams/542.png"
      }
    }
  ]
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"get_match_schedule","arguments":{"date_from":"2026-08-20","date_to":"2026-08-20","league_id":140}}}' \
  /tmp/response.json

# Result: Found Rayo Vallecano vs Alaves (fixture ID: 1570351)
```

---

### get_match_details

Get detailed information for a specific match by fixture ID.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_match_details",
    "arguments": {
      "match_id": "1547765"
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `match_id` | string | Yes | - | API-Football fixture ID (as string) |

#### Response

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"match\": {...}}"
      }
    ]
  }
}
```

**Parsed `text` content:**

```json
{
  "match": {
    "id": "1547765",
    "external_id": "1547765",
    "scheduled_at": "2026-08-19T22:00:00+00:00",
    "status": "2H",
    "home_team": "Cerro Porteno",
    "away_team": "Palmeiras",
    "home_team_id": 1176,
    "away_team_id": 121,
    "league": "CONMEBOL Libertadores",
    "league_id": 13,
    "home_score": 0,
    "away_score": 1,
    "ht_home_score": 0,
    "ht_away_score": 1,
    "metadata": {
      "venue": "General Pablo Rojas",
      "referee": "Facundo Raul Tello Figueroa, Argentina",
      "league_country": "World",
      "league_logo": "https://media.api-sports.io/football/leagues/13.png",
      "league_round": "Round of 16",
      "home_team_logo": "https://media.api-sports.io/football/teams/1176.png",
      "away_team_logo": "https://media.api-sports.io/football/teams/121.png"
    }
  }
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"get_match_details","arguments":{"match_id":"1547765"}}}' \
  /tmp/response.json

# Result: Returned full match details for Cerro Porteno vs Palmeiras
```

---

### get_live_matches

Get all currently live matches across all leagues.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_live_matches",
    "arguments": {}
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| (none) | - | - | - | No parameters required |

#### Response

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"matches\": [...]}"
      }
    ]
  }
}
```

**Parsed `text` content:**

```json
{
  "matches": [
    {
      "id": "1508511",
      "external_id": "1508511",
      "scheduled_at": "2026-08-19T22:30:00+00:00",
      "status": "1H",
      "home_team": "Racing Louisville W",
      "away_team": "Seattle Reign FC W",
      "home_team_id": 16488,
      "away_team_id": 3002,
      "league": "NWSL Women",
      "league_id": 254,
      "home_score": 0,
      "away_score": 1,
      "ht_home_score": 0,
      "ht_away_score": 1,
      "metadata": {
        "venue": "Lynn Family Stadium",
        "referee": null,
        "league_country": "USA",
        "league_logo": "https://media.api-sports.io/football/leagues/254.png",
        "league_round": "Group Stage",
        "home_team_logo": "https://media.api-sports.io/football/teams/16488.png",
        "away_team_logo": "https://media.api-sports.io/football/teams/3002.png"
      }
    }
    // ... more live matches
  ]
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"get_live_matches","arguments":{}}}' \
  /tmp/response.json

# Result: Returned 16 live matches from various leagues (NWSL, MLS Next Pro, Serie B Brazil, etc.)
```

---

### search_fixtures

Search for fixtures with flexible filtering by league, date, and status.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "search_fixtures",
    "arguments": {
      "league_ids": [140],
      "date_from": "2026-08-20",
      "date_to": "2026-08-20",
      "status": "scheduled",
      "limit": 100
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `league_ids` | array[int] | No | null | List of API-Football league IDs |
| `league_names` | array[string] | No | null | List of league names (alternative to IDs) |
| `date_from` | string | No | today | Start date (YYYY-MM-DD) |
| `date_to` | string | No | +7 days | End date (YYYY-MM-DD) |
| `status` | string | No | "scheduled" | Match status: "scheduled", "live", "finished" |
| `has_odds` | boolean | No | true | Filter for matches with odds |
| `limit` | integer | No | 100 | Maximum fixtures to return |

#### Response

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"fixtures\": [...], \"count\": 1, \"filters_applied\": {...}}"
      }
    ]
  }
}
```

**Parsed `text` content:**

```json
{
  "fixtures": [
    {
      "id": "1570351",
      "external_id": "1570351",
      "scheduled_at": "2026-08-20T19:00:00+00:00",
      "status": "NS",
      "home_team": "Rayo Vallecano",
      "away_team": "Alaves",
      "home_team_id": 728,
      "away_team_id": 542,
      "league": "La Liga",
      "league_id": 140,
      "home_score": null,
      "away_score": null,
      "ht_home_score": null,
      "ht_away_score": null,
      "metadata": {
        "venue": "Estadio Municipal de Butarque",
        "referee": null,
        "league_country": "Spain",
        "league_logo": "https://media.api-sports.io/football/leagues/140.png",
        "league_round": "Regular Season - 2",
        "home_team_logo": "https://media.api-sports.io/football/teams/728.png",
        "away_team_logo": "https://media.api-sports.io/football/teams/542.png"
      }
    }
  ],
  "count": 1,
  "filters_applied": {
    "league_ids": [140],
    "date_from": "2026-08-20",
    "date_to": "2026-08-20",
    "status": "scheduled",
    "limit": 100,
    "source": "api_football"
  }
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"search_fixtures","arguments":{"league_ids":[140],"date_from":"2026-08-20","date_to":"2026-08-20"}}}' \
  /tmp/response.json

# Result: Found 1 fixture (Rayo Vallecano vs Alaves)
```

---

### search_matches

Search for matches by team name. Returns last 15 **completed** fixtures across all competitions (league, cup, friendlies, pre-season).

**Status:** ✅ WORKING (Tested 2026-08-19)

> **Note:** This tool returns completed (past) fixtures only. Use `search_fixtures` or `get_match_schedule` for upcoming matches.

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "search_matches",
    "arguments": {
      "query": "Rayo Vallecano"
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Team name to search for |

#### Response

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"matches\": [...], \"team_found\": true, \"team_id\": 728, \"team_name\": \"Rayo Vallecano\"}"
      }
    ]
  }
}
```

**Parsed `text` content:**

```json
{
  "matches": [
    {
      "id": "1570341",
      "external_id": "1570341",
      "scheduled_at": "2026-08-15T19:30:00+00:00",
      "status": "FT",
      "home_team": "Sevilla",
      "away_team": "Rayo Vallecano",
      "home_team_id": 536,
      "away_team_id": 728,
      "league": "La Liga",
      "league_id": 140,
      "home_score": 2,
      "away_score": 1,
      "ht_home_score": 0,
      "ht_away_score": 1,
      "metadata": {
        "venue": "Ramón Sánchez Pizjuán",
        "referee": "Ricardo De Burgos Bengoetxea, Spain",
        "league_country": "Spain",
        "league_logo": "https://media.api-sports.io/football/leagues/140.png",
        "league_round": "Regular Season - 1",
        "home_team_logo": "https://media.api-sports.io/football/teams/536.png",
        "away_team_logo": "https://media.api-sports.io/football/teams/728.png"
      }
    }
    // ... up to 15 completed fixtures
  ],
  "team_found": true,
  "team_id": 728,
  "team_name": "Rayo Vallecano"
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"search_matches","arguments":{"query":"Rayo Vallecano"}}}' \
  /tmp/response.json

# Result: 15 completed fixtures including:
# - La Liga 2026-27: Sevilla 2-1 Rayo (Aug 15)
# - Friendlies: vs Ipswich, Charleroi, Feyenoord, Hearts
# - Conference League Final: Crystal Palace 1-0 Rayo (May 27)
# - La Liga 2025-26: Multiple matches (rounds 32-38)
# - Previous H2H: Alaves 1-2 Rayo Vallecano (May 23)
```

---

## Common League IDs (API-Football)

| League | ID | Country |
|--------|-----|---------|
| La Liga | 140 | Spain |
| Premier League | 39 | England |
| Serie A | 135 | Italy |
| Bundesliga | 78 | Germany |
| Ligue 1 | 61 | France |
| Eredivisie | 88 | Netherlands |
| Primeira Liga | 94 | Portugal |
| Champions League | 2 | Europe |
| Europa League | 3 | Europe |
| CONMEBOL Libertadores | 13 | South America |

---

## Team Tools

### get_head_to_head

Get head-to-head statistics and match history between two teams.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_head_to_head",
    "arguments": {
      "home_team_id": 728,
      "away_team_id": 542
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `home_team_id` | integer | Yes | - | API-Football team ID for home team |
| `away_team_id` | integer | Yes | - | API-Football team ID for away team |

#### Response

```json
{
  "head_to_head": [
    {
      "id": "1391189",
      "external_id": "1391189",
      "scheduled_at": "2026-05-23T19:00:00+00:00",
      "status": "FT",
      "home_team": "Alaves",
      "away_team": "Rayo Vallecano",
      "home_team_id": 542,
      "away_team_id": 728,
      "league": "La Liga",
      "league_id": 140,
      "home_score": 1,
      "away_score": 2,
      "ht_home_score": 1,
      "ht_away_score": 0,
      "metadata": {
        "venue": "Estadio Mendizorrotza",
        "referee": "J. Manzano",
        "league_country": "Spain",
        "league_logo": "https://media.api-sports.io/football/leagues/140.png",
        "league_round": "Regular Season - 38",
        "home_team_logo": "https://media.api-sports.io/football/teams/542.png",
        "away_team_logo": "https://media.api-sports.io/football/teams/728.png"
      }
    }
    // ... more H2H matches (full match details, not truncated)
  ],
  "summary": {
    "team_1_id": 542,
    "team_2_id": 728,
    "team_1_wins": 4,
    "team_2_wins": 7,
    "draws": 0,
    "total_matches": 11,
    "team_1_goals": 10,
    "team_2_goals": 12
  }
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"get_head_to_head","arguments":{"home_team_id":728,"away_team_id":542}}}' \
  /tmp/response.json

# Result: 11 H2H matches with full details + summary
# Rayo Vallecano: 7 wins, Alaves: 4 wins, Draws: 0
```

---

### get_team_stats

Get team statistics for a specific league and season. When current season has fewer than 10 matches, includes previous season stats and last 15 fixtures for comprehensive analysis.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_team_stats",
    "arguments": {
      "team_id": 728,
      "league_id": 140,
      "season": "2026"
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `team_id` | integer | Yes | - | API-Football team ID |
| `league_id` | integer | Yes | - | API-Football league ID |
| `season` | string | Yes | - | Season year (YYYY format, e.g., "2026") |

#### Response (when current season < 10 matches)

```json
{
  "stats": {
    "team_id": 728,
    "team_name": "Rayo Vallecano",
    "league_id": 140,
    "league_name": "La Liga",
    "season": 2026,
    "form": "L",
    "total_played": 1,
    "total_wins": 0,
    "total_draws": 0,
    "total_losses": 1,
    "total_goals_for": 1,
    "total_goals_against": 2,
    "home_played": 0,
    "wins_home": 0,
    "draws_home": 0,
    "losses_home": 0,
    "goals_for_home": 0,
    "goals_against_home": 0,
    "away_played": 1,
    "wins_away": 0,
    "draws_away": 0,
    "losses_away": 1,
    "goals_for_away": 1,
    "goals_against_away": 2,
    "clean_sheets_home": 0,
    "clean_sheets_away": 0,
    "clean_sheets_total": 0,
    "failed_to_score_home": 0,
    "failed_to_score_away": 0,
    "failed_to_score_total": 0,
    "biggest": {
      "streak": {"wins": 0, "draws": 0, "loses": 1},
      "wins": {"home": null, "away": null},
      "loses": {"home": null, "away": "2-1"},
      "goals": {"for": {"home": 0, "away": 1}, "against": {"home": 0, "away": 2}}
    },
    "penalty": {
      "scored": {"total": 0, "percentage": "0%"},
      "missed": {"total": 0, "percentage": "0%"},
      "total": 0
    }
  },
  "previous_season_stats": {
    "team_id": 728,
    "team_name": "Rayo Vallecano",
    "league_id": 140,
    "league_name": "La Liga",
    "season": 2025,
    "form": "WLDLDLLWWWLDDDLDLDWLLLWDDWDDLWLWDWDDWW",
    "total_played": 38,
    "total_wins": 12,
    "total_draws": 14,
    "total_losses": 12,
    // ... full previous season stats
  },
  "previous_season": 2025,
  "recent_fixtures": [
    // Last 15 completed fixtures across all competitions
    // (La Liga, Friendlies, Conference League, etc.)
  ],
  "recent_fixtures_count": 15,
  "data_note": "Current season (2026) has only 1 matches. Previous season stats and last 15 fixtures included for comprehensive analysis."
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"get_team_stats","arguments":{"team_id":728,"league_id":140,"season":"2026"}}}' \
  /tmp/response.json

# Result: Current season stats (1 match) + previous season full stats + 15 recent fixtures
```

---

### get_league_table

Get current league standings with full team statistics.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_league_table",
    "arguments": {
      "league_id": 140,
      "season": "2026"
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `league_id` | integer | Yes | - | API-Football league ID |
| `season` | string | Yes | - | Season year (YYYY format) |

#### Response

```json
{
  "standings": [
    {
      "team_id": 540,
      "team_name": "Espanyol",
      "team_logo": "https://media.api-sports.io/football/teams/540.png",
      "rank": 1,
      "points": 3,
      "played": 1,
      "wins": 1,
      "draws": 0,
      "losses": 0,
      "goals_for": 3,
      "goals_against": 0,
      "goal_difference": 3,
      "form": "W",
      "description": "Champions League league stage",
      "home_played": 1,
      "home_wins": 1,
      "home_draws": 0,
      "home_losses": 0,
      "home_goals_for": 3,
      "home_goals_against": 0,
      "away_played": 0,
      "away_wins": 0,
      "away_draws": 0,
      "away_losses": 0,
      "away_goals_for": 0,
      "away_goals_against": 0
    }
    // ... all 20 teams in La Liga
  ]
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"get_league_table","arguments":{"league_id":140,"season":"2026"}}}' \
  /tmp/response.json

# Result: Full La Liga 2026-27 standings with 20 teams
# Includes home/away splits, form, European/relegation descriptions
```

---

## Historical Tools

### query_history

Query historical match data for a team with flexible date filtering.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "query_history",
    "arguments": {
      "team_id": 728,
      "limit": 10
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `team_id` | integer | Yes | - | API-Football team ID |
| `league_id` | integer | No | null | Filter by specific league |
| `date_from` | string | No | null | Start date (YYYY-MM-DD) |
| `date_to` | string | No | null | End date (YYYY-MM-DD) |
| `limit` | integer | No | 20 | Maximum matches to return |

#### Response

```json
{
  "matches": [
    {
      "id": "1570341",
      "external_id": "1570341",
      "scheduled_at": "2026-08-15T19:30:00+00:00",
      "status": "FT",
      "home_team": "Sevilla",
      "away_team": "Rayo Vallecano",
      "home_team_id": 536,
      "away_team_id": 728,
      "league": "La Liga",
      "league_id": 140,
      "home_score": 2,
      "away_score": 1,
      "ht_home_score": 0,
      "ht_away_score": 1,
      "metadata": {
        "venue": "Ramón Sánchez Pizjuán",
        "referee": "Ricardo De Burgos Bengoetxea, Spain",
        "league_country": "Spain",
        "league_logo": "https://media.api-sports.io/football/leagues/140.png",
        "league_round": "Regular Season - 1",
        "home_team_logo": "https://media.api-sports.io/football/teams/536.png",
        "away_team_logo": "https://media.api-sports.io/football/teams/728.png"
      }
    },
    {
      "id": "1585060",
      "external_id": "1585060",
      "scheduled_at": "2026-08-08T14:00:00+00:00",
      "status": "FT",
      "home_team": "Ipswich",
      "away_team": "Rayo Vallecano",
      "home_team_id": 57,
      "away_team_id": 728,
      "league": "Friendlies Clubs",
      "league_id": 667,
      "home_score": 3,
      "away_score": 0,
      "ht_home_score": 3,
      "ht_away_score": 0,
      "metadata": {
        "venue": null,
        "referee": null,
        "league_country": "World",
        "league_logo": "https://media.api-sports.io/football/leagues/667.png",
        "league_round": "Club Friendlies",
        "home_team_logo": "https://media.api-sports.io/football/teams/57.png",
        "away_team_logo": "https://media.api-sports.io/football/teams/728.png"
      }
    }
    // ... more matches
  ]
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"query_history","arguments":{"team_id":728,"limit":10}}}' \
  /tmp/response.json

# Result: 10 completed fixtures including:
# - La Liga 2026-27: Sevilla 2-1 Rayo Vallecano (Aug 15)
# - Friendlies: vs Ipswich, Charleroi, Feyenoord, Hearts
# - Conference League Final: Crystal Palace 1-0 Rayo (May 27)
# - La Liga 2025-26: Multiple late-season matches
```

---

### get_form_data

Calculate team form from recent match results. Returns aggregated statistics showing team momentum and recent performance.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_form_data",
    "arguments": {
      "team_id": 728,
      "num_matches": 10
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `team_id` | integer | Yes | - | API-Football team ID |
| `num_matches` | integer | No | 5 | Number of recent matches to analyze |
| `league_id` | integer | No | null | Filter by specific league |

#### Response

```json
{
  "form_string": "LLWLLLWWDD",
  "matches_analyzed": 10,
  "wins": 3,
  "draws": 2,
  "losses": 5,
  "points": 11,
  "points_per_match": 1.1,
  "goals_for": 12,
  "goals_against": 15,
  "goal_difference": -3,
  "goals_per_match": 1.2,
  "conceded_per_match": 1.5
}
```

| Field | Description |
|-------|-------------|
| `form_string` | W/D/L sequence (most recent first) |
| `matches_analyzed` | Number of matches included |
| `wins/draws/losses` | Result counts |
| `points` | Total points (3 per win, 1 per draw) |
| `points_per_match` | Average points per match |
| `goals_for/against` | Total goals scored/conceded |
| `goal_difference` | Goals for minus goals against |
| `goals_per_match` | Average goals scored per match |
| `conceded_per_match` | Average goals conceded per match |

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"get_form_data","arguments":{"team_id":728,"num_matches":10}}}' \
  /tmp/response.json

# Result: Rayo Vallecano last 10 matches
# Form: LLWLLLWWDD (3W, 2D, 5L)
# Points: 11 (1.1 per match)
# Goals: 12 scored, 15 conceded (-3 GD)
```

---

## Odds Tools

### get_match_odds

Get betting odds from multiple bookmakers for a specific fixture.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_match_odds",
    "arguments": {
      "fixture_id": 1570351
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `fixture_id` | integer | Yes | - | API-Football fixture ID |
| `is_live` | boolean | No | false | Whether to fetch live odds |

#### Response

```json
{
  "fixture_id": 1570351,
  "count": 14,
  "odds": [
    {
      "bookmaker_id": 1,
      "bookmaker_name": "10Bet",
      "market": "1X2",
      "home_odds": 2.24,
      "draw_odds": 2.98,
      "away_odds": 3.45,
      "is_live": false,
      "updated_at": "2026-08-20T00:12:12.301157"
    },
    {
      "bookmaker_id": 8,
      "bookmaker_name": "Bet365",
      "market": "1X2",
      "home_odds": 2.25,
      "draw_odds": 3.0,
      "away_odds": 3.6,
      "is_live": false,
      "updated_at": "2026-08-20T00:12:12.301184"
    },
    {
      "bookmaker_id": 4,
      "bookmaker_name": "Pinnacle",
      "market": "1X2",
      "home_odds": 2.28,
      "draw_odds": 3.07,
      "away_odds": 3.71,
      "is_live": false,
      "updated_at": "2026-08-20T00:12:12.301206"
    }
    // ... more bookmakers (14 total)
  ]
}
```

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"get_match_odds","arguments":{"fixture_id":1570351}}}' \
  /tmp/response.json

# Result: Rayo vs Alaves odds from 14 bookmakers
# Home (Rayo): 2.24-2.36 | Draw: 2.78-3.14 | Away (Alaves): 3.11-3.75
# Bookmakers: 10Bet, William Hill, Bet365, Marathonbet, Unibet, Betfair,
#             BetVictor, Pinnacle, SBO, 1xBet, Betano, Superbet, 888Sport, Dafabet
```

---

### get_odds_movements

Track odds movements over time for a fixture. Returns current odds with note that historical movement tracking requires Redis storage.

**Status:** ✅ WORKING (Tested 2026-08-19)

> **Note:** API-Football doesn't provide historical odds snapshots. Full movement tracking requires implementing Redis-based odds history storage.

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_odds_movements",
    "arguments": {
      "fixture_id": 1570351,
      "time_window": "24h"
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `fixture_id` | integer | Yes | - | API-Football fixture ID |
| `time_window` | string | No | "24h" | Time window: "1h", "6h", "12h", "24h", "48h", "7d" |

#### Response

```json
{
  "fixture_id": 1570351,
  "movements": [],
  "opening_odds": null,
  "current_odds": {
    "home": 2.24,
    "draw": 2.98,
    "away": 3.45
  },
  "movement_summary": null,
  "note": "Historical odds movements require Redis-based tracking"
}
```

| Field | Description |
|-------|-------------|
| `movements` | List of historical odds snapshots (empty without Redis tracking) |
| `opening_odds` | First recorded odds (null without historical data) |
| `current_odds` | Latest odds from first available bookmaker |
| `movement_summary` | Net change in odds (null without historical data) |
| `note` | Explanation if data is limited |

#### Test Result

```bash
# Request
aws lambda invoke --function-name SipapDataMcpServer --cli-binary-format raw-in-base64-out \
  --payload '{"jsonrpc":"2.0","id":"test","method":"tools/call","params":{"name":"get_odds_movements","arguments":{"fixture_id":1570351}}}' \
  /tmp/response.json

# Result: Current odds returned (2.24 / 2.98 / 3.45)
# Historical movements not available (requires Redis implementation)
```

---

## Form Pattern Tools

All form pattern tools require `team_id` and `league_id` parameters.

### get_momentum_streak

Identifies current winning/losing/drawing streaks and momentum.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_momentum_streak",
    "arguments": {
      "team_id": 728,
      "league_id": 140,
      "match_limit": 15
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `team_id` | integer | Yes | - | API-Football team ID |
| `league_id` | integer | Yes | - | API-Football league ID |
| `match_limit` | integer | No | 15 | Number of matches to analyze |
| `venue` | string | No | null | Filter: "home" or "away" |

#### Response

```json
{
  "tool": "get_momentum_streak",
  "data": {
    "current_streak": {
      "type": "mixed",
      "length": 1,
      "points": 0,
      "goals_scored_avg": 1.0,
      "goals_conceded_avg": 2.0
    },
    "longest_streak": {
      "type": "winning",
      "length": 2,
      "period": "May 23 - May 17",
      "points": 6
    },
    "recent_form": {
      "matches_analyzed": 15,
      "wins": 6,
      "draws": 6,
      "losses": 3,
      "points": 24
    },
    "momentum_rating": 30
  },
  "metadata": {
    "venue": "all",
    "earliest_match": "2026-02-28T13:00:00+00:00",
    "latest_match": "2026-08-15T19:30:00+00:00"
  }
}
```

---

### get_form_trajectory

Analyzes if team form is improving, declining, or stable.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "tools/call",
  "params": {
    "name": "get_form_trajectory",
    "arguments": {
      "team_id": 728,
      "league_id": 140,
      "match_limit": 15
    }
  }
}
```

#### Response

```json
{
  "tool": "get_form_trajectory",
  "data": {
    "trajectory": "stable",
    "last_5": {
      "points": 8,
      "wins": 2,
      "draws": 2,
      "losses": 1,
      "goals_scored": 7,
      "goals_conceded": 5
    },
    "previous_5": {
      "points": 10,
      "wins": 3,
      "draws": 1,
      "losses": 1,
      "goals_scored": 7,
      "goals_conceded": 6
    },
    "comparison": {
      "points_change": -2,
      "points_percentage_change": -20.0,
      "goals_scored_change": 0.0,
      "goals_conceded_change": -0.2,
      "win_rate_change": -20.0
    },
    "trajectory_rating": 54
  },
  "metadata": {
    "venue": "all",
    "matches_analyzed": 15
  }
}
```

---

### get_consistency_score

Measures how predictable a team's results are.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Response

```json
{
  "tool": "get_consistency_score",
  "data": {
    "consistency_rating": 33,
    "volatility": "medium",
    "pattern": "trending",
    "std_deviation": 1.01,
    "result_distribution": {
      "wins": 6,
      "draws": 6,
      "losses": 3,
      "dominant_result": "mixed"
    },
    "points_per_match_avg": 1.6,
    "reliability_assessment": "Highly volatile - unreliable form pattern (form is changing)"
  },
  "metadata": {
    "venue": "all",
    "matches_analyzed": 15
  }
}
```

---

### get_venue_form_split

Compares home vs away performance.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Response

```json
{
  "tool": "get_venue_form_split",
  "data": {
    "home_form": {
      "points": 16,
      "wins": 4,
      "draws": 4,
      "losses": 0,
      "goals_scored": 13,
      "goals_conceded": 6,
      "form_score": 11.0,
      "win_rate": 0.5
    },
    "away_form": {
      "points": 8,
      "wins": 2,
      "draws": 2,
      "losses": 3,
      "goals_scored": 7,
      "goals_conceded": 9,
      "form_score": 7.0,
      "win_rate": 0.286
    },
    "comparison": {
      "points_differential": 8,
      "form_score_differential": 4.0,
      "win_rate_differential": 0.214,
      "goals_scored_differential": 0.62,
      "venue_impact": "medium",
      "stronger_venue": "home"
    },
    "venue_advantage_rating": 74
  },
  "metadata": {
    "home_matches_analyzed": 8,
    "away_matches_analyzed": 7
  }
}
```

---

### get_goal_scoring_form_trend

Analyzes attacking output trends.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Response

```json
{
  "tool": "get_goal_scoring_form_trend",
  "data": {
    "trend": "stable",
    "last_5": {
      "goals_scored": 7,
      "avg_per_match": 1.4,
      "highest_in_match": 2,
      "matches_2plus_goals": 2
    },
    "previous_5": {
      "goals_scored": 7,
      "avg_per_match": 1.4,
      "highest_in_match": 3,
      "matches_2plus_goals": 2
    },
    "comparison": {
      "goals_change": 0,
      "avg_change": 0.0,
      "percentage_change": 0.0
    },
    "highest_scoring_streak": 2,
    "offensive_rating": 51
  },
  "metadata": {
    "venue": "all",
    "matches_analyzed": 15
  }
}
```

---

### get_defensive_form_trend

Analyzes defensive performance trends.

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Response

```json
{
  "tool": "get_defensive_form_trend",
  "data": {
    "trend": "stable",
    "last_5": {
      "goals_conceded": 5,
      "avg_per_match": 1.0,
      "worst_in_match": 2,
      "clean_sheets": 1
    },
    "previous_5": {
      "goals_conceded": 6,
      "avg_per_match": 1.2,
      "worst_in_match": 3,
      "clean_sheets": 3
    },
    "comparison": {
      "goals_change": -1,
      "avg_change": -0.2,
      "percentage_change": -16.7,
      "clean_sheets_change": -2
    },
    "clean_sheet_streak": 0,
    "defensive_rating": 52
  },
  "metadata": {
    "venue": "all",
    "matches_analyzed": 15
  }
}
```

---

### get_pressure_performance

Analyzes performance in high-stakes situations (vs strong vs weak opponents).

**Status:** ✅ WORKING (Tested 2026-08-19)

#### Response

```json
{
  "tool": "get_pressure_performance",
  "data": {
    "vs_strong_opponents": {
      "matches": 6,
      "points": 13,
      "wins": 4,
      "draws": 1,
      "losses": 1,
      "points_per_match": 2.17,
      "goals_scored": 8,
      "goals_conceded": 4
    },
    "vs_weaker_opponents": {
      "matches": 9,
      "points": 11,
      "wins": 2,
      "draws": 5,
      "losses": 2,
      "points_per_match": 1.22,
      "goals_scored": 12,
      "goals_conceded": 11
    },
    "comparison": {
      "points_per_match_diff": 0.95,
      "win_rate_diff": 0.444,
      "performance_differential": 31,
      "pressure_rating": "high"
    },
    "pressure_performance_rating": 83
  },
  "metadata": {
    "strong_opponent_threshold": 2.0,
    "matches_analyzed": 15
  }
}
```

> **Insight:** Rayo Vallecano performs better against strong opponents (2.17 PPM) than weaker ones (1.22 PPM). Pressure performance rating: 83/100.

---

## Statistical Analysis Tools

All 24 statistical analysis tools are now working with API-Football integration.

**Status:** ✅ ALL WORKING (Tested 2026-08-19)

### Common Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `home_team` | string \| int | Team name or API-Football team ID |
| `away_team` | string \| int | Team name or API-Football team ID |
| `league` | string \| int | League name or API-Football league ID |
| `team` | string \| int | Team name or ID (for single-team tools) |
| `seasons_back` | int | Historical seasons to analyze (default: 6) |
| `current_form_matches` | int | Recent matches for form (default: 10) |

> **Note:** Using integer IDs is recommended for more reliable API integration.

---

### Core Statistical Tools (5)

#### get_h2h_full_time_result

Analyze head-to-head full-time results with recency weighting.

```json
// Request
{"home_team": 728, "away_team": 542, "league": 140}

// Response
{
  "tool": "get_h2h_full_time_result",
  "data": {
    "total_matches": 11,
    "home_wins": 7,
    "draws": 0,
    "away_wins": 4,
    "home_win_probability": 0.6364,
    "draw_probability": 0.0,
    "away_win_probability": 0.3636,
    "weighted_probabilities": {
      "home_win": 0.7643,
      "draw": 0.0,
      "away_win": 0.2357
    },
    "current_form": {
      "recent_matches": 10,
      "home_wins": 7,
      "draws": 0,
      "away_wins": 3,
      "home_win_probability": 0.7
    },
    "by_season": [
      {"season": "2026-2027", "matches": 2, "home_wins": 1, "draws": 0, "away_wins": 1}
      // ... more seasons
    ]
  },
  "metadata": {
    "seasons_analyzed": 8,
    "earliest_match": "2018-09-22T11:00:00+00:00",
    "latest_match": "2026-05-23T19:00:00+00:00",
    "data_quality": "medium"
  }
}
```

#### get_h2h_goals

Analyze total goals with over/under thresholds.

```json
// Response
{
  "data": {
    "total_matches": 11,
    "total_goals": 22,
    "average_goals_per_match": 2.0,
    "over_thresholds": {
      "over_0.5": {"count": 11, "probability": 1.0},
      "over_1.5": {"count": 6, "probability": 0.5455},
      "over_2.5": {"count": 2, "probability": 0.1818}
    },
    "under_thresholds": {
      "under_2.5": {"count": 9, "probability": 0.8182}
    },
    "weighted_probabilities": {
      "over_2.5": 0.0786,
      "under_2.5": 0.9214
    }
  }
}
```

#### get_bts

Analyze both teams to score probability.

```json
// Response
{
  "data": {
    "total_matches": 11,
    "bts_occurrences": 2,
    "bts_probability": 0.1818,
    "no_bts_probability": 0.8182,
    "weighted_bts_probability": 0.0786,
    "breakdown": {
      "home_scored_away_blanked": 7,
      "away_scored_home_blanked": 2,
      "both_scored": 2,
      "both_blanked": 0
    }
  }
}
```

#### get_home_total_goals

Analyze home team's scoring patterns.

```json
// Request
{"team": 728, "league": 140}

// Response
{
  "data": {
    "total_matches": 25,
    "total_goals_scored": 30,
    "average_goals_per_match": 1.2,
    "scoring_probabilities": {
      "0_goals": 0.2,
      "1_goal": 0.52,
      "2_goals": 0.16
    },
    "over_thresholds": {
      "over_0.5": 0.8,
      "over_1.5": 0.28
    }
  }
}
```

#### get_away_total_goals

Same as get_home_total_goals but for away matches.

---

### Halftime Analysis Tools (5)

All halftime tools require `home_team`, `away_team`, and `league` parameters (using API-Football IDs).

**Status:** ✅ ALL WORKING (Tested 2026-08-19)

#### get_h2h_half_time_result

Analyze head-to-head half-time results (leading, drawing, trailing at HT).

```json
// Request
{"home_team": 728, "away_team": 542, "league": 140}

// Response
{
  "tool": "get_h2h_half_time_result",
  "data": {
    "total_matches": 11,
    "home_leading_ht": 3,
    "draw_ht": 5,
    "away_leading_ht": 3,
    "home_leading_ht_probability": 0.2727,
    "draw_ht_probability": 0.4545,
    "away_leading_ht_probability": 0.2727,
    "weighted_probabilities": {
      "home_leading_ht": 0.3571,
      "draw_ht": 0.4857,
      "away_leading_ht": 0.1571
    },
    "current_form": {
      "recent_matches": 10,
      "home_leading_ht": 3,
      "home_leading_ht_probability": 0.3
    }
  },
  "metadata": {
    "seasons_analyzed": 8,
    "halftime_data_coverage": 1.0,
    "data_quality": "medium"
  }
}
```

> **Insight:** Draw at HT most likely (45.45%), with weighted probability of 48.57%.

---

#### get_h2h_2nd_half_result

Analyze second half results (calculated as FT score - HT score).

```json
// Response
{
  "tool": "get_h2h_2nd_half_result",
  "data": {
    "total_matches": 11,
    "home_wins_2h": 6,
    "draws_2h": 2,
    "away_wins_2h": 3,
    "home_win_2h_probability": 0.5455,
    "draw_2h_probability": 0.1818,
    "away_win_2h_probability": 0.2727,
    "weighted_probabilities": {
      "home_win_2h": 0.6857,
      "draw_2h": 0.1571,
      "away_win_2h": 0.1571
    }
  },
  "metadata": {
    "seasons_analyzed": 8,
    "halftime_data_coverage": 1.0,
    "data_quality": "medium"
  }
}
```

> **Insight:** Rayo Vallecano dominates second halves (54.55% win rate, weighted 68.57%).

---

#### get_ht_ft_outcome

Analyze all 9 HT/FT outcome combinations (Home/Draw/Away at HT × Home/Draw/Away at FT).

```json
// Response
{
  "tool": "get_ht_ft_outcome",
  "data": {
    "total_matches": 11,
    "outcomes": [
      {"halftime": "Home", "fulltime": "Home", "count": 3, "probability": 0.2727},
      {"halftime": "Draw", "fulltime": "Home", "count": 3, "probability": 0.2727},
      {"halftime": "Draw", "fulltime": "Away", "count": 2, "probability": 0.1818},
      {"halftime": "Away", "fulltime": "Away", "count": 2, "probability": 0.1818},
      {"halftime": "Away", "fulltime": "Home", "count": 1, "probability": 0.0909},
      {"halftime": "Home", "fulltime": "Draw", "count": 0, "probability": 0.0},
      {"halftime": "Home", "fulltime": "Away", "count": 0, "probability": 0.0},
      {"halftime": "Draw", "fulltime": "Draw", "count": 0, "probability": 0.0},
      {"halftime": "Away", "fulltime": "Draw", "count": 0, "probability": 0.0}
    ],
    "most_likely": {
      "halftime": "Home",
      "fulltime": "Home",
      "count": 3,
      "probability": 0.2727
    }
  },
  "metadata": {
    "seasons_analyzed": 8,
    "halftime_data_coverage": 1.0,
    "data_quality": "medium"
  }
}
```

> **Insight:** Most common outcomes are Home/Home and Draw/Home (27.27% each). No draws at full-time historically.

---

#### get_half_time_goals

Analyze halftime goals scored by each team.

```json
// Response
{
  "tool": "get_half_time_goals",
  "data": {
    "total_matches": 11,
    "home_ht_goals": {
      "total": 5,
      "average": 0.45,
      "probabilities": {
        "0_goals": 0.6364,
        "1_goal": 0.2727,
        "2+_goals": 0.0909
      },
      "over_0.5": 0.3636
    },
    "away_ht_goals": {
      "total": 4,
      "average": 0.36,
      "probabilities": {
        "0_goals": 0.7273,
        "1_goal": 0.1818,
        "2+_goals": 0.0909
      },
      "over_0.5": 0.2727
    },
    "total_ht_goals": {
      "average": 0.82,
      "over_1.5": 0.1818
    }
  },
  "metadata": {
    "seasons_analyzed": 8,
    "halftime_data_coverage": 1.0,
    "data_quality": "medium"
  }
}
```

> **Insight:** Low-scoring first halves (0.82 goals avg). Under 1.5 HT goals hits 81.82%.

---

#### get_2nd_half_goals

Analyze second half goals scored by each team (FT - HT).

```json
// Response
{
  "tool": "get_2nd_half_goals",
  "data": {
    "total_matches": 11,
    "home_2h_goals": {
      "total": 7,
      "average": 0.64
    },
    "away_2h_goals": {
      "total": 6,
      "average": 0.55
    },
    "total_2h_goals": {
      "average": 1.18,
      "over_1.5": 0.2727
    }
  },
  "metadata": {
    "seasons_analyzed": 8,
    "halftime_data_coverage": 1.0,
    "data_quality": "medium"
  }
}
```

> **Insight:** Second halves slightly more productive (1.18 avg vs 0.82 in first half).

---

### Combination Market Tools (9)

All combination tools use OR and AND logic for compound betting markets.

**Status:** ✅ ALL WORKING (Tested 2026-08-19)

#### get_double_chance

Probability of not losing (Win OR Draw).

```json
// Request
{"home_team": 728, "away_team": 542, "league": 140, "perspective": "home"}

// Response
{
  "tool": "get_double_chance",
  "data": {
    "total_matches": 11,
    "perspective": "home",
    "outcomes": {"home_win": 7, "draw": 0, "away_win": 4},
    "double_chance_count": 7,
    "double_chance_probability": 0.6364,
    "weighted_probability": 0.7643
  },
  "metadata": {
    "seasons_analyzed": 8,
    "data_quality": "medium"
  }
}
```

> **Insight:** Rayo has 63.64% not-to-lose probability (76.43% weighted). No draws in H2H history.

---

#### get_win_or_total_goals

Team wins OR match has X+ goals (OR logic).

```json
// Response
{
  "tool": "get_win_or_total_goals",
  "data": {
    "total_matches": 11,
    "perspective": "home",
    "goals_threshold": 2.5,
    "conditions": {
      "team_win": {"count": 7, "probability": 0.6364},
      "over_goals": {"count": 2, "probability": 0.1818}
    },
    "breakdown": {"win_only": 6, "goals_only": 1, "both": 1, "neither": 3},
    "or_logic": {"count": 8, "probability": 0.7273},
    "weighted_probability": 0.7929
  }
}
```

> **Insight:** 72.73% either Rayo wins OR over 2.5 goals (79.29% weighted).

---

#### get_win_and_total_goals

Team wins AND match has X+ goals (AND logic).

```json
// Response
{
  "data": {
    "total_matches": 11,
    "and_logic": {"count": 1, "probability": 0.0909},
    "weighted_probability": 0.05
  }
}
```

---

#### get_win_or_both_scores / get_win_and_both_scores

Win combined with BTS using OR/AND logic.

---

#### get_both_scores_or_multi_goals

BTS OR over 2.5 goals (popular safety net bet).

---

#### get_no_defeat_and_total_goals

Team avoids defeat AND over X goals.

---

#### get_avoid_halftime_defeat

Probability of not losing at half-time (leading OR drawing at HT).

```json
// Response
{
  "tool": "get_avoid_halftime_defeat",
  "data": {
    "total_matches": 11,
    "perspective": "home",
    "halftime_outcomes": {"home_win": 3, "draw": 5, "away_win": 3},
    "avoid_defeat_count": 8,
    "avoid_defeat_probability": 0.7273,
    "weighted_probability": 0.8429
  },
  "metadata": {
    "halftime_data_coverage": 1.0,
    "data_quality": "medium"
  }
}
```

> **Insight:** 72.73% Rayo not trailing at HT (84.29% weighted).

---

#### get_avoid_2nd_half_defeat

Probability of not losing in second half (winning OR drawing in 2H).

```json
// Response
{
  "tool": "get_avoid_2nd_half_defeat",
  "data": {
    "total_matches": 11,
    "perspective": "home",
    "second_half_outcomes": {"home_win": 6, "draw": 2, "away_win": 3},
    "avoid_defeat_count": 8,
    "avoid_defeat_probability": 0.7273,
    "weighted_probability": 0.8429
  }
}
```

> **Insight:** 72.73% Rayo not losing second half (84.29% weighted).

---

### Specialized Analysis Tools (5)

**Status:** ✅ ALL WORKING (Tested 2026-08-19)

#### get_total_goals_range

Analyze goal distribution with percentiles and most common range.

```json
// Response
{
  "tool": "get_total_goals_range",
  "data": {
    "total_matches": 11,
    "goal_distribution": {"0-1": 5, "2-3": 5, "4-5": 0, "6+": 1},
    "most_common_range": {"range": "0-1", "occurrences": 5, "probability": 0.4545},
    "percentiles": {"25th": 1, "50th": 2, "75th": 2},
    "weighted_probabilities": {"0-1": 0.5143, "2-3": 0.4571, "4-5": 0.0, "6+": 0.0286}
  }
}
```

> **Insight:** Low-scoring fixture. 0-1 and 2-3 goals most common (45.45% each).

---

#### get_home_either_half_outcome

Analyze which half home team tends to win (1H vs 2H dominance).

```json
// Response
{
  "tool": "get_home_either_half_outcome",
  "data": {
    "total_matches": 11,
    "first_half_wins": 3,
    "second_half_wins": 6,
    "probabilities": {
      "win_first_half": 0.2727,
      "win_second_half": 0.5455,
      "win_either_half": 0.6364,
      "win_both_halves": 0.1818
    },
    "weighted_probabilities": {
      "win_first_half": 0.3571,
      "win_second_half": 0.6857,
      "win_either_half": 0.7643,
      "win_both_halves": 0.2786
    },
    "tendency": "second_half"
  },
  "metadata": {
    "halftime_data_coverage": 1.0,
    "data_quality": "medium"
  }
}
```

> **Insight:** Rayo dominates second halves (54.55% vs 27.27% first half). 76.43% weighted to win either half.

---

#### get_away_either_half_outcome

Same as above but for away team perspective.

---

#### get_home_to_score

Probability that home team scores at least one goal.

```json
// Response
{
  "tool": "get_home_to_score",
  "data": {
    "total_matches": 11,
    "home_scored": 8,
    "home_blanked": 3,
    "home_to_score_probability": 0.7273,
    "weighted_probability": 0.7929
  }
}
```

> **Insight:** Rayo scores in 72.73% of H2H matches (79.29% weighted).

---

#### get_away_to_score

Probability that away team scores at least one goal.

```json
// Response
{
  "tool": "get_away_to_score",
  "data": {
    "total_matches": 11,
    "away_scored": 5,
    "away_blanked": 6,
    "away_to_score_probability": 0.4545,
    "weighted_probability": 0.2857
  }
}
```

> **Insight:** Alaves struggles to score vs Rayo (45.45% historical, only 28.57% weighted recent form).

---

### Test Results Summary

```bash
# All statistical tools tested with Rayo Vallecano (728) vs Alaves (542)
# Data quality: 11 H2H matches across 8 seasons (2018-2026)

# Key insights from H2H:
# - Rayo Vallecano dominates: 7 wins, 0 draws, 4 losses
# - Low-scoring fixture: avg 2.0 goals, 82% under 2.5
# - BTS rare: only 18% (Rayo tends to blank Alaves)
# - Weighted home win probability: 76.4%
```

---

## Error Handling

All tools return errors in JSON-RPC 2.0 format:

```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "error": {
    "code": -32603,
    "message": "Internal error: <error description>"
  }
}
```

Common error codes:
- `-32603`: Internal error (check message for details)
- `-32602`: Invalid parameters
- `-32601`: Method not found
