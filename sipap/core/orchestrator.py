"""Main Orchestrator - Sport-agnostic routing to specialized orchestrators.

Pattern adapted from Sentinel's routing and delegation patterns.

This orchestrator provides a unified API for all sports and routes requests
to sport-specific orchestrators (SoccerOrchestrator, BasketballOrchestrator, etc.).
"""

import logging
from typing import Any

from sipap.conversation import ConversationManager, NLUAgent, RequestIntent
from sipap.conversation.nlu_agent import ClarificationResponse
from sipap.core.batch_orchestrator import BatchOrchestrator
from sipap.factory.mcp import MCPFactory
from sipap.sports.soccer.orchestrator import SoccerOrchestrator


class MainOrchestrator:
    """
    Main orchestrator that routes prediction requests to sport-specific orchestrators.

    Supports:
    - Soccer (current)
    - Basketball (future)
    - Tennis (future)
    - American Football (future)

    Example:
        >>> orchestrator = MainOrchestrator()
        >>> prediction = await orchestrator.predict(
        ...     sport="soccer",
        ...     match_id="12345",
        ...     market="1X2"
        ... )
    """

    def __init__(self, logger: logging.Logger | None = None):
        """
        Initialize the main orchestrator.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        # Initialize conversation manager for multi-turn conversations
        self.conversation_manager = ConversationManager(logger=self.logger)

        # Initialize NLU agent for natural language understanding
        self.nlu_agent = NLUAgent(logger=self.logger)

        # Initialize MCP factory for data aggregation
        self.mcp_factory = MCPFactory(logger=self.logger)

        # Initialize batch orchestrator for accumulated odds predictions
        self.batch_orchestrator = BatchOrchestrator(
            main_orchestrator=self,
            mcp_factory=self.mcp_factory,
            logger=self.logger,
        )

        # Register sport-specific orchestrators
        self._orchestrators: dict[str, Any] = {
            "soccer": SoccerOrchestrator(logger=self.logger),
            # Future: "basketball": BasketballOrchestrator(logger=self.logger),
            # Future: "tennis": TennisOrchestrator(logger=self.logger),
        }

        self.logger.info(
            "MainOrchestrator initialized",
            extra={"supported_sports": list(self._orchestrators.keys())},
        )

    def get_supported_sports(self) -> list[str]:
        """
        Get list of supported sports.

        Returns:
            List of sport identifiers
        """
        return list(self._orchestrators.keys())

    async def predict(
        self,
        sport: str,
        match_id: str,
        market: str,
        user_id: str | None = None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate prediction for a match.

        This is the main entry point for all prediction requests. It:
        1. Routes to appropriate sport orchestrator
        2. Aggregates context from MCP servers
        3. Validates context quality
        4. Runs ensemble prediction
        5. Calculates expected value
        6. Applies quality gates
        7. Saves prediction
        8. Returns final recommendation

        Args:
            sport: Sport identifier (e.g., "soccer", "basketball")
            match_id: Match identifier
            market: Betting market (e.g., "1X2", "BTTS", "OU2.5")
            user_id: Optional user identifier for conversation tracking
            user_message: Optional original user message for conversation history

        Returns:
            Final prediction with recommendation

        Raises:
            ValueError: If sport not supported or invalid parameters

        Example:
            >>> prediction = await orchestrator.predict(
            ...     sport="soccer",
            ...     match_id="Man_United_vs_Liverpool",
            ...     market="1X2",
            ...     user_id="whatsapp:+1234567890",
            ...     user_message="Show me prediction for Man United vs Liverpool"
            ... )
            >>> print(prediction["recommendation"])
            "PLACE BET - Positive expected value"
        """
        self.logger.info(
            "Prediction request received",
            extra={"sport": sport, "match_id": match_id, "market": market, "user_id": user_id},
        )

        # Add user message to conversation history if provided
        if user_id and user_message:
            self.conversation_manager.add_user_message(user_id, user_message)

        # Validate sport
        if sport not in self._orchestrators:
            supported = list(self._orchestrators.keys())
            raise ValueError(
                f"Sport '{sport}' not supported. Available sports: {supported}"
            )

        # Get sport-specific orchestrator
        orchestrator = self._orchestrators[sport]

        # Step 0: Resolve match identifier (UUID or natural language)
        self.logger.debug("Step 0: Resolving match identifier")
        try:
            resolved_match_id = await orchestrator.resolve_match_id(match_id)
        except ValueError as e:
            return {
                "status": "FAILED",
                "reason": f"Match resolution failed: {str(e)}",
                "recommendation": "SKIP - Invalid match identifier",
            }

        # Step 1: Aggregate context from MCP servers
        self.logger.debug("Step 1: Aggregating context from MCP servers")
        context = await orchestrator.aggregate_context(resolved_match_id)

        # Step 2: Validate context quality
        self.logger.debug("Step 2: Validating context quality")
        validation = orchestrator.validate_context_quality(context)

        if validation["status"] == "FAILED":
            return {
                "status": "FAILED",
                "reason": validation["reason"],
                "recommendation": "SKIP - Insufficient data quality",
                "validation": validation,
            }

        # Step 3: Run ensemble prediction with real AI agents
        self.logger.debug("Step 3: Running AI agent predictions")

        try:
            # Execute all 5 specialized agents
            agent_predictions = await orchestrator.run_agent_predictions(context, market)
        except Exception as e:
            self.logger.error(
                f"Agent execution failed: {e}",
                exc_info=True,
            )
            return {
                "status": "FAILED",
                "reason": f"Agent execution error: {str(e)}",
                "recommendation": "SKIP - Agent execution failed",
            }

        # Calculate ensemble from agent predictions
        ensemble = orchestrator._calculate_ensemble(agent_predictions, market)

        # Step 4: Calculate expected value
        self.logger.debug("Step 4: Calculating expected value")
        odds = context.get("odds", {})
        ev_analysis = orchestrator.calculate_expected_value(ensemble, odds)

        # Add EV to ensemble
        ensemble["expected_value"] = ev_analysis

        # Step 5: Apply quality gates
        self.logger.debug("Step 5: Applying quality gates")
        final_prediction: dict[str, Any] = orchestrator._apply_quality_gates(ensemble, agent_predictions)

        # Step 6: Save prediction
        self.logger.debug("Step 6: Saving prediction to database")
        save_result = await orchestrator.save_prediction(resolved_match_id, final_prediction, context)

        # Add save result to prediction
        final_prediction["save_result"] = save_result

        self.logger.info(
            "Prediction complete",
            extra={
                "match_id": match_id,
                "quality_gate": final_prediction.get("quality_gate"),
                "recommendation": final_prediction.get("recommendation"),
                "prediction_id": save_result.get("prediction_id"),
            },
        )

        # Update conversation state if user_id provided
        if user_id:
            # Format assistant response
            home_team = context.get("home_team", {}).get("name", "Home")
            away_team = context.get("away_team", {}).get("name", "Away")
            outcome = final_prediction.get("outcome", "Unknown")
            probability = final_prediction.get("probability", 0)
            confidence = final_prediction.get("confidence", 0)
            recommendation = final_prediction.get("recommendation", "")

            assistant_message = (
                f"Prediction for {home_team} vs {away_team}:\n"
                f"Outcome: {outcome}\n"
                f"Probability: {probability:.1%}\n"
                f"Confidence: {confidence:.1%}\n"
                f"Recommendation: {recommendation}"
            )

            # Add assistant message to conversation
            self.conversation_manager.add_assistant_message(user_id, assistant_message)

            # Update conversation context with extracted entities
            context_updates = {
                "last_match_id": resolved_match_id,
                "last_home_team": home_team,
                "last_away_team": away_team,
                "last_market": market,
                "last_prediction_id": save_result.get("prediction_id"),
            }
            self.conversation_manager.update_context(user_id, context_updates)

        return final_prediction

    async def handle_user_message(
        self,
        user_id: str,
        message: str,
    ) -> dict[str, Any]:
        """
        Handle natural language user message from WhatsApp.

        This is the PRIMARY ENTRY POINT for WhatsApp user interactions.
        It orchestrates the full flow:
        1. Add user message to conversation history
        2. Get conversation context for entity resolution
        3. Parse message with NLU agent (Claude + regex fallback)
        4. Route based on intent_type
        5. Format response for WhatsApp
        6. Update conversation state

        Args:
            user_id: WhatsApp user identifier (e.g., "whatsapp:+1234567890")
            message: User's natural language query

        Returns:
            Response dictionary ready for WhatsApp delivery:
            {
                "message": "Formatted response text",
                "intent": "batch_prediction",
                "data": {...},  # Optional structured data
                "error": None,  # Or error message if failed
            }

        Example:
            >>> response = await orchestrator.handle_user_message(
            ...     user_id="whatsapp:+1234567890",
            ...     message="I need 20 odds with highest positive outcome"
            ... )
            >>> print(response["message"])
            "Analyzing fixtures for accumulated odds target: 20.0..."

        Business Logic (CRITICAL):
            "X odds" means ACCUMULATED ODDS (sum of bookmaker odds), not match count!
            Example: "20 odds" = accumulate fixtures until sum(bookmaker_odds) >= 20
        """
        self.logger.info(
            "User message received",
            extra={"user_id": user_id, "user_message": message[:100]},
        )

        # Step 1: Add user message to conversation history
        self.conversation_manager.add_user_message(user_id, message)

        # Step 2: Get conversation context for entity resolution
        context = self.conversation_manager.get_context(user_id)

        # Step 3: Parse message with NLU agent
        try:
            intent: RequestIntent = await self.nlu_agent.parse_user_message(
                message, conversation_context=context
            )

            self.logger.info(
                "Intent parsed",
                extra={
                    "user_id": user_id,
                    "intent_type": intent.intent_type,
                    "confidence": intent.confidence,
                    "target_odds": intent.target_odds,
                    "accumulation_mode": intent.accumulation_mode,
                },
            )

            # Step 3.5: Check if clarification is needed
            if self.nlu_agent.needs_clarification(intent):
                self.logger.info(
                    "Generating clarification",
                    extra={"user_id": user_id, "confidence": intent.confidence},
                )

                clarification = await self.nlu_agent.generate_clarification(intent, context)

                # Format clarification for WhatsApp
                clarification_message = self._format_clarification_response(clarification)

                # Save clarification context for follow-up
                if clarification.follow_up_context:
                    self.conversation_manager.update_context(user_id, clarification.follow_up_context)

                response = {
                    "message": clarification_message,
                    "intent": "clarification_needed",
                    "data": {
                        "clarification_type": clarification.clarification_type,
                        "original_intent": intent.intent_type,
                        "confidence": intent.confidence,
                    },
                    "error": None,
                }

                self.conversation_manager.add_assistant_message(user_id, response["message"])
                return response

        except Exception as e:
            self.logger.error(f"NLU parsing failed: {e}", exc_info=True)

            # Even on exception, try to generate helpful response
            from sipap.conversation.nlu_agent import RequestIntent

            unknown_intent = RequestIntent(
                intent_type="unknown",
                confidence=0.0,
                original_query=message,
                extracted_entities={},
            )

            clarification = await self.nlu_agent.generate_clarification(unknown_intent, context)
            clarification_message = self._format_clarification_response(clarification)

            response = {
                "message": clarification_message,
                "intent": "unknown",
                "data": None,
                "error": f"NLU parsing error: {str(e)}",
            }
            self.conversation_manager.add_assistant_message(user_id, response["message"])
            return response

        # Step 4: Route based on intent_type
        if intent.intent_type == "batch_prediction":
            # Phase 2B: Batch prediction with accumulated odds (not yet implemented)
            result = await self._handle_batch_prediction(intent, user_id)

        elif intent.intent_type == "single_prediction":
            # Existing single prediction flow
            result = await self._handle_single_prediction(intent, user_id, message)

        elif intent.intent_type == "track_results":
            # Phase 3: Prediction tracking (not yet implemented)
            result = {
                "message": (
                    "Prediction tracking is coming soon! "
                    "You'll be able to see how your previous selections performed."
                ),
                "intent": "track_results",
                "data": None,
                "error": None,
            }

        elif intent.intent_type == "get_match_results":
            # Get actual match results (live or finished) from Intelligence MCP
            result = await self._handle_get_match_results(intent, user_id)

        elif intent.intent_type == "explain":
            # Explanation feature (future)
            result = {
                "message": (
                    "Explanation feature is coming soon! "
                    "You'll be able to ask 'why' questions about predictions."
                ),
                "intent": "explain",
                "data": None,
                "error": None,
            }

        elif intent.intent_type == "show_fixtures":
            # List upcoming fixtures (no predictions)
            result = await self._handle_show_fixtures(intent, user_id)

        elif intent.intent_type == "check_odds":
            # Check odds feature (future)
            result = {
                "message": (
                    "Odds checking is coming soon! "
                    "You'll be able to see bookmaker odds for any match."
                ),
                "intent": "check_odds",
                "data": None,
                "error": None,
            }

        else:
            # Unknown intent - generate clarification
            clarification = await self.nlu_agent.generate_clarification(intent, context)
            clarification_message = self._format_clarification_response(clarification)

            # Save clarification context for follow-up
            if clarification.follow_up_context:
                self.conversation_manager.update_context(user_id, clarification.follow_up_context)

            result = {
                "message": clarification_message,
                "intent": "unknown",
                "data": {
                    "parsed_intent": intent.dict() if hasattr(intent, "dict") else None,
                    "clarification_type": clarification.clarification_type,
                },
                "error": None,
            }

        # Step 5: Add assistant response to conversation
        self.conversation_manager.add_assistant_message(user_id, result["message"])

        return result

    def _format_clarification_response(self, clarification: ClarificationResponse) -> str:
        """
        Format clarification response for WhatsApp display.

        Args:
            clarification: ClarificationResponse object

        Returns:
            Formatted WhatsApp message

        Example:
            >>> clarification = ClarificationResponse(
            ...     clarification_type="ask_for_missing_entity",
            ...     message="Which match are you interested in?",
            ...     suggested_actions=[{"number": "1", "label": "Example", "example": "Arsenal vs Chelsea"}]
            ... )
            >>> formatted = orchestrator._format_clarification_response(clarification)
            >>> assert "Which match" in formatted
            >>> assert "1️⃣" in formatted
        """
        lines = [clarification.message]

        # Add suggested actions if present
        if clarification.suggested_actions and len(clarification.suggested_actions) > 0:
            lines.append("")  # Blank line before actions

            # Number emoji mapping
            number_emojis = {
                "1": "1️⃣",
                "2": "2️⃣",
                "3": "3️⃣",
                "4": "4️⃣",
                "5": "5️⃣",
            }

            for action in clarification.suggested_actions:
                number = action.get("number", "")
                label = action.get("label", "")
                example = action.get("example")

                emoji = number_emojis.get(number, f"{number}.")

                if example:
                    lines.append(f"{emoji} {label}")
                    lines.append(f"   Example: '{example}'")
                else:
                    lines.append(f"{emoji} {label}")

        return "\n".join(lines)

    async def _handle_batch_prediction(
        self,
        intent: RequestIntent,
        user_id: str,
    ) -> dict[str, Any]:
        """
        Handle batch prediction request (accumulated odds mode).

        Business Logic (CRITICAL):
            "X odds" means ACCUMULATED ODDS (sum of bookmaker odds), NOT number of matches!
            This method calls BatchOrchestrator.process_batch_request() which:
            1. Queries fixtures matching filters (leagues, dates)
            2. Predicts iteratively until accumulated_sum >= target_odds
            3. Applies quality gates (confidence + EV thresholds)
            4. Returns selections with accumulated total

        Args:
            intent: Parsed user intent with target_odds, leagues, date_range, quality_threshold
            user_id: User identifier

        Returns:
            Response dictionary with accumulated predictions:
            {
                "message": "Formatted response for WhatsApp",
                "intent": "batch_prediction",
                "data": {
                    "accumulated_odds": 20.3,
                    "target_odds": 20.0,
                    "selections": [...],
                    "warning": None | "...",
                },
                "error": None | "...",
            }
        """
        target = intent.target_odds or 20.0  # Default to 20 odds

        try:
            # Call BatchOrchestrator to process request
            result = await self.batch_orchestrator.process_batch_request(intent, user_id)

            # Check for errors
            if result.get("error"):
                return {
                    "message": (
                        f"❌ Batch Prediction Error\n\n"
                        f"{result['error']}\n\n"
                        f"Please try:\n"
                        f"- Different date range\n"
                        f"- Different leagues\n"
                        f"- Lower quality threshold"
                    ),
                    "intent": "batch_prediction",
                    "data": result,
                    "error": result["error"],
                }

            # Format success response
            accumulated_odds = result["accumulated_odds"]
            num_selections = len(result["selections"])
            warning = result.get("warning")

            # Build filters text from applied filters in result
            filters_applied = result.get("filters_applied", {})
            filters_text = []

            # Leagues
            leagues = filters_applied.get("leagues") or intent.leagues
            if leagues:
                filters_text.append(f"📍 Leagues: {', '.join(leagues)}")

            # Date range
            date_range = filters_applied.get("date_range") or intent.date_range
            if date_range:
                filters_text.append(
                    f"📅 Dates: {date_range['start']} to {date_range['end']}"
                )

            # Quality threshold
            quality_threshold = filters_applied.get("quality_threshold") or intent.quality_threshold
            if quality_threshold:
                quality_labels = {
                    "highest": "Highest (>70% conf, >10% EV)",
                    "high": "High (>60% conf, >5% EV)",
                    "medium": "Medium (>55% conf, >0% EV)",
                }
                quality_label = quality_labels.get(quality_threshold, quality_threshold)
                filters_text.append(f"⚡ Quality: {quality_label}")

            filters_str = "\n".join(filters_text) if filters_text else "No filters applied"

            # Build selections text
            selections_text = []
            for i, selection in enumerate(result["selections"], 1):
                fixture = selection["fixture"]
                home = fixture.get("home_team", {}).get("name", "Home")
                away = fixture.get("away_team", {}).get("name", "Away")

                # Market information (NEW: explain what market was selected)
                market_code = selection.get("market_code", "Unknown")
                market_name = selection.get("market_name", "Unknown Market")
                outcome = selection["best_outcome"]
                odd = selection["bookmaker_odd"]
                conf = selection["confidence"]
                ev = selection["ev"]

                selections_text.append(
                    f"{i}. {home} vs {away}\n"
                    f"   Market: {market_name} ({market_code})\n"
                    f"   Prediction: {outcome} @ {odd:.1f} odds\n"
                    f"   Confidence: {conf:.0%} | EV: {ev:+.1%}"
                )

            selections_str = "\n\n".join(selections_text) if selections_text else "No selections"

            # Warning text if target not reached
            warning_text = ""
            if warning:
                warning_text = f"\n\n⚠️ {warning}"

            message = (
                f"🎯 Batch Prediction Results\n\n"
                f"Target: {target:.1f} accumulated odds\n"
                f"Achieved: {accumulated_odds:.1f} odds ({num_selections} fixtures)\n\n"
                f"{filters_str}\n\n"
                f"📊 Selections:\n\n{selections_str}"
                f"{warning_text}"
            )

            return {
                "message": message,
                "intent": "batch_prediction",
                "data": result,
                "error": None,
            }

        except Exception as e:
            self.logger.error(f"Batch prediction failed: {e}", exc_info=True)
            return {
                "message": (
                    f"❌ Batch Prediction Failed\n\n"
                    f"An unexpected error occurred: {str(e)}\n\n"
                    f"Please try again or contact support."
                ),
                "intent": "batch_prediction",
                "data": None,
                "error": f"Batch prediction error: {str(e)}",
            }

    async def _handle_single_prediction(
        self,
        intent: RequestIntent,
        user_id: str,
        original_message: str,
    ) -> dict[str, Any]:
        """
        Handle single match prediction request.

        Args:
            intent: Parsed user intent with teams/match_id
            user_id: User identifier
            original_message: Original user message

        Returns:
            Response dictionary with prediction
        """
        # Extract match identifier from intent
        if intent.match_id:
            match_id = intent.match_id
        elif intent.home_team and intent.away_team:
            # Natural language match identifier
            match_id = f"{intent.home_team} vs {intent.away_team}"
        else:
            return {
                "message": (
                    "I couldn't identify which match you're asking about. "
                    "Please specify team names, e.g., 'Arsenal vs Chelsea'"
                ),
                "intent": "single_prediction",
                "data": None,
                "error": "Missing match identifier",
            }

        # Determine market (default to 1X2)
        market = intent.markets[0] if intent.markets else "1X2"

        # Call existing predict method
        try:
            prediction = await self.predict(
                sport="soccer",  # Currently only soccer supported
                match_id=match_id,
                market=market,
                user_id=user_id,
                user_message=original_message,
            )

            # Format prediction for WhatsApp
            if prediction.get("status") == "FAILED":
                message = (
                    f"❌ Prediction failed\n"
                    f"Reason: {prediction.get('reason', 'Unknown error')}"
                )
                error = prediction.get("reason")
            else:
                outcome = prediction.get("outcome", "Unknown")
                probability = prediction.get("probability", 0)
                confidence = prediction.get("confidence", 0)
                recommendation = prediction.get("recommendation", "")

                message = (
                    f"⚽ {match_id}\n"
                    f"Prediction: {outcome}\n"
                    f"Probability: {probability:.1%}\n"
                    f"Confidence: {confidence:.1%}\n"
                    f"💡 {recommendation}"
                )
                error = None

            return {
                "message": message,
                "intent": "single_prediction",
                "data": prediction,
                "error": error,
            }

        except Exception as e:
            self.logger.error(f"Prediction failed: {e}", exc_info=True)
            return {
                "message": f"❌ Prediction error: {str(e)}",
                "intent": "single_prediction",
                "data": None,
                "error": str(e),
            }

    async def _handle_get_match_results(
        self,
        intent: RequestIntent,
        user_id: str,
    ) -> dict[str, Any]:
        """
        Handle match results request (live or finished matches).

        Calls Intelligence MCP's get_match_results tool to fetch real-time
        match scores and status from API-Football.

        Args:
            intent: Parsed user intent with filters (date, league, team, status)
            user_id: User identifier

        Returns:
            Response dictionary with match results
        """
        from datetime import UTC, datetime

        try:
            # Get Intelligence MCP client
            intelligence_mcp = self.mcp_factory.get_client("intelligence")

            # Prepare parameters for get_match_results tool
            params: dict[str, Any] = {}

            # Determine date (default to today)
            if intent.date_range:
                params["date"] = intent.date_range.get("start")
            else:
                params["date"] = datetime.now(UTC).date().isoformat()

            # Add league filter if provided
            if intent.leagues and len(intent.leagues) > 0:
                params["league_name"] = intent.leagues[0]

            # Add team filter if provided
            if intent.home_team:
                params["team_name"] = intent.home_team
            elif intent.away_team:
                params["team_name"] = intent.away_team

            # Determine status (live vs finished)
            # If user says "live", "happening now" -> status = "LIVE"
            # If user says "results", "scores" -> status = "FT"
            # Default to "ALL" to show both
            params["status"] = "ALL"  # Show both live and finished by default

            # Call Intelligence MCP tool
            result = await intelligence_mcp.call_tool("get_match_results", params)

            # Extract matches from result
            matches = result.get("matches", [])
            count = result.get("count", 0)

            # Format results for user
            if count == 0:
                message = (
                    "No matches found matching your criteria. "
                    "Try a different date or league."
                )
                return {
                    "message": message,
                    "intent": "get_match_results",
                    "data": result,
                    "error": None,
                }

            # Format match results for WhatsApp
            lines = [f"📊 Match Results ({count} matches):\n"]

            for match in matches[:10]:  # Limit to 10 matches for WhatsApp
                fixture = match.get("fixture", {})
                teams = match.get("teams", {})
                goals = match.get("goals", {})
                league = match.get("league", {})

                home_team = teams.get("home", {}).get("name", "Unknown")
                away_team = teams.get("away", {}).get("name", "Unknown")
                home_goals = goals.get("home")
                away_goals = goals.get("away")
                status = fixture.get("status", {}).get("short", "")
                league_name = league.get("name", "")

                # Format score display
                if home_goals is not None and away_goals is not None:
                    score_display = f"{home_team} {home_goals}-{away_goals} {away_team}"
                else:
                    score_display = f"{home_team} vs {away_team}"

                # Add status indicator
                status_emoji = "🟢" if status == "LIVE" else "✅" if status == "FT" else "⏰"

                lines.append(f"{status_emoji} {score_display} [{league_name}]")

            if count > 10:
                lines.append(f"\n... and {count - 10} more matches")

            message = "\n".join(lines)

            return {
                "message": message,
                "intent": "get_match_results",
                "data": result,
                "error": None,
            }

        except Exception as e:
            self.logger.error(f"Get match results failed: {e}", exc_info=True)
            return {
                "message": f"❌ Error fetching match results: {str(e)}",
                "intent": "get_match_results",
                "data": None,
                "error": str(e),
            }

    async def _handle_show_fixtures(
        self,
        intent: RequestIntent,
        user_id: str,
    ) -> dict[str, Any]:
        """
        Handle show fixtures request (list upcoming matches).

        Calls Data MCP's search_fixtures tool to fetch scheduled matches
        matching the user's filters (date, league, country).

        Args:
            intent: Parsed user intent with filters (date_range, leagues, extracted_entities)
            user_id: User identifier

        Returns:
            Response dictionary with fixture listings
        """
        from datetime import UTC, datetime, timedelta

        try:
            # Get Data MCP client
            data_mcp = self.mcp_factory.get_client("data")

            # Prepare parameters for search_fixtures tool
            params: dict[str, Any] = {}

            # Extract date range (default to next 7 days)
            if intent.date_range:
                params["date_from"] = intent.date_range.get("start")
                params["date_to"] = intent.date_range.get("end", intent.date_range.get("start"))
            else:
                # Default to next 7 days
                today = datetime.now(UTC).date()
                params["date_from"] = today.isoformat()
                params["date_to"] = (today + timedelta(days=7)).isoformat()

            # Extract league/country filters
            league_names = []

            # Check for explicit league names in intent
            if intent.leagues:
                league_names.extend(intent.leagues)

            # Check for country/location in extracted entities or original query
            entities = intent.extracted_entities or {}

            # Map country names to league names
            country_to_leagues = {
                "sweden": ["Allsvenskan", "Superettan"],
                "england": ["Premier League", "Championship", "League One", "League Two"],
                "spain": ["LaLiga", "LaLiga2"],
                "germany": ["Bundesliga", "2. Bundesliga"],
                "italy": ["Serie A", "Serie B"],
                "france": ["Ligue 1", "Ligue 2"],
            }

            # Check if country mentioned in original query
            original_query_lower = intent.original_query.lower()
            for country, leagues in country_to_leagues.items():
                if country in original_query_lower:
                    league_names.extend(leagues)
                    break

            if league_names:
                params["league_names"] = league_names

            # Only show scheduled matches with odds available
            params["status"] = "scheduled"
            params["has_odds"] = True
            params["limit"] = 50  # Limit to 50 fixtures

            # Call Data MCP tool
            result = await data_mcp.call_tool("search_fixtures", params)

            # Extract fixtures from result
            fixtures = result.get("fixtures", [])
            count = result.get("count", 0)
            filters_applied = result.get("filters_applied", {})

            # Format results for user
            if count == 0:
                # Build helpful message based on what filters were applied
                filter_desc = []
                if params.get("league_names"):
                    filter_desc.append(f"leagues: {', '.join(params['league_names'])}")
                if params.get("date_from"):
                    filter_desc.append(f"date: {params['date_from']}")

                filter_text = " with " + " and ".join(filter_desc) if filter_desc else ""

                message = (
                    f"No fixtures found{filter_text}.\n\n"
                    f"Try:\n"
                    f"- Different date range\n"
                    f"- Different leagues/countries\n"
                    f"- Checking available competitions"
                )
                return {
                    "message": message,
                    "intent": "show_fixtures",
                    "data": result,
                    "error": None,
                }

            # Format fixture listings for WhatsApp
            lines = [f"📅 Upcoming Fixtures ({count} matches):\n"]

            # Group fixtures by date
            from collections import defaultdict
            fixtures_by_date = defaultdict(list)

            for fixture in fixtures[:20]:  # Limit to 20 fixtures for WhatsApp
                scheduled_at = fixture.get("scheduled_at", "")
                if scheduled_at:
                    # Extract just the date part (YYYY-MM-DD)
                    date_part = scheduled_at.split("T")[0] if "T" in scheduled_at else scheduled_at[:10]
                    fixtures_by_date[date_part].append(fixture)

            # Format each date group
            for date_str, date_fixtures in sorted(fixtures_by_date.items())[:5]:  # Max 5 days
                # Parse date for display
                try:
                    date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    date_display = date_obj.strftime("%a, %b %d")
                except:
                    date_display = date_str

                lines.append(f"\n📆 {date_display}:")

                for fixture in date_fixtures[:8]:  # Max 8 matches per day
                    home_team = fixture.get("home_team", "Unknown")
                    away_team = fixture.get("away_team", "Unknown")
                    league = fixture.get("league", "")
                    time_part = fixture.get("scheduled_at", "").split("T")[1][:5] if "T" in fixture.get("scheduled_at", "") else ""

                    # Format: "⚽ 15:00 Arsenal vs Chelsea [Premier League]"
                    if time_part:
                        lines.append(f"  ⚽ {time_part} {home_team} vs {away_team}")
                    else:
                        lines.append(f"  ⚽ {home_team} vs {away_team}")

                    if league:
                        lines.append(f"     📍 {league}")

            if count > 20:
                lines.append(f"\n... and {count - 20} more fixtures")

            # Add filter information
            if filters_applied:
                lines.append("\n")
                if filters_applied.get("leagues"):
                    lines.append(f"🔍 Filtered by: {', '.join(filters_applied['leagues'])}")
                if filters_applied.get("date_range"):
                    date_range = filters_applied["date_range"]
                    lines.append(f"📅 Date range: {date_range.get('from')} to {date_range.get('to')}")

            message = "\n".join(lines)

            return {
                "message": message,
                "intent": "show_fixtures",
                "data": result,
                "error": None,
            }

        except Exception as e:
            self.logger.error(f"Show fixtures failed: {e}", exc_info=True)
            return {
                "message": f"❌ Error fetching fixtures: {str(e)}",
                "intent": "show_fixtures",
                "data": None,
                "error": str(e),
            }

    def _mock_agent_predictions(self, market: str) -> list[dict[str, Any]]:
        """
        DEPRECATED: Mock agent predictions for testing.

        This method is NO LONGER USED. Real agent execution is now implemented
        in SoccerOrchestrator.run_agent_predictions().

        Kept for backwards compatibility and testing only.

        Args:
            market: Betting market

        Returns:
            List of mock agent predictions
        """
        # Note: market parameter reserved for future use
        _ = market  # Suppress unused warning

        # Mock predictions for 5 agents
        return [
            {
                "agent": "statistical",
                "prediction": {"outcome": "Home Win", "probability": 0.55},
                "reasoning": "Poisson model favors home team",
                "evidence": ["Home team xG: 1.8", "Away team xG: 1.2"],
            },
            {
                "agent": "ml",
                "prediction": {"outcome": "Home Win", "probability": 0.60},
                "reasoning": "XGBoost model prediction",
                "evidence": ["Model confidence: 85%"],
            },
            {
                "agent": "form",
                "prediction": {"outcome": "Home Win", "probability": 0.52},
                "reasoning": "Home team in better form",
                "evidence": ["Home form: WWDWL", "Away form: LLWDD"],
            },
            {
                "agent": "market",
                "prediction": {"outcome": "Home Win", "probability": 0.58},
                "reasoning": "Betting market sentiment",
                "evidence": ["Market probability: 58%"],
            },
            {
                "agent": "news",
                "prediction": {"outcome": "Home Win", "probability": 0.50},
                "reasoning": "Neutral news impact",
                "evidence": ["No significant team news"],
            },
        ]
