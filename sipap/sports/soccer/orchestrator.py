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

from sqlalchemy import text

from sipap.factory.agent import AgentToolFactory
from sipap.factory.mcp import MCPFactory
from sipap_common.database.manager import DatabaseManager
from sipap_common.exceptions import AgentError, DatabaseError, MCPError, PredictionError
from sipap_common.utils.retry import retry_with_backoff


class SoccerOrchestrator:
    """
    Coordinates 5 specialized agents to generate ensemble predictions.

    Agents:
    1. Statistical Agent - Poisson, xG, Elo
    2. ML Agent - XGBoost model
    3. Form Agent - Recent form analysis
    4. Market Agent - Betting market sentiment
    5. News Agent - Contextual news analysis

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

        self.logger.info("SoccerOrchestrator initialized")

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

        Football seasons span two calendar years:
        - August-December: current_year to next_year (e.g., "2024-2025")
        - January-July: previous_year to current_year (e.g., "2024-2025" for Jan 2025)

        Args:
            match_date: Match date as datetime object or ISO string

        Returns:
            Season string in format "YYYY-YYYY" (e.g., "2024-2025")

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
        # August-December: current year to next year
        # January-July: previous year to current year
        if month >= 8:  # August to December
            season = f"{year}-{year + 1}"
        else:  # January to July
            season = f"{year - 1}-{year}"

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
        self.logger.info(f"Resolving natural language match identifier: {match_identifier}")

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
        self.logger.info(f"Aggregating context for match {match_id}")

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
            home_team_name = match_data.get("home_team", {}).get("name", "Unknown")
            away_team_name = match_data.get("away_team", {}).get("name", "Unknown")

            # Extract season from match date dynamically
            match_date_str = match_data.get("scheduled_at") or match_data.get("date")
            if not match_date_str:
                raise ValueError(f"Match date not found in match details: {match_id}")
            season = self.extract_season_from_date(match_date_str)

            # Step 2: Fetch all other data in parallel
            results = await asyncio.gather(
                # Sports data (using correct tool names and parameters)
                data_mcp.call_tool("get_team_stats", {"team_id": home_team_id, "season": season}),
                data_mcp.call_tool("get_team_stats", {"team_id": away_team_id, "season": season}),
                data_mcp.call_tool("get_head_to_head", {"team1_id": home_team_id, "team2_id": away_team_id, "limit": 10}),
                data_mcp.call_tool("get_form_data", {"team_id": home_team_id, "num_matches": 5}),
                data_mcp.call_tool("get_form_data", {"team_id": away_team_id, "num_matches": 5}),
                data_mcp.call_tool("get_match_odds", {"match_id": match_id}),
                # Intelligence data (using correct parameters)
                intelligence_mcp.call_tool("get_match_weather", {"match_id": match_id}),
                intelligence_mcp.call_tool("get_injury_reports", {"team_id": home_team_id, "team_name": home_team_name}),
                intelligence_mcp.call_tool("get_injury_reports", {"team_id": away_team_id, "team_name": away_team_name}),
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
                home_injuries,
                away_injuries,
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
                    "injuries": home_injuries if not isinstance(home_injuries, Exception) else None,
                },
                "away_team": {
                    "id": away_team_id,
                    "name": away_team_name,
                    "stats": away_stats if not isinstance(away_stats, Exception) else None,
                    "form": away_form if not isinstance(away_form, Exception) else None,
                    "injuries": away_injuries if not isinstance(away_injuries, Exception) else None,
                },
                "head_to_head": head_to_head if not isinstance(head_to_head, Exception) else None,
                "odds": odds if not isinstance(odds, Exception) else None,
                "weather": weather if not isinstance(weather, Exception) else None,
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

        self.logger.info("Loading agent tools...")

        # Load MCP tools from both servers
        mcp_data_tools = await self.mcp_factory.get_tools_for_agent("data")
        mcp_intelligence_tools = await self.mcp_factory.get_tools_for_agent("intelligence")

        # Load Python function tools
        from sipap.tools.function import statistical, ml

        function_tools = [
            statistical.poisson_model,
            statistical.xg_calculator,
            statistical.elo_rating,
            statistical.form_score,
            ml.ml_predict,
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
        self.logger.info(f"Running agent predictions for market: {market}")

        # Step 1: Load all tools
        tools = await self.load_agent_tools()
        data_tools = tools["mcp_data_tools"]
        intel_tools = tools["mcp_intelligence_tools"]
        func_tools = tools["function_tools"]

        # Step 2: Define agent-specific tool combinations
        agent_tools = {
            "statistical": data_tools + func_tools,  # Data + statistical functions
            "ml": data_tools + intel_tools + func_tools,  # All tools
            "form": data_tools + [func_tools[3]],  # Data + form_score
            "market": data_tools,  # Data only (odds)
            "news": intel_tools,  # Intelligence only (news, injuries, weather)
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

        # Step 4: Create agents
        self.logger.debug("Creating agents...")
        agents: dict[str, Any] = {}
        for agent_name in ["statistical", "ml", "form", "market", "news"]:
            try:
                agent = self.agent_factory.create(agent_name, tools=agent_tools[agent_name])
                agents[agent_name] = agent
                self.logger.debug(f"Created agent: {agent_name}")
            except Exception as e:
                self.logger.error(
                    f"Failed to create agent: {agent_name}",
                    extra={"error": str(e)},
                    exc_info=True,
                )
                # Continue without this agent (graceful degradation)

        if not agents:
            raise RuntimeError("Failed to create any agents")

        # Step 5: Execute all agents in parallel
        self.logger.info(f"Executing {len(agents)} agents in parallel...")

        async def run_agent(name: str, agent: Any) -> tuple[str, Any]:
            """Execute single agent and return (name, result)."""
            try:
                result = await agent(prompt)
                self.logger.debug(f"Agent {name} completed successfully")
                return (name, result)
            except Exception as e:
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

        self.logger.info(
            f"Agent predictions complete: {len(predictions)}/{len(agents)} agents succeeded",
            extra={"successful_agents": [p["agent"] for p in predictions]},
        )

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
            ("home_injuries", context.get("home_team", {}).get("injuries")),
            ("away_injuries", context.get("away_team", {}).get("injuries")),
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
        self.logger.info(f"Saving prediction for match {match_id}")

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
            return {
                "expected_value": 0.0,
                "is_positive_ev": False,
                "recommendation": "SKIP - Invalid outcome type",
                "reason": "Outcome must be a string",
            }

        outcome: str = outcome_raw

        # Get odds for this outcome
        outcome_odds = odds.get(outcome)
        if not outcome_odds:
            return {
                "expected_value": 0.0,
                "is_positive_ev": False,
                "recommendation": "SKIP - No odds available",
                "reason": f"No odds found for outcome: {outcome}",
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
        # Weighted average (weights based on historical accuracy)
        weights = {
            "statistical": 0.25,
            "ml": 0.30,
            "form": 0.20,
            "market": 0.15,
            "news": 0.10
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
        3. Minimum agent consensus (3/5 agents agree)

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

        # Quality Gate 3: Agent consensus (at least 3/5 agree)
        outcome_counts = Counter([p["prediction"]["outcome"] for p in agent_predictions])
        max_count = max(outcome_counts.values())
        if max_count < 3:
            return {
                **ensemble,
                "quality_gate": "FAILED",
                "reason": "Insufficient agent consensus (< 3/5)",
                "recommendation": "Do not place bet"
            }

        # All gates passed
        return {
            **ensemble,
            "quality_gate": "PASSED",
            "recommendation": "Prediction ready for user"
        }
