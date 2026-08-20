"""Soccer Orchestrator - Coordinates all agents to generate ensemble predictions.

Pattern adapted from Sentinel's multi-agent workflow system.

Phase 4: Now includes MCP integration for data aggregation and validation.
"""

import asyncio
import json
import logging
import os
import statistics
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sipap_common.database.manager import DatabaseManager
from sipap_common.exceptions import DatabaseError, MCPError
from sipap_common.utils.retry import retry_with_backoff
from sqlalchemy import text

from sipap.factory.agent import AgentToolFactory
from sipap.factory.mcp import MCPFactory
from sipap.sports.soccer.market_evaluator import MarketEvaluator, MarketEvaluation


class SoccerOrchestrator:
    """
    Coordinates 3 specialized agents to generate ensemble predictions.

    Agents (MVP - v2.3):
    1. Statistical Agent (40%) - Long-term statistical analysis (Poisson, xG, Elo)
    2. Form Agent (40%) - Recent performance patterns and trends
    3. News Agent (20%) - Current reality adjustments (injuries, suspensions, team news)

    Note: ML Agent and Market Agent removed from MVP for simplicity.

    This is a simplified implementation focusing on ensemble logic and quality gates.
    """

    def __init__(self, logger: logging.Logger | None = None):
        """
        Initialize the orchestrator.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        # Initialize AgentToolFactory
        self.agent_factory = AgentToolFactory(sport="soccer", logger=self.logger)

        # Initialize MCPFactory for data aggregation
        self.mcp_factory = MCPFactory(logger=self.logger)

        # Cache for loaded tools (to avoid re-loading on every prediction)
        self._tools_cache: dict[str, list[Any]] | None = None

        # Initialize DatabaseManager for Aurora PostgreSQL
        # Use environment variable or construct from components
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            # Construct from individual environment variables
            db_host = os.environ.get("DB_HOST", "localhost")
            db_port = os.environ.get("DB_PORT", "5432")
            db_name = os.environ.get("DB_NAME", "sipap")
            db_user = os.environ.get("DB_USER", "sipap")
            db_password = os.environ.get("DB_PASSWORD", "sipap")
            database_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

        self.db = DatabaseManager(database_url, use_pool=True)

        # Check if DEBUG logging is enabled
        self.debug_enabled = self.logger.isEnabledFor(logging.DEBUG)

        # Initialize MarketEvaluator for 44-market evaluation
        # Will be properly initialized when data MCP is created
        self._market_evaluator: MarketEvaluator | None = None

        log_mode = "DEBUG mode enabled" if self.debug_enabled else "INFO mode (summary only)"
        self.logger.info(f"SoccerOrchestrator initialized - {log_mode}")

    @retry_with_backoff(
        max_attempts=3,
        initial_delay=1.0,
        backoff_factor=2.0,
        retry_exceptions=(ConnectionError, TimeoutError, OSError),
        no_retry_exceptions=(ValueError, KeyError, MCPError),
        jitter=True,
    )
    async def _call_mcp_with_retry(
        self,
        mcp_client: Any,
        tool_name: str,
        parameters: dict[str, Any],
        server_name: str = "unknown",
    ) -> dict[str, Any]:
        """
        Call MCP tool with automatic retry on transient failures.

        Args:
            mcp_client: MCP client instance
            tool_name: Name of the MCP tool to call
            parameters: Tool parameters
            server_name: Name of MCP server (for logging)

        Returns:
            Tool result dictionary

        Raises:
            MCPError: If MCP call fails after all retries
            ValueError: If parameters are invalid (no retry)
        """
        try:
            result = await mcp_client.call_tool(tool_name, parameters)

            # Check if result is an exception (from return_exceptions=True)
            if isinstance(result, Exception):
                raise MCPError(
                    f"MCP tool '{tool_name}' on server '{server_name}' returned error: {str(result)}"
                )

            return result

        except (ConnectionError, TimeoutError, OSError) as e:
            # Transient errors - will be retried by decorator
            self.logger.warning(
                f"Transient MCP error (will retry): {server_name}.{tool_name}",
                extra={"error": str(e), "parameters": parameters},
            )
            raise
        except Exception as e:
            # Non-transient errors - wrap in MCPError
            self.logger.error(
                f"MCP call failed: {server_name}.{tool_name}",
                exc_info=True,
                extra={"parameters": parameters},
            )
            raise MCPError(f"MCP tool '{tool_name}' failed: {str(e)}") from e

    def extract_season_from_date(self, match_date: datetime | str) -> str:
        """
        Extract football season from match date.

        Football seasons span two calendar years, but we return just the start year:
        - August-December: current_year (e.g., "2024" for Dec 2024)
        - January-July: previous_year (e.g., "2024" for Jan 2025)

        Args:
            match_date: Match date as datetime object or ISO string

        Returns:
            Season string in format "YYYY" (e.g., "2024")

        Example:
            >>> extract_season_from_date("2024-12-25")  # December 2024
            "2024-2025"
            >>> extract_season_from_date("2025-01-15")  # January 2025
            "2024-2025"
            >>> extract_season_from_date("2025-08-10")  # August 2025
            "2025-2026"
        """
        # Convert string to datetime if needed
        if isinstance(match_date, str):
            try:
                match_date = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            except ValueError:
                # Try parsing just the date part (YYYY-MM-DD)
                match_date = datetime.strptime(match_date[:10], "%Y-%m-%d")

        year = match_date.year
        month = match_date.month

        # Season logic: August (8) to July (7)
        # August-December: return current year
        # January-July: return previous year (season start year)
        if month >= 8:  # August to December
            season = str(year)
        else:  # January to July
            season = str(year - 1)

        return season

    async def resolve_match_id(self, match_identifier: str) -> str:
        """
        Resolve match identifier to UUID.

        Handles both UUID and natural language inputs:
        - If UUID format: return as-is
        - If natural language (e.g., "Man United vs Liverpool"): search and return UUID

        Args:
            match_identifier: Either UUID or natural language (team names)

        Returns:
            Match UUID string

        Raises:
            ValueError: If match cannot be resolved

        Example:
            >>> # UUID input
            >>> match_id = await orchestrator.resolve_match_id("550e8400-e29b-41d4-a716-446655440000")
            >>> # Natural language input
            >>> match_id = await orchestrator.resolve_match_id("Manchester United vs Liverpool")
        """
        # Check if it's already a UUID
        try:
            uuid.UUID(match_identifier)
            self.logger.debug(f"Match identifier is valid UUID: {match_identifier}")
            return match_identifier
        except ValueError:
            pass

        # Not a UUID - treat as natural language search query
        self.logger.debug(f"Resolving natural language match identifier: {match_identifier}")

        try:
            # Use MCP data server to search for matches
            data_mcp = self.mcp_factory.create("data")
            result = await data_mcp.call_tool("search_matches", {"query": match_identifier})

            matches = result.get("matches", [])

            if not matches:
                raise ValueError(f"No matches found for query: {match_identifier}")

            # Take the first match (most relevant)
            match = matches[0]
            match_id = match.get("id")

            if not match_id:
                raise ValueError(f"Match found but missing ID: {match}")

            self.logger.info(
                f"Resolved '{match_identifier}' to match_id: {match_id}",
                extra={
                    "query": match_identifier,
                    "match_id": match_id,
                    "home_team": match.get("home_team", {}).get("name"),
                    "away_team": match.get("away_team", {}).get("name"),
                },
            )

            return match_id

        except Exception as e:
            self.logger.error(
                f"Failed to resolve match identifier: {match_identifier}",
                exc_info=True,
            )
            raise ValueError(f"Cannot resolve match identifier '{match_identifier}': {str(e)}") from e

    async def aggregate_context(self, match_id: str) -> dict[str, Any]:
        """
        Aggregate context from all MCP servers in parallel.

        Fetches data from:
        - Sports Data MCP: fixtures, stats, odds, form
        - Intelligence MCP: weather, injuries, news

        Args:
            match_id: Match identifier (e.g., "12345")

        Returns:
            Aggregated context dictionary with all data

        Raises:
            Exception: If critical data cannot be fetched
        """
        self.logger.debug(f"Aggregating context for match {match_id}")

        # Create MCP clients
        data_mcp = self.mcp_factory.create("data")
        intelligence_mcp = self.mcp_factory.create("intelligence")

        # TODO: In production, match_id should be a UUID and we should look up team IDs
        # For now, assume match_id is UUID and extract team IDs from match details

        try:
            # Step 1: Get match details first to extract team IDs
            match_details_result = await data_mcp.call_tool("get_match_details", {"match_id": match_id})

            # Extract team IDs from match details
            if isinstance(match_details_result, Exception) or not match_details_result.get("match"):
                raise ValueError(f"Could not fetch match details for match_id: {match_id}")

            match_data = match_details_result["match"]
            home_team_id = match_data.get("home_team_id")
            away_team_id = match_data.get("away_team_id")
            external_id = match_data.get("external_id")  # API-Football fixture ID (integer)
            # Use league_external_id (API-Football integer ID), NOT league_id (internal UUID)
            league_external_id = match_data.get("league_external_id")  # API-Football league ID (integer)

            # Handle both string and dict formats for team names
            home_team = match_data.get("home_team")
            away_team = match_data.get("away_team")
            home_team_name = home_team if isinstance(home_team, str) else (home_team.get("name", "Unknown") if isinstance(home_team, dict) else "Unknown")
            away_team_name = away_team if isinstance(away_team, str) else (away_team.get("name", "Unknown") if isinstance(away_team, dict) else "Unknown")

            # Extract season from match date dynamically
            match_date_str = match_data.get("scheduled_at") or match_data.get("date")
            if not match_date_str:
                raise ValueError(f"Match date not found in match details: {match_id}")
            season = self.extract_season_from_date(match_date_str)

            # Helper coroutine to return None (for asyncio.gather compatibility)
            async def return_none():
                return None

            # Get external team IDs for MCP calls that need integers
            home_team_external_id = match_data.get("home_team_external_id")
            away_team_external_id = match_data.get("away_team_external_id")

            # Step 2: Fetch all other data in parallel (skip tools that fail or aren't available)
            # Note: All items must be coroutines, not None, for asyncio.gather
            results = await asyncio.gather(
                # Sports data (all need external integer IDs from API-Football)
                # Team stats needs external team_id (int), league_external_id (int), and season (str)
                data_mcp.call_tool("get_team_stats", {"team_id": int(home_team_external_id), "league_id": int(league_external_id), "season": season}) if home_team_external_id and league_external_id else return_none(),
                data_mcp.call_tool("get_team_stats", {"team_id": int(away_team_external_id), "league_id": int(league_external_id), "season": season}) if away_team_external_id and league_external_id else return_none(),
                # Head-to-head needs external team IDs (integers)
                data_mcp.call_tool("get_head_to_head", {"home_team_id": int(home_team_external_id), "away_team_id": int(away_team_external_id)}) if home_team_external_id and away_team_external_id else return_none(),
                # Form data uses team UUIDs (string)
                data_mcp.call_tool("get_form_data", {"team_id": home_team_id, "num_matches": 5}) if home_team_id else return_none(),
                data_mcp.call_tool("get_form_data", {"team_id": away_team_id, "num_matches": 5}) if away_team_id else return_none(),
                # Match odds uses external fixture ID (integer)
                data_mcp.call_tool("get_match_odds", {"fixture_id": int(external_id)}) if external_id else return_none(),
                # Intelligence data (skip weather for now due to RedisCache error)
                return_none(),  # intelligence_mcp.call_tool("get_match_weather", {"match_id": match_id}),
                # Injuries and lineups (skip - tools not registered in MCP yet)
                return_none(),  # data_mcp.call_tool("get_injuries", {"fixture_id": int(external_id)}) if external_id else return_none(),
                return_none(),  # data_mcp.call_tool("get_lineups", {"fixture_id": int(external_id)}) if external_id else return_none(),
                return_exceptions=True,
            )

            # Unpack results
            (
                home_stats,
                away_stats,
                head_to_head,
                home_form,
                away_form,
                odds,
                weather,
                injuries,  # Single call returns injuries for both teams
                lineups,   # Single call returns lineups for both teams
            ) = results

            # Build aggregated context
            context = {
                "match_id": match_id,
                "fixture": match_data,  # Already fetched in step 1
                "home_team": {
                    "id": home_team_id,
                    "name": home_team_name,
                    "stats": home_stats if not isinstance(home_stats, Exception) else None,
                    "form": home_form if not isinstance(home_form, Exception) else None,
                },
                "away_team": {
                    "id": away_team_id,
                    "name": away_team_name,
                    "stats": away_stats if not isinstance(away_stats, Exception) else None,
                    "form": away_form if not isinstance(away_form, Exception) else None,
                },
                "head_to_head": head_to_head if not isinstance(head_to_head, Exception) else None,
                "odds": odds if not isinstance(odds, Exception) else None,
                "weather": weather if not isinstance(weather, Exception) else None,
                # Injuries and lineups at top level (cover both teams)
                "injuries": injuries if not isinstance(injuries, Exception) else None,
                "lineups": lineups if not isinstance(lineups, Exception) else None,
            }

            self.logger.info(
                f"Context aggregation complete for match {match_id}",
                extra={"data_points": len([v for v in context.values() if v is not None])},
            )

            return context

        except Exception as e:
            self.logger.error(
                f"Failed to aggregate context for match {match_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise

    async def evaluate_all_markets(
        self,
        match_id: str,
        top_n: int = 3,
        min_probability: float = 0.5,
    ) -> dict[str, Any]:
        """
        Evaluate all 44 betting markets for a fixture and return top N.

        This method:
        1. Resolves match to get team/league IDs
        2. Creates MarketEvaluator with Data MCP client
        3. Evaluates all 44 markets using statistical tools
        4. Ranks markets by weighted probability
        5. Returns top N markets with highest success probability

        Args:
            match_id: Match identifier (UUID or natural language)
            top_n: Number of top markets to return (default: 3)
            min_probability: Minimum probability threshold (default: 0.5)

        Returns:
            Dictionary with fixture info, all market evaluations, and top markets

        Example:
            >>> result = await orchestrator.evaluate_all_markets("match-uuid", top_n=3)
            >>> print(result["top_markets"][0])
            {
                "rank": 1,
                "market_code": "CHANCEMIX_1X2_OU25",
                "market_name": "Chance Mix 1X2 or Total 2.5",
                "best_outcome": "Home or Over",
                "probability": 0.8571,
                ...
            }
        """
        self.logger.info(f"Evaluating all 44 markets for match: {match_id}")

        # Step 1: Resolve match ID if natural language
        resolved_match_id = await self.resolve_match_id(match_id)

        # Step 2: Get match details to extract team/league IDs
        data_mcp = self.mcp_factory.create("data")

        match_details_result = await data_mcp.call_tool(
            "get_match_details", {"match_id": resolved_match_id}
        )

        if isinstance(match_details_result, Exception) or not match_details_result.get("match"):
            raise ValueError(f"Could not fetch match details for match_id: {resolved_match_id}")

        match_data = match_details_result["match"]

        # Extract API-Football IDs (integers) for Data MCP tools
        home_team_external_id = match_data.get("home_team_external_id")
        away_team_external_id = match_data.get("away_team_external_id")
        league_external_id = match_data.get("league_external_id")

        if not all([home_team_external_id, away_team_external_id, league_external_id]):
            raise ValueError(
                f"Missing external IDs for match. home={home_team_external_id}, "
                f"away={away_team_external_id}, league={league_external_id}"
            )

        # Handle team names (can be string or dict)
        home_team = match_data.get("home_team")
        away_team = match_data.get("away_team")
        home_team_name = (
            home_team if isinstance(home_team, str)
            else (home_team.get("name", "Unknown") if isinstance(home_team, dict) else "Unknown")
        )
        away_team_name = (
            away_team if isinstance(away_team, str)
            else (away_team.get("name", "Unknown") if isinstance(away_team, dict) else "Unknown")
        )

        # Step 3: Initialize MarketEvaluator with Data MCP client
        if self._market_evaluator is None:
            self._market_evaluator = MarketEvaluator(data_mcp)

        # Step 4: Evaluate all 44 markets
        self.logger.info(
            f"Evaluating markets for: {home_team_name} vs {away_team_name} "
            f"(IDs: {home_team_external_id} vs {away_team_external_id}, league: {league_external_id})"
        )

        all_evaluations = await self._market_evaluator.evaluate_all_markets(
            home_team_id=int(home_team_external_id),
            away_team_id=int(away_team_external_id),
            league_id=int(league_external_id),
        )

        # Step 5: Get top N markets by probability
        top_markets = self._market_evaluator.get_top_markets(
            evaluations=all_evaluations,
            top_n=top_n,
            min_probability=min_probability,
        )

        # Step 6: Build response
        result = {
            "fixture": {
                "id": resolved_match_id,
                "external_id": match_data.get("external_id"),
                "home_team": home_team_name,
                "away_team": away_team_name,
                "league": match_data.get("league_name", match_data.get("league", "Unknown")),
                "scheduled_at": match_data.get("scheduled_at"),
            },
            "markets_evaluated": len(all_evaluations),
            "top_markets": top_markets,
            "all_evaluations": [e.to_dict() for e in all_evaluations],
            "recommendation": self._generate_market_recommendation(top_markets),
        }

        self.logger.info(
            f"Market evaluation complete: {len(all_evaluations)} markets evaluated, "
            f"{len(top_markets)} top markets returned"
        )

        return result

    def _generate_market_recommendation(self, top_markets: list[dict]) -> str:
        """Generate a recommendation based on top markets.

        Args:
            top_markets: List of top market dictionaries

        Returns:
            Recommendation string
        """
        if not top_markets:
            return "No markets meet the minimum probability threshold"

        top = top_markets[0]
        prob = top.get("probability", 0)
        market_name = top.get("market_name", "Unknown")
        best_outcome = top.get("best_outcome", "Unknown")

        if prob >= 0.8:
            return f"STRONG BET on {market_name} - {best_outcome} ({prob*100:.1f}% probability)"
        elif prob >= 0.65:
            return f"PLACE BET on {market_name} - {best_outcome} ({prob*100:.1f}% probability)"
        elif prob >= 0.5:
            return f"CONSIDER {market_name} - {best_outcome} ({prob*100:.1f}% probability)"
        else:
            return f"MARGINAL: {market_name} - {best_outcome} ({prob*100:.1f}% probability)"

    async def load_agent_tools(self) -> dict[str, list[Any]]:
        """
        Load all tools needed for agents (MCP tools + Python functions).

        This method is cached to avoid re-loading tools on every prediction.

        Returns:
            Dict with "mcp_data_tools", "mcp_intelligence_tools", "function_tools"

        Example:
            >>> tools = await orchestrator.load_agent_tools()
            >>> data_tools = tools["mcp_data_tools"]
            >>> ml_tools = tools["function_tools"]
        """
        if self._tools_cache is not None:
            self.logger.debug("Using cached tools")
            return self._tools_cache

        self.logger.debug("Loading agent tools...")

        # Load MCP tools from both servers
        mcp_data_tools = await self.mcp_factory.get_tools_for_agent("data")
        mcp_intelligence_tools = await self.mcp_factory.get_tools_for_agent("intelligence")

        # Load Python function tools
        from sipap.tools.function import statistical, web

        function_tools = [
            statistical.poisson_model,
            statistical.xg_calculator,
            statistical.elo_rating,
            statistical.form_score,
            web.web_fetch,  # For News Agent to fetch news content
        ]

        # Cache tools
        self._tools_cache = {
            "mcp_data_tools": mcp_data_tools,
            "mcp_intelligence_tools": mcp_intelligence_tools,
            "function_tools": function_tools,
        }

        self.logger.info(
            "Tools loaded successfully",
            extra={
                "mcp_data_tools_count": len(mcp_data_tools),
                "mcp_intelligence_tools_count": len(mcp_intelligence_tools),
                "function_tools_count": len(function_tools),
            },
        )

        return self._tools_cache

    async def run_agent_predictions(
        self,
        context: dict[str, Any],
        market: str = "1X2",
    ) -> list[dict[str, Any]]:
        """
        Execute all 5 specialized agents and collect their predictions.

        This is the core prediction pipeline that:
        1. Loads all required tools (MCP + Python functions)
        2. Creates 5 specialized agents with their tools
        3. Executes all agents in parallel
        4. Parses their structured outputs
        5. Returns agent predictions for ensemble

        Args:
            context: Aggregated match context from aggregate_context()
            market: Betting market (1X2, BTTS, OU2.5)

        Returns:
            List of agent prediction dictionaries

        Example:
            >>> context = await orchestrator.aggregate_context("12345")
            >>> predictions = await orchestrator.run_agent_predictions(context, "1X2")
            >>> assert len(predictions) == 5  # 5 agents
        """
        # Only log if DEBUG enabled
        if self.debug_enabled:
            self.logger.debug(f"Running agent predictions for market: {market}")

        # Step 1: Load all tools
        tools = await self.load_agent_tools()
        data_tools = tools["mcp_data_tools"]
        tools["mcp_intelligence_tools"]
        func_tools = tools["function_tools"]

        # Step 2: Define agent-specific tool combinations
        agent_tools = {
            "statistical": data_tools + func_tools[:4],  # Data + statistical functions (poisson, xg, elo, form_score)
            "form": data_tools + [func_tools[3]],  # Data + form_score
            "market": data_tools,  # Data only (odds)
            "news": data_tools + [func_tools[4]],  # Data + web_fetch for news fetching
        }

        # Step 3: Create prediction prompt
        import json

        prompt = f"""
