# SIPAP Data MCP Tools Reference

**Generated:** 2026-08-19
**Purpose:** Comprehensive documentation of Data MCP tool inputs/outputs for orchestrator configuration
**Log Group:** `/aws/lambda/SipapDataMcpServer`

---

## Category 1: Match/Fixture Tools ✅ ALL TESTED

### 1.1 get_match_schedule ✅

**Description:** Get match schedule for date range with optional filters

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
    "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
    "status": {"type": "string", "description": "scheduled|live|finished", "default": "scheduled"},
    "league_id": {"type": "string", "description": "Optional league UUID filter"}
  },
  "required": ["date_from", "date_to"]
}
```

**Output:** `{"matches": [{id, external_id, scheduled_at, status, home_team, away_team, home_team_id, away_team_id, league, league_id, home_score, away_score, metadata, best_home_odds, best_draw_odds, best_away_odds, bookmakers_count}]}`

**Test:** ✅ 351 matches for 2026-08-19

---

### 1.2 get_match_details ✅

**Description:** Get detailed information for a specific match

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "match_id": {"type": "string", "description": "Match UUID"}
  },
  "required": ["match_id"]
}
```

**Output:** `{"match": {id, external_id, scheduled_at, status, home_team, away_team, home_team_id, away_team_id, league, league_id, league_external_id, home_score, away_score, metadata}}`

**Test:** ✅ The Strongest vs Oriente Petrolero (Copa de la División Profesional)

---

### 1.3 get_live_matches ✅

**Description:** Get all currently live matches

**Input Schema:**
```json
{
  "type": "object",
  "properties": {}
}
```

**Output:** `{"matches": [/* same as get_match_schedule */]}`

**Test:** ✅ 531 matches returned

---

### 1.4 search_matches ✅

**Description:** Search for matches by team name or other criteria

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "Search query string"}
  },
  "required": ["query"]
}
```

**Output:** `{"matches": [/* same as get_match_schedule */]}`

**Test:** ✅ 100 matches for "Barcelona"

---

### 1.5 search_fixtures ✅

**Description:** Search for fixtures with flexible filtering (leagues, dates, odds availability)

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "league_ids": {"type": "array", "items": {"type": "integer"}, "description": "API-Football league IDs [39, 140]"},
    "league_names": {"type": "array", "items": {"type": "string"}, "description": "League names (legacy)"},
    "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
    "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
    "status": {"type": "string", "default": "scheduled"},
    "has_odds": {"type": "boolean", "default": true},
    "limit": {"type": "integer", "default": 100}
  },
  "required": []
}
```

**Output:** `{"fixtures": [...], "count": int, "filters_applied": {}}`

**Test:** ✅ 10 fixtures with odds (Banfield vs Midland, H=1.98, D=3.7, A=4.6)

---

## Category 2: Team/League Tools ⚠️ 1 BUG

### 2.1 get_team_stats ✅

**Description:** Get team statistics for a season (uses API-Football integer IDs)

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "team_id": {"type": "integer", "description": "API-Football team ID (e.g., 50 for Man City)"},
    "league_id": {"type": "integer", "description": "API-Football league ID (e.g., 39 for EPL)"},
    "season": {"type": "string", "description": "Season year (e.g., '2025')"}
  },
  "required": ["team_id", "league_id", "season"]
}
```

**Output:** `{"stats": {home_played, away_played, total_played, total_wins, total_draws, total_losses, total_goals_for, total_goals_against, wins_home, wins_away, draws_home, draws_away, losses_home, losses_away, goals_for_home, goals_for_away, goals_against_home, goals_against_away, clean_sheets_home, clean_sheets_away, clean_sheets_total, failed_to_score_home, failed_to_score_away, failed_to_score_total}}`

**Test:** ✅ Man City (ID 50), EPL (ID 39), Season 2025

---

### 2.2 get_league_table ❌ BUG

**Description:** Get league standings/table

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "league_id": {"type": "integer", "description": "API-Football league ID"},
    "season": {"type": "string", "description": "Season year"}
  },
  "required": ["league_id", "season"]
}
```

**Test:** ❌ **ERROR**: `column "played" does not exist` - DB schema mismatch

---

### 2.3 get_head_to_head ✅

**Description:** Get head-to-head history between two teams

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "home_team_id": {"type": "integer", "description": "API-Football team ID"},
    "away_team_id": {"type": "integer", "description": "API-Football team ID"},
    "limit": {"type": "integer", "default": 10}
  },
  "required": ["home_team_id", "away_team_id"]
}
```

**Output:** `{"head_to_head": [...], "summary": {...}}`

**Test:** ✅ Works (empty h2h data for tested teams)

---

## Category 3: Historical/Form Data ✅ ALL TESTED

### 3.1 query_history ✅

**Description:** Query historical match data

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "team_id": {"type": "integer", "description": "API-Football team ID"},
    "league_id": {"type": "integer", "description": "Optional league filter"},
    "date_from": {"type": "string", "description": "Start date"},
    "date_to": {"type": "string", "description": "End date"},
    "status": {"type": "string", "default": "finished"},
    "limit": {"type": "integer", "default": 20}
  },
  "required": ["team_id"]
}
```

**Test:** ✅ Works (0 finished matches for test team)

---

### 3.2 get_form_data ✅

**Description:** Get recent form data for a team

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "team_id": {"type": "integer", "description": "API-Football team ID"},
    "num_matches": {"type": "integer", "default": 5}
  },
  "required": ["team_id"]
}
```

**Test:** ✅ Works (empty form - no finished matches)

---

## Category 4: Odds Tools ⚠️ 1 BUG

### 4.1 get_match_odds ✅

**Description:** Get betting odds for a match

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "fixture_id": {"type": "integer", "description": "API-Football fixture ID"},
    "is_live": {"type": "boolean", "default": false}
  },
  "required": ["fixture_id"]
}
```

**Output:** `{"fixture_id": int, "count": int, "odds": [{bookmaker_name, market, home_odds, draw_odds, away_odds, is_live, updated_at}]}`

**Test:** ✅ Fixture 1549146 (Banfield vs Midland): H=1.98, D=3.7, A=4.6

---

### 4.2 get_odds_movements ❌ BUG

**Description:** Track odds movements over time for a match

**Input Schema (INCORRECT - needs fix):**
```json
{
  "type": "object",
  "properties": {
    "match_id": {"type": "string", "description": "Match UUID"},
    "time_window": {"type": "string", "default": "24h"}
  },
  "required": ["match_id"]
}
```

**Test:** ❌ **BUG**: Schema uses `match_id: str` but `tools/odds.py` expects `fixture_id: int`. Parameter mismatch in `server.py`.

**Fix Required:** Update `server.py` to use `fixture_id` in schema and pass `fixture_id` to underlying function.

---

## Category 5: Market Intelligence

### 5.1 get_implied_probabilities
**Test:** PENDING

### 5.2 get_value_opportunities
**Test:** PENDING

---

## Category 6-11: Statistical/Form/Analysis Tools
**Test:** PENDING

---

## Known Bugs Summary

| Tool | Error | Fix |
|------|-------|-----|
| get_league_table | `column "played" does not exist` | Update DB query or standings table schema |
| get_odds_movements | Parameter mismatch (`match_id` vs `fixture_id`) | Update server.py schema to use `fixture_id: int` |