Generate a prediction for this soccer match.

**Market:** {market}

**Match Context:**
```json
{json.dumps(context, indent=2, default=str)}
```

**Instructions:**
1. Analyze the provided context data
2. Use available tools to gather any additional insights
3. Generate your prediction with probability (0-1) and confidence (0-100)
4. Provide clear reasoning and evidence
5. Return structured output according to the defined schema

Focus on your specialized analysis approach based on your role.
"""

        # Step 4: Create agents (3-agent ensemble: Statistical, Form, News)
        # Create agents (only log if DEBUG enabled)
        if self.debug_enabled:
            self.logger.debug("Creating agents...")
        agents: dict[str, Any] = {}
        for agent_name in ["statistical", "form", "news"]:
            try:
                agent = self.agent_factory.create(agent_name, tools=agent_tools[agent_name])
                agents[agent_name] = agent
                if self.debug_enabled:
                    self.logger.debug(f"Created agent: {agent_name}")
            except Exception as e:
                # Always log errors
                self.logger.error(
                    f"Failed to create agent: {agent_name}",
                    extra={"error": str(e)},
                    exc_info=True,
                )
                # Continue without this agent (graceful degradation)

        if not agents:
            raise RuntimeError("Failed to create any agents")

        # Step 5: Execute all agents in parallel
        if self.debug_enabled:
            self.logger.debug(f"Executing {len(agents)} agents in parallel for market: {market}")

        async def run_agent(name: str, agent: Any) -> tuple[str, Any]:
            """Execute single agent and return (name, result)."""
            try:
                # Use invoke_async for proper async invocation of Strands agents
                # agent(prompt) returns AgentResult synchronously, not an awaitable
                result = await agent.invoke_async(prompt)
                # Only log individual agent completion if DEBUG enabled
                if self.debug_enabled:
                    self.logger.debug(f"Agent {name} completed")
                return (name, result)
            except Exception as e:
                # Always log errors
                self.logger.error(
                    f"Agent {name} failed",
                    extra={"error": str(e)},
                    exc_info=True,
                )
                return (name, e)

        # Run all agents concurrently
        results = await asyncio.gather(
            *[run_agent(name, agent) for name, agent in agents.items()],
            return_exceptions=False,
        )

        # Step 6: Parse agent outputs
        predictions = []
        for agent_name, result in results:
            if isinstance(result, Exception):
                self.logger.warning(f"Skipping failed agent: {agent_name}")
                continue

            try:
                # Extract structured output
                if hasattr(result, "structured_output") and result.structured_output:
                    structured = result.structured_output
                    prediction_data = {
                        "agent": agent_name,
                        "prediction": {
                            "market": structured.prediction.get("market", market),
                            "outcome": structured.prediction.get("outcome", "Unknown"),
                            "probability": structured.prediction.get("probability", 0.5),
                            "confidence": structured.prediction.get("confidence", 50),
                        },
                        "reasoning": structured.reasoning,
                        "evidence": structured.evidence,
                        "metadata": structured.metadata if hasattr(structured, "metadata") else {},
                    }
                    # Only log individual agent predictions if DEBUG enabled
                    if self.debug_enabled:
                        self.logger.debug(
                            f"Agent {agent_name} → {prediction_data['prediction']['outcome']} "
                            f"(prob: {prediction_data['prediction']['probability']:.2f}, "
                            f"conf: {prediction_data['prediction']['confidence']})"
                        )
                else:
                    # Fallback: try to parse from result object
                    self.logger.warning(
                        f"Agent {agent_name} returned no structured output, attempting fallback parse"
                    )
                    # Create a default prediction
                    prediction_data = {
                        "agent": agent_name,
                        "prediction": {
                            "market": market,
                            "outcome": "Unknown",
                            "probability": 0.5,
                            "confidence": 50,
                        },
                        "reasoning": "Agent output parsing failed",
                        "evidence": [],
                        "metadata": {},
                    }

                predictions.append(prediction_data)
                # Parsing details only if DEBUG enabled
                if self.debug_enabled:
                    self.logger.debug(
                        f"Parsed prediction from {agent_name}",
                        extra={"prediction": prediction_data["prediction"]},
                    )

            except Exception as e:
                self.logger.error(
                    f"Failed to parse output from agent: {agent_name}",
                    extra={"error": str(e)},
                    exc_info=True,
                )
                # Continue without this prediction

        if not predictions:
            raise RuntimeError("No agent predictions were successfully generated")

        # Log summary with agent outcomes (INFO - always visible)
        agent_summary = ", ".join([
            f"{p['agent'][0].upper()}={p['prediction']['probability']:.2f}"
            for p in predictions
        ])
        self.logger.info(f"🤖 Agents [{agent_summary}] → {len(predictions)}/{len(agents)} succeeded")

        return predictions

    def validate_context_quality(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Validate that aggregated context has sufficient data quality.

        Quality checks:
        1. Critical fields present (fixture, odds, team stats)
        2. At least 70% of data points available
        3. No critical data fetch failures

        Args:
            context: Aggregated context dictionary

        Returns:
            Validation result with status and missing fields
        """
        # Only log validation details if DEBUG enabled
        if self.debug_enabled:
            self.logger.debug("Validating context quality")

        # Define critical fields
        critical_fields = [
            ("fixture", context.get("fixture")),
            ("odds", context.get("odds")),
            ("home_stats", context.get("home_team", {}).get("stats")),
            ("away_stats", context.get("away_team", {}).get("stats")),
        ]

        # Define optional fields (nice to have)
        optional_fields = [
            ("home_form", context.get("home_team", {}).get("form")),
            ("away_form", context.get("away_team", {}).get("form")),
            ("injuries", context.get("injuries")),
            ("lineups", context.get("lineups")),
            ("head_to_head", context.get("head_to_head")),
            ("weather", context.get("weather")),
        ]

        # Check critical fields
        missing_critical = [name for name, value in critical_fields if value is None]
        if missing_critical:
            return {
                "status": "FAILED",
                "reason": f"Missing critical fields: {', '.join(missing_critical)}",
                "missing_critical": missing_critical,
                "missing_optional": [],
                "data_completeness": 0.0,
            }

        # Check optional fields
        missing_optional = [name for name, value in optional_fields if value is None]
        total_fields = len(critical_fields) + len(optional_fields)
        available_fields = total_fields - len(missing_optional)
        data_completeness = (available_fields / total_fields) * 100

        # Quality gate: At least 70% data completeness
        if data_completeness < 70:
            return {
                "status": "FAILED",
                "reason": f"Data completeness below threshold: {data_completeness:.1f}% < 70%",
                "missing_critical": [],
                "missing_optional": missing_optional,
                "data_completeness": data_completeness,
            }

        # All gates passed
        self.logger.info(
            "Context validation passed",
            extra={"data_completeness": data_completeness},
        )

        return {
            "status": "PASSED",
            "reason": "All quality checks passed",
            "missing_critical": [],
            "missing_optional": missing_optional,
            "data_completeness": data_completeness,
        }

    async def save_prediction(
        self,
        match_id: str,
        prediction: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Save prediction to Aurora database for audit and analysis.

        Stores:
        - Prediction metadata (timestamp, match_id, market, outcome)
        - Ensemble results (probability, confidence, quality_gate)
        - Agent predictions (all 5 agent outputs)
        - Context data (aggregated match data)
        - Expected value calculation

        Args:
            match_id: Match identifier (UUID)
            prediction: Final ensemble prediction
            context: Aggregated match context

        Returns:
            Save result with prediction_id

        Raises:
            DatabaseError: If save operation fails
        """
        self.logger.debug(f"Saving prediction for match {match_id}")

        # Generate prediction ID
        prediction_id = uuid.uuid4()

        try:
            with self.db.get_session() as session:
                # Step 1: Insert into predictions table
                session.execute(
                    text(
                        """
                        INSERT INTO predictions (
                            id, match_id, user_id, market, outcome,
                            probability, confidence_score, ensemble_method, generated_at
                        ) VALUES (
                            :id, :match_id, :user_id, :market, :outcome,
                            :probability, :confidence_score, :ensemble_method, :generated_at
                        )
                        """
                    ),
                    {
                        "id": str(prediction_id),
                        "match_id": match_id,
                        "user_id": None,  # TODO: Extract from context when user auth is implemented
                        "market": prediction.get("market", "1X2"),
                        "outcome": prediction.get("outcome"),
                        "probability": float(prediction.get("probability", 0.0)),
                        "confidence_score": float(prediction.get("confidence", 0.0)),
                        "ensemble_method": "weighted_average",
                        "generated_at": datetime.now(),
                    },
                )

                # Step 2: Insert agent contributions
                agent_predictions = prediction.get("agent_predictions", [])
                for agent_pred in agent_predictions:
                    agent_name = agent_pred.get("agent")
                    agent_prob = agent_pred.get("prediction", {}).get("probability", 0.0)
                    agent_conf = agent_pred.get("confidence", 0.0)
                    reasoning = {
                        "reasoning": agent_pred.get("reasoning", ""),
                        "evidence": agent_pred.get("evidence", []),
                        "metadata": agent_pred.get("metadata", {}),
                    }

                    session.execute(
                        text(
                            """
                            INSERT INTO agent_contributions (
                                id, prediction_id, agent_name,
                                agent_probability, agent_confidence, reasoning
                            ) VALUES (
                                :id, :prediction_id, :agent_name,
                                :agent_probability, :agent_confidence, :reasoning::jsonb
                            )
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "prediction_id": str(prediction_id),
                            "agent_name": agent_name,
                            "agent_probability": float(agent_prob),
                            "agent_confidence": float(agent_conf),
                            "reasoning": json.dumps(reasoning),
                        },
                    )

                # Step 3: Insert prediction evidence (MCP context data)
                # Store aggregated context as evidence
                evidence_entries = [
                    {
                        "mcp_server": "data",
                        "evidence_type": "match_fixture",
                        "evidence_data": context.get("fixture", {}),
                        "weight": 1.0,
                    },
                    {
                        "mcp_server": "data",
                        "evidence_type": "odds_data",
                        "evidence_data": context.get("odds", {}),
                        "weight": 1.0,
                    },
                    {
                        "mcp_server": "data",
                        "evidence_type": "team_stats",
                        "evidence_data": {
                            "home": context.get("home_team", {}),
                            "away": context.get("away_team", {}),
                        },
                        "weight": 1.0,
                    },
                    {
                        "mcp_server": "intelligence",
                        "evidence_type": "weather_data",
                        "evidence_data": context.get("weather", {}),
                        "weight": 0.5,
                    },
                ]

                for evidence in evidence_entries:
                    # Skip if evidence data is empty
                    if not evidence["evidence_data"]:
                        continue

                    session.execute(
                        text(
                            """
                            INSERT INTO prediction_evidence (
                                id, prediction_id, mcp_server,
                                evidence_type, evidence_data, weight
                            ) VALUES (
                                :id, :prediction_id, :mcp_server,
                                :evidence_type, :evidence_data::jsonb, :weight
                            )
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "prediction_id": str(prediction_id),
                            "mcp_server": evidence["mcp_server"],
                            "evidence_type": evidence["evidence_type"],
                            "evidence_data": json.dumps(evidence["evidence_data"]),
                            "weight": float(evidence["weight"]),
                        },
                    )

                # Transaction committed automatically by DatabaseManager context manager

            self.logger.info(
                "Prediction saved to Aurora database",
                extra={
                    "prediction_id": str(prediction_id),
                    "match_id": match_id,
                    "agent_count": len(agent_predictions),
                },
            )

            return {
                "status": "SUCCESS",
                "prediction_id": str(prediction_id),
                "message": "Prediction saved to Aurora database",
            }

        except DatabaseError as e:
            self.logger.error(
                f"Failed to save prediction to database: {e}",
                exc_info=True,
                extra={"match_id": match_id},
            )
            return {
                "status": "FAILED",
                "prediction_id": None,
                "message": f"Database error: {str(e)}",
            }
        except Exception as e:
            self.logger.error(
                f"Unexpected error saving prediction: {e}",
                exc_info=True,
                extra={"match_id": match_id},
            )
            return {
                "status": "FAILED",
                "prediction_id": None,
                "message": f"Unexpected error: {str(e)}",
            }

    def calculate_expected_value(
        self,
        prediction: dict[str, Any],
        odds: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Calculate expected value (+EV) for a prediction.

        Expected Value (EV) formula:
            EV = (Probability × Payout) - (1 - Probability × Stake)
            +EV when: Our probability > Implied probability from odds

        Args:
            prediction: Ensemble prediction with probability
            odds: Market odds for the outcome

        Returns:
            Expected value analysis with recommendation

        Example:
            >>> prediction = {"outcome": "Home Win", "probability": 0.60}
            >>> odds = {"Home Win": 2.0}  # Decimal odds
            >>> result = calculate_expected_value(prediction, odds)
            >>> print(result)
            {
                "expected_value": 0.20,
                "is_positive_ev": True,
                "recommendation": "PLACE BET",
                ...
            }
        """
        outcome_raw = prediction.get("outcome")
        our_probability = prediction.get("probability", 0)

        # Ensure outcome is a string
        if not isinstance(outcome_raw, str):
            self.logger.warning(f"Invalid outcome type: {type(outcome_raw)} - {outcome_raw}")
            return {
                "expected_value": 0.0,
                "odds": 0.0,
                "is_positive_ev": False,
                "recommendation": "SKIP - Invalid outcome type",
                "reason": f"Outcome must be a string, got {type(outcome_raw)}",
            }

        outcome: str = outcome_raw

        # Get odds for this outcome
        outcome_odds = odds.get(outcome)
        if not outcome_odds:
            self.logger.warning(
                f"No odds found for outcome '{outcome}'. Available odds keys: {list(odds.keys())}"
            )
            return {
                "expected_value": 0.0,
                "odds": 0.0,
                "is_positive_ev": False,
                "recommendation": "SKIP - No odds available",
                "reason": f"No odds found for outcome: {outcome}. Available: {list(odds.keys())}",
            }

        # Convert decimal odds to implied probability
        # Implied probability = 1 / decimal_odds
        implied_probability = 1 / outcome_odds

        # Calculate expected value
        # EV = (our_prob × (odds - 1)) - ((1 - our_prob) × 1)
        # Simplified: EV = (our_prob × odds) - 1
        expected_value = (our_probability * outcome_odds) - 1

        # +EV threshold: At least 5% edge
        ev_threshold = 0.05
        is_positive_ev = expected_value >= ev_threshold

        # Edge calculation
        edge = our_probability - implied_probability

        self.logger.info(
            "Expected value calculated",
            extra={
                "outcome": outcome,
                "our_probability": our_probability,
                "implied_probability": implied_probability,
                "expected_value": expected_value,
                "edge": edge,
                "is_positive_ev": is_positive_ev,
            },
        )

        # Build recommendation
        if is_positive_ev and edge > 0.1:
            recommendation = "STRONG BET - High +EV opportunity"
        elif is_positive_ev:
            recommendation = "PLACE BET - Positive expected value"
        elif expected_value > 0:
            recommendation = "MARGINAL - Small +EV, below threshold"
        else:
            recommendation = "SKIP - Negative expected value"

        return {
            "expected_value": round(expected_value, 4),
            "edge": round(edge, 4),
            "is_positive_ev": is_positive_ev,
            "our_probability": round(our_probability, 4),
            "implied_probability": round(implied_probability, 4),
            "odds": outcome_odds,
            "recommendation": recommendation,
        }

    def _calculate_ensemble(self, agent_predictions: list[dict[str, Any]], market: str) -> dict[str, Any]:
        """
        Calculate weighted ensemble from all agent predictions.

        Args:
            agent_predictions: List of predictions from all agents
            market: Betting market (1X2, BTTS, OU2.5)

        Returns:
            Ensemble prediction dictionary
        """
        # Weighted average (3-agent ensemble - ML removed from MVP)
        weights = {
            "statistical": 0.40,  # Primary: Long-term statistical analysis (6 seasons)
            "form": 0.40,         # Primary: Recent performance patterns (10-15 matches)
            "news": 0.20,         # Contextual: Current reality adjustments (injuries, suspensions)
        }

        # Extract probabilities and calculate weighted average
        probabilities = [
            p["prediction"]["probability"] * weights[p["agent"]]
            for p in agent_predictions
        ]

        ensemble_probability = sum(probabilities)

        # Confidence based on agent agreement
        confidence = self._calculate_agreement(agent_predictions)

        return {
            "market": market,
            "outcome": self._select_outcome(agent_predictions),
            "probability": round(ensemble_probability, 4),
            "confidence": round(confidence, 0),
            "agent_predictions": agent_predictions,
            "reasoning": self._generate_reasoning(agent_predictions),
            "evidence": self._aggregate_evidence(agent_predictions)
        }

    def _calculate_agreement(self, predictions: list[dict[str, Any]]) -> float:
        """
        Calculate confidence from agent agreement.

        Args:
            predictions: List of agent predictions

        Returns:
            Confidence score (0-100)
        """
        # Extract probabilities
        probs = [p["prediction"]["probability"] for p in predictions]

        # Standard deviation of probabilities
        std_dev = statistics.stdev(probs) if len(probs) > 1 else 0

        # Low std dev = high agreement = high confidence
        # Scale std_dev more aggressively: std_dev of 0.3 → ~40% confidence
        # Formula: confidence = (1 - min(std_dev * 2, 1.0)) * 100
        confidence = (1 - min(std_dev * 2, 1.0)) * 100

        return max(0, min(100, confidence))

    def _select_outcome(self, predictions: list[dict[str, Any]]) -> str:
        """
        Select most common outcome from agents (majority vote).

        Args:
            predictions: List of agent predictions

        Returns:
            Most common outcome
        """
        outcomes = [p["prediction"]["outcome"] for p in predictions]
        most_common = Counter(outcomes).most_common(1)
        return str(most_common[0][0]) if most_common else ""

    def _generate_reasoning(self, predictions: list[dict[str, Any]]) -> str:
        """
        Aggregate reasoning from all agents.

        Args:
            predictions: List of agent predictions

        Returns:
            Combined reasoning string
        """
        reasons = [f"{p['agent']}: {p['reasoning']}" for p in predictions]
        return " | ".join(reasons)

    def _aggregate_evidence(self, predictions: list[dict[str, Any]]) -> list[str]:
        """
        Aggregate evidence from all agents.

        Args:
            predictions: List of agent predictions

        Returns:
            List of all evidence items
        """
        evidence = []
        for p in predictions:
            evidence.extend(p.get("evidence", []))
        return evidence

    def _apply_quality_gates(self, ensemble: dict[str, Any], agent_predictions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Apply quality gates to final prediction.

        Quality Gates:
        1. Minimum confidence threshold (55%)
        2. Minimum probability threshold (50%)
        3. Minimum agent consensus (2/3 agents agree)

        Args:
            ensemble: Ensemble prediction
            agent_predictions: List of agent predictions

        Returns:
            Prediction with quality gate status
        """
        # Quality Gate 1: Minimum confidence threshold
        if ensemble["confidence"] < 55:
            return {
                **ensemble,
                "quality_gate": "FAILED",
                "reason": "Confidence below threshold (55%)",
                "recommendation": "Do not place bet"
            }

        # Quality Gate 2: Minimum probability threshold
        if ensemble["probability"] < 0.50:
            return {
                **ensemble,
                "quality_gate": "FAILED",
                "reason": "Probability below threshold (50%)",
                "recommendation": "Do not place bet"
            }

        # Quality Gate 3: Agent consensus (at least 2/3 agree)
        outcome_counts = Counter([p["prediction"]["outcome"] for p in agent_predictions])
        max_count = max(outcome_counts.values())
        if max_count < 2:
            return {
                **ensemble,
                "quality_gate": "FAILED",
                "reason": "Insufficient agent consensus (< 2/3)",
                "recommendation": "Do not place bet"
            }

        # All gates passed
        return {
            **ensemble,
            "quality_gate": "PASSED",
            "recommendation": "Prediction ready for user"
        }

    async def build_accumulator(
        self,
        target_odds: float,
        date: str | None = None,
        min_probability: float = 0.65,
        max_selections: int = 10,
        league_ids: list[int] | None = None,
        market_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Build accumulator bet meeting target cumulative odds.

        This method:
        1. Gets fixtures for the specified date (default: today)
        2. Evaluates markets for each fixture with odds (filtered if market_codes provided)
        3. Picks top 1 probability market per fixture
        4. Builds accumulator by selecting fixtures until cumulative odds >= target
        5. Returns selections with fixture, market, outcome, probability, odds

        Args:
            target_odds: Target cumulative odds (e.g., 10.0 for "10 odds")
            date: Date to evaluate (default: today, format: YYYY-MM-DD)
            min_probability: Minimum probability threshold (default: 0.65)
            max_selections: Maximum number of selections (default: 10)
            league_ids: Optional list of league IDs to filter fixtures
            market_codes: Optional list of market codes to evaluate.
                         If None, evaluates all 44 markets.
                         If provided, only evaluates and selects from
                         these specific markets (e.g., ["BTTS", "1X2", "DC"]).

        Returns:
            Dictionary with:
            - target_odds: The requested target
            - achieved_odds: Actual cumulative odds achieved
            - target_met: Whether target was achieved
            - selection_count: Number of selections
            - selections: List of selection dictionaries
            - total_probability: Combined probability (product)
            - recommendation: Bet recommendation string
            - market_codes: The market codes used for filtering (if any)

        Raises:
            ValueError: If any market code is invalid

        Example:
            >>> # Build accumulator from all markets (original behavior)
            >>> result = await orchestrator.build_accumulator(
            ...     target_odds=10.0,
            ...     min_probability=0.65
            ... )

            >>> # Build accumulator from BTTS only
            >>> result = await orchestrator.build_accumulator(
            ...     target_odds=5.0,
            ...     market_codes=["BTTS"]
            ... )

            >>> # Build accumulator from specific markets
            >>> result = await orchestrator.build_accumulator(
            ...     target_odds=8.0,
            ...     market_codes=["1X2", "DC", "DNB"],
            ...     min_probability=0.70
            ... )
        """
        from datetime import datetime as dt, timezone

        market_filter_msg = f", markets={market_codes}" if market_codes else ""
        self.logger.info(f"Building accumulator: target={target_odds} odds, min_prob={min_probability}{market_filter_msg}")

        # Default date is today
        if date is None:
            date = dt.now(timezone.utc).strftime("%Y-%m-%d")

        # Step 1: Get fixtures for the date
        data_mcp = self.mcp_factory.create("data")

        # Get API client for odds fetching
        # Note: This requires the API-Football client to be configured
        api_client = None
        try:
            from sipap_data_mcp.api.football_client import APIFootballClient
            from sipap_data_mcp.cache.redis import RedisCache
            import os

            api_key = os.environ.get("API_FOOTBALL_KEY", "")
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

            if api_key:
                cache = RedisCache(url=redis_url)
                await cache.connect()
                api_client = APIFootballClient(api_key=api_key, cache=cache)
                await api_client.connect()
        except ImportError:
            self.logger.warning("sipap_data_mcp not available, odds fetching disabled")
        except Exception as e:
            self.logger.warning(f"Failed to initialize API client: {e}")

        # Fetch fixtures from database/MCP
        try:
            fixtures_result = await data_mcp.call_tool(
                "search_fixtures_by_date",
                {"date": date, "league_ids": league_ids or []},
            )
            fixtures = fixtures_result.get("fixtures", []) if not isinstance(fixtures_result, Exception) else []
        except Exception as e:
            self.logger.warning(f"Failed to fetch fixtures: {e}")
            fixtures = []

        if not fixtures:
            return {
                "target_odds": target_odds,
                "achieved_odds": 0.0,
                "target_met": False,
                "selection_count": 0,
                "selections": [],
                "total_probability": 0.0,
                "recommendation": f"NO FIXTURES - No fixtures found for {date}",
            }

        # Initialize MarketEvaluator if needed
        if self._market_evaluator is None:
            self._market_evaluator = MarketEvaluator(data_mcp)

        # Step 2: Process fixtures and build accumulator
        selections: list[dict[str, Any]] = []
        cumulative_odds = 1.0
        cumulative_probability = 1.0
        processed_fixtures = 0

        self.logger.info(f"Processing {len(fixtures)} fixtures for accumulator")

        for fixture in fixtures:
            # Check if we've met the target
            if cumulative_odds >= target_odds:
                break
            if len(selections) >= max_selections:
                break

            # Extract fixture details
            fixture_id = fixture.get("id") or fixture.get("external_id")
            external_id = fixture.get("external_id")
            home_team_external_id = fixture.get("home_team_external_id")
            away_team_external_id = fixture.get("away_team_external_id")
            league_external_id = fixture.get("league_external_id")

            # Skip if missing required IDs
            if not all([external_id, home_team_external_id, away_team_external_id, league_external_id]):
                self.logger.debug(f"Skipping fixture {fixture_id}: missing external IDs")
                continue

            processed_fixtures += 1

            # Get team names
            home_team = fixture.get("home_team")
            away_team = fixture.get("away_team")
            home_team_name = (
                home_team if isinstance(home_team, str)
                else (home_team.get("name", "Unknown") if isinstance(home_team, dict) else "Unknown")
            )
            away_team_name = (
                away_team if isinstance(away_team, str)
                else (away_team.get("name", "Unknown") if isinstance(away_team, dict) else "Unknown")
            )

            try:
                # Evaluate markets for this fixture (filtered if market_codes provided)
                if api_client:
                    # Use evaluate_all_markets_with_odds for odds integration
                    evaluations = await self._market_evaluator.evaluate_all_markets_with_odds(
                        home_team_id=int(home_team_external_id),
                        away_team_id=int(away_team_external_id),
                        league_id=int(league_external_id),
                        fixture_id=int(external_id),
                        api_client=api_client,
                        top_n=1,
                        min_probability=min_probability,
                        market_codes=market_codes,
                    )
                else:
                    # Fallback: evaluate without odds
                    evaluations = await self._market_evaluator.evaluate_all_markets(
                        home_team_id=int(home_team_external_id),
                        away_team_id=int(away_team_external_id),
                        league_id=int(league_external_id),
                        market_codes=market_codes,
                    )

                # Get top market meeting threshold
                top_markets = self._market_evaluator.get_top_markets(
                    evaluations=evaluations,
                    top_n=1,
                    min_probability=min_probability,
                )

                if not top_markets:
                    self.logger.debug(f"No markets meet threshold for {home_team_name} vs {away_team_name}")
                    continue

                top = top_markets[0]
                odds = top.get("best_odds")

                # Skip if no odds available
                if not odds or odds <= 1.0:
                    self.logger.debug(f"No valid odds for {home_team_name} vs {away_team_name}")
                    continue

                # Add to accumulator
                selection = {
                    "fixture_id": str(fixture_id),
                    "external_id": int(external_id),
                    "fixture": f"{home_team_name} vs {away_team_name}",
                    "scheduled_at": fixture.get("scheduled_at"),
                    "league": fixture.get("league_name", fixture.get("league", "Unknown")),
                    "market_code": top.get("market_code"),
                    "market_name": top.get("market_name"),
                    "outcome": top.get("best_outcome"),
                    "probability": top.get("probability"),
                    "odds": odds,
                    "bookmaker": top.get("best_odds_bookmaker", "Unknown"),
                }

                selections.append(selection)
                cumulative_odds *= odds
                cumulative_probability *= top.get("probability", 0.5)

                self.logger.info(
                    f"Added: {home_team_name} vs {away_team_name} | "
                    f"{top.get('best_outcome')} @ {odds} | "
                    f"Cumulative: {cumulative_odds:.2f}"
                )

            except Exception as e:
                self.logger.warning(f"Failed to evaluate {home_team_name} vs {away_team_name}: {e}")
                continue

        # Cleanup API client
        if api_client:
            try:
                await api_client.close()
            except Exception:
                pass

        # Step 3: Build response
        target_met = cumulative_odds >= target_odds

        result = {
            "target_odds": target_odds,
            "achieved_odds": round(cumulative_odds, 2),
            "target_met": target_met,
            "selection_count": len(selections),
            "fixtures_processed": processed_fixtures,
            "fixtures_available": len(fixtures),
            "date": date,
            "market_codes": market_codes,  # Include filter criteria
            "selections": selections,
            "total_probability": round(cumulative_probability, 4),
            "recommendation": self._generate_accumulator_recommendation(
                target_odds, cumulative_odds, cumulative_probability, len(selections)
            ),
        }

        self.logger.info(
            f"Accumulator built: {len(selections)} selections, "
            f"{cumulative_odds:.2f} odds, {cumulative_probability*100:.1f}% combined probability"
        )

        return result

    def _generate_accumulator_recommendation(
        self,
        target: float,
        achieved: float,
        probability: float,
        count: int,
    ) -> str:
        """Generate recommendation for accumulator bet.

        Args:
            target: Target cumulative odds
            achieved: Achieved cumulative odds
            probability: Combined probability
            count: Number of selections

        Returns:
            Recommendation string
        """
        if achieved < target:
            return (
                f"INCOMPLETE - Only achieved {achieved:.2f} odds from {count} selections. "
                f"Need more fixtures to reach {target:.2f} target."
            )
        if probability >= 0.30:
            return (
                f"STRONG BET - {achieved:.2f} odds achieved with "
                f"{probability*100:.1f}% combined probability from {count} selections"
            )
        if probability >= 0.15:
            return (
                f"PLACE BET - {achieved:.2f} odds achieved with "
                f"{probability*100:.1f}% combined probability from {count} selections"
            )
        return (
            f"RISKY BET - {achieved:.2f} odds achieved but only "
            f"{probability*100:.1f}% combined probability from {count} selections"
        )

    async def get_filtered_fixtures(
        self,
        market_codes: list[str],
        top_n: int = 10,
        date: str | None = None,
        min_probability: float = 0.60,
        league_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """
        Get top N fixtures ranked by probability for specific markets.

        This method evaluates ONLY the specified markets across all fixtures,
        ranks them by probability, and returns the top N selections with odds.

        Use this when users request specific market types, e.g.:
        - "Give me 10 BTTS picks with high probability"
        - "Show me the best Double Chance and Match Winner selections"

        Args:
            market_codes: List of market codes to evaluate (REQUIRED).
                         E.g., ["BTTS"], ["1X2", "DC", "DNB"]
            top_n: Number of top fixtures to return (default: 10)
            date: Date to evaluate (default: today, format: YYYY-MM-DD)
            min_probability: Minimum probability threshold (default: 0.60)
            league_ids: Optional list of league IDs to filter fixtures

        Returns:
            Dictionary with:
            - market_codes: The requested market codes
            - total_fixtures: Number of fixtures evaluated
            - total_evaluations: Number of market evaluations meeting threshold
            - selection_count: Number of selections returned
            - selections: Top N fixtures ranked by probability
            - filters_applied: Summary of filtering criteria

        Raises:
            ValueError: If market_codes is empty or contains invalid codes

        Examples:
            >>> # Get top 10 BTTS Yes picks
            >>> result = await orch.get_filtered_fixtures(
            ...     market_codes=["BTTS"],
            ...     top_n=10
            ... )

            >>> # Get top 5 Home Win or Double Chance picks
            >>> result = await orch.get_filtered_fixtures(
            ...     market_codes=["1X2", "DC"],
            ...     top_n=5,
            ...     min_probability=0.70
            ... )

            >>> # Get selections for specific markets from Premier League
            >>> result = await orch.get_filtered_fixtures(
            ...     market_codes=["BTTS", "OU2.5", "1X2"],
            ...     top_n=10,
            ...     league_ids=[39]  # Premier League
            ... )
        """
        from datetime import datetime as dt, timezone

        if not market_codes:
            raise ValueError("market_codes is required and cannot be empty")

        self.logger.info(
            f"Getting filtered fixtures: markets={market_codes}, top_n={top_n}, "
            f"min_prob={min_probability}"
        )

        # Default date is today
        if date is None:
            date = dt.now(timezone.utc).strftime("%Y-%m-%d")

        # Step 1: Get fixtures for the date
        data_mcp = self.mcp_factory.create("data")

        # Get API client for odds fetching
        api_client = None
        try:
            from sipap_data_mcp.api.football_client import APIFootballClient
            from sipap_data_mcp.cache.redis import RedisCache
            import os

            api_key = os.environ.get("API_FOOTBALL_KEY", "")
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

            if api_key:
                cache = RedisCache(url=redis_url)
                await cache.connect()
                api_client = APIFootballClient(api_key=api_key, cache=cache)
                await api_client.connect()
        except ImportError:
            self.logger.warning("sipap_data_mcp not available, odds fetching disabled")
        except Exception as e:
            self.logger.warning(f"Failed to initialize API client: {e}")

        # Fetch fixtures from database/MCP
        try:
            fixtures_result = await data_mcp.call_tool(
                "search_fixtures_by_date",
                {"date": date, "league_ids": league_ids or []},
            )
            fixtures = fixtures_result.get("fixtures", []) if not isinstance(fixtures_result, Exception) else []
        except Exception as e:
            self.logger.warning(f"Failed to fetch fixtures: {e}")
            fixtures = []

        if not fixtures:
            return {
                "market_codes": market_codes,
                "total_fixtures": 0,
                "total_evaluations": 0,
                "selection_count": 0,
                "selections": [],
                "filters_applied": {
                    "date": date,
                    "min_probability": min_probability,
                    "league_ids": league_ids,
                    "market_codes": market_codes,
                },
            }

        # Initialize MarketEvaluator if needed
        if self._market_evaluator is None:
            self._market_evaluator = MarketEvaluator(data_mcp)

        # Step 2: Evaluate all fixtures with filtered markets
        all_selections: list[dict[str, Any]] = []

        self.logger.info(f"Evaluating {len(fixtures)} fixtures for markets: {market_codes}")

        for fixture in fixtures:
            # Extract fixture details
            fixture_id = fixture.get("id") or fixture.get("external_id")
            external_id = fixture.get("external_id")
            home_team_external_id = fixture.get("home_team_external_id")
            away_team_external_id = fixture.get("away_team_external_id")
            league_external_id = fixture.get("league_external_id")

            # Skip if missing required IDs
            if not all([external_id, home_team_external_id, away_team_external_id, league_external_id]):
                continue

            # Get team names
            home_team = fixture.get("home_team")
            away_team = fixture.get("away_team")
            home_team_name = (
                home_team if isinstance(home_team, str)
                else (home_team.get("name", "Unknown") if isinstance(home_team, dict) else "Unknown")
            )
            away_team_name = (
                away_team if isinstance(away_team, str)
                else (away_team.get("name", "Unknown") if isinstance(away_team, dict) else "Unknown")
            )

            try:
                # Evaluate only the filtered markets for this fixture
                if api_client:
                    evaluations = await self._market_evaluator.evaluate_all_markets_with_odds(
                        home_team_id=int(home_team_external_id),
                        away_team_id=int(away_team_external_id),
                        league_id=int(league_external_id),
                        fixture_id=int(external_id),
                        api_client=api_client,
                        top_n=len(market_codes),  # Get all filtered markets
                        min_probability=0.0,  # Don't filter here, filter after
                        market_codes=market_codes,
                    )
                else:
                    evaluations = await self._market_evaluator.evaluate_all_markets(
                        home_team_id=int(home_team_external_id),
                        away_team_id=int(away_team_external_id),
                        league_id=int(league_external_id),
                        market_codes=market_codes,
                    )

                # Add all evaluations meeting the probability threshold
                for evaluation in evaluations:
                    if evaluation.best_outcome.weighted_probability >= min_probability:
                        all_selections.append({
                            "fixture_id": str(fixture_id),
                            "external_id": int(external_id),
                            "fixture": f"{home_team_name} vs {away_team_name}",
                            "scheduled_at": fixture.get("scheduled_at"),
                            "league": fixture.get("league_name", fixture.get("league", "Unknown")),
                            "market_code": evaluation.market_code,
                            "market_name": evaluation.market_name,
                            "outcome": evaluation.best_outcome.outcome_code,
                            "probability": evaluation.best_outcome.weighted_probability,
                            "confidence": evaluation.best_outcome.confidence,
                            "odds": evaluation.best_odds,
                            "bookmaker": evaluation.best_odds_bookmaker,
                        })

            except Exception as e:
                self.logger.warning(f"Failed to evaluate {home_team_name} vs {away_team_name}: {e}")
                continue

        # Cleanup API client
        if api_client:
            try:
                await api_client.close()
            except Exception:
                pass

        # Step 3: Sort by probability (highest first) and take top N
        all_selections.sort(key=lambda x: x["probability"], reverse=True)
        top_selections = all_selections[:top_n]

        result = {
            "market_codes": market_codes,
            "total_fixtures": len(fixtures),
            "total_evaluations": len(all_selections),
            "selection_count": len(top_selections),
            "selections": top_selections,
            "filters_applied": {
                "date": date,
                "min_probability": min_probability,
                "league_ids": league_ids,
                "market_codes": market_codes,
            },
        }

        self.logger.info(
            f"Filtered fixtures: {len(top_selections)}/{len(all_selections)} selections "
            f"from {len(fixtures)} fixtures for markets {market_codes}"
        )

        return result
