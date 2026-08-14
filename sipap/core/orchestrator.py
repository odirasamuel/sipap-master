"""Main Orchestrator - Sport-agnostic routing to specialized orchestrators.

Pattern adapted from Sentinel's routing and delegation patterns.

This orchestrator provides a unified API for all sports and routes requests
to sport-specific orchestrators (SoccerOrchestrator, BasketballOrchestrator, etc.).
"""

import logging
import os
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

        # Check if DEBUG logging is enabled
        self.debug_enabled = self.logger.isEnabledFor(logging.DEBUG)

        # Initialize conversation manager for multi-turn conversations
        self.conversation_manager = ConversationManager(logger=self.logger)

        # Initialize NLU agent for natural language understanding
        # Claude-powered clarifications can be enabled via ENABLE_CLAUDE_NLU env var
        use_claude_nlu = os.getenv("ENABLE_CLAUDE_NLU", "true").lower() == "true"
        self.nlu_agent = NLUAgent(logger=self.logger, use_claude=use_claude_nlu)

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

        log_mode = "DEBUG mode enabled" if self.debug_enabled else "INFO mode (summary only)"
        self.logger.info(
            f"MainOrchestrator initialized - {log_mode}",
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
        if self.debug_enabled:
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
        if self.debug_enabled:
            self.logger.debug("Step 1: Aggregating context from MCP servers")
        context = await orchestrator.aggregate_context(resolved_match_id)

        # Step 2: Validate context quality
        if self.debug_enabled:
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
        if self.debug_enabled:
            self.logger.debug("Step 3: Running AI agent predictions")

        try:
            # Execute all 3 specialized agents
            agent_predictions = await orchestrator.run_agent_predictions(context, market)
        except Exception as e:
            # Always log errors
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
        # Log ensemble result (INFO - always visible)
        self.logger.info(
            f"🎯 Ensemble: {ensemble.get('outcome', 'Unknown')} "
            f"(prob={ensemble.get('probability', 0):.2f}, "
            f"conf={ensemble.get('confidence', 0):.0f}%)"
        )

        # Step 4: Calculate expected value
        if self.debug_enabled:
            self.logger.debug("Step 4: Calculating expected value")
        odds = context.get("odds", {})
        ev_analysis = orchestrator.calculate_expected_value(ensemble, odds)

        # Add EV to ensemble
        ensemble["expected_value"] = ev_analysis

        # Step 5: Apply quality gates
        if self.debug_enabled:
            self.logger.debug("Step 5: Applying quality gates")
        final_prediction: dict[str, Any] = orchestrator._apply_quality_gates(ensemble, agent_predictions)

        # Step 6: Save prediction
        if self.debug_enabled:
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

    async def predict_with_context(
        self,
        sport: str,
        match_id: str,
        market: str,
        context: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate prediction using pre-aggregated context.

        This is an OPTIMIZED version of predict() for batch processing where
        context has already been aggregated. It skips context aggregation and
        validation steps, proceeding directly to agent execution.

        Use this when processing multiple markets for the SAME fixture to avoid
        redundant MCP calls (context is identical across markets).

        Args:
            sport: Sport identifier (e.g., "soccer")
            match_id: Match identifier (must be resolved UUID)
            market: Betting market (e.g., "1X2", "BTTS", "OU2.5")
            context: Pre-aggregated context from aggregate_context()
            user_id: Optional user identifier

        Returns:
            Final prediction with recommendation

        Raises:
            ValueError: If sport not supported

        Example:
            >>> # Batch processing 44 markets for same fixture
            >>> context = await orchestrator.aggregate_context(match_id)
            >>> for market in all_markets:
            ...     prediction = await orchestrator.predict_with_context(
            ...         sport="soccer",
            ...         match_id=match_id,
            ...         market=market,
            ...         context=context,
            ...     )
        """
        self.logger.info(
            "Prediction with context request received",
            extra={"sport": sport, "match_id": match_id, "market": market},
        )

        # Validate sport
        if sport not in self._orchestrators:
            supported = list(self._orchestrators.keys())
            raise ValueError(
                f"Sport '{sport}' not supported. Available sports: {supported}"
            )

        # Get sport-specific orchestrator
        orchestrator = self._orchestrators[sport]

        # Step 1: Run ensemble prediction with real AI agents
        self.logger.debug("Step 1: Running AI agent predictions")

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
        self.logger.info(
            f"Ensemble result: {ensemble.get('outcome', 'Unknown')} "
            f"(prob: {ensemble.get('probability', 0):.2f}, "
            f"conf: {ensemble.get('confidence', 0):.0f}%)"
        )

        # Step 2: Calculate expected value
        self.logger.debug("Step 2: Calculating expected value")
        odds = context.get("odds", {})
        ev_analysis = orchestrator.calculate_expected_value(ensemble, odds)

        # Add EV to ensemble
        ensemble["expected_value"] = ev_analysis

        # Step 3: Apply quality gates
        self.logger.debug("Step 3: Applying quality gates")
        final_prediction: dict[str, Any] = orchestrator._apply_quality_gates(ensemble, agent_predictions)

        # Step 4: Save prediction
        self.logger.debug("Step 4: Saving prediction to database")
        save_result = await orchestrator.save_prediction(match_id, final_prediction, context)

        # Add save result to prediction
        final_prediction["save_result"] = save_result

        self.logger.info(
            "Prediction with context complete",
            extra={
                "match_id": match_id,
                "market": market,
                "quality_gate": final_prediction.get("quality_gate"),
                "recommendation": final_prediction.get("recommendation"),
                "prediction_id": save_result.get("prediction_id"),
            },
        )

        return final_prediction

    async def aggregate_and_validate_context(
        self,
        sport: str,
        match_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | tuple[None, dict[str, Any]]:
        """
        Aggregate and validate context for a fixture.

        Helper method for batch processing to check context quality BEFORE
        evaluating markets. Returns (context, validation) tuple.

        Args:
            sport: Sport identifier
            match_id: Match identifier (can be UUID or natural language)

        Returns:
            (context, validation) if validation passes
            (None, validation) if validation fails

        Example:
            >>> context, validation = await orchestrator.aggregate_and_validate_context(
            ...     sport="soccer",
            ...     match_id="123e4567-e89b-12d3-a456-426614174000",
            ... )
            >>> if context is None:
            ...     print(f"Skipping fixture: {validation['reason']}")
            ...     return
            >>> # Use context for multiple markets...
        """
        # Validate sport
        if sport not in self._orchestrators:
            supported = list(self._orchestrators.keys())
            return (None, {
                "status": "FAILED",
                "reason": f"Sport '{sport}' not supported. Available: {supported}",
            })

        orchestrator = self._orchestrators[sport]

        # Resolve match identifier
        try:
            resolved_match_id = await orchestrator.resolve_match_id(match_id)
        except ValueError as e:
            return (None, {
                "status": "FAILED",
                "reason": f"Match resolution failed: {str(e)}",
            })

        # Aggregate context
        context = await orchestrator.aggregate_context(resolved_match_id)

        # Validate context quality
        validation = orchestrator.validate_context_quality(context)

        if validation["status"] == "FAILED":
            return (None, validation)

        return (context, validation)

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
                "error": None,  # Don't expose technical errors to user
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

            # Build selections text (condensed format)
            # Format: "1. Arsenal v Chelsea - Home @2.5 (65%, +8%) [PL]"
            selections_text = []
            for i, selection in enumerate(result["selections"], 1):
                fixture = selection["fixture"]
                home = fixture.get("home_team", {}).get("name", "Home")
                away = fixture.get("away_team", {}).get("name", "Away")
                league = fixture.get("league", {}).get("name", "")

                outcome = selection["best_outcome"]
                odd = selection["bookmaker_odd"]
                conf = selection["confidence"]
                ev = selection["ev"]

                # Abbreviate league
                league_abbrev = self._abbreviate_league(league)

                # Condensed format
                line = f"{i}. {home} v {away} - {outcome} @{odd:.1f} ({conf:.0%}, {ev:+.0%})"
                if league_abbrev:
                    line += f" [{league_abbrev}]"
                selections_text.append(line)

            selections_str = "\n".join(selections_text) if selections_text else "No selections"

            # Warning text if target not reached
            warning_text = ""
            if warning:
                warning_text = f"\n⚠️ {warning}"

            # Build header
            header = (
                f"🎯 Batch Prediction\n"
                f"Target: {target:.1f} | Achieved: {accumulated_odds:.1f} ({num_selections})\n"
            )
            if filters_str:
                header += f"{filters_str}\n"
            header += f"\n📊 Selections:\n"

            # Full message
            full_message = header + selections_str + warning_text

            # Paginate if needed (automatic multi-message sending)
            if len(full_message) > 1600:
                # Use _paginate_message to split into pages with [PAGE_BREAK] markers
                # The daemon will automatically send multiple messages
                message = self._paginate_message(
                    header=header + warning_text + "\n",
                    lines=selections_text,
                    max_length=1600,
                    total_count=num_selections
                )
            else:
                message = full_message

            return {
                "message": message,
                "intent": "batch_prediction",
                "data": result,
                "error": None,
            }

        except Exception as e:
            self.logger.error(f"Batch prediction failed: {e}", exc_info=True)

            # NEVER expose raw errors to users - provide friendly message
            friendly_message = (
                "I'm having trouble generating predictions right now. "
                "Please try again in a moment, or try:\n\n"
                "• Being more specific about what you're looking for\n"
                "• Checking fixtures first to see what's available\n"
                "• Starting with a smaller batch (e.g., '5 odds' instead of '20')"
            )

            return {
                "message": friendly_message,
                "intent": "batch_prediction",
                "data": None,
                "error": None,  # Don't expose error to user
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

            # NEVER expose raw errors to users - provide friendly message
            friendly_message = (
                "I'm having trouble generating predictions right now. "
                "Please try again in a moment, or try:\n\n"
                "• Checking if the match is scheduled (predictions need upcoming fixtures)\n"
                "• Asking for batch predictions instead (e.g., '20 odds')\n"
                "• Viewing available fixtures first"
            )

            return {
                "message": friendly_message,
                "intent": "single_prediction",
                "data": None,
                "error": None,  # Don't expose error to user
            }

    async def _handle_get_match_results(
        self,
        intent: RequestIntent,
        user_id: str,
    ) -> dict[str, Any]:
        """
        Handle match results request (live or finished matches).

        Database-First Strategy with API-Football Fallback:
        1. For LIVE matches → Always use Intelligence MCP (API-Football real-time)
        2. For finished matches → Try Data MCP (database) first, fallback to Intelligence MCP
        3. For "ALL" status → Combine database finished + API live matches

        This ensures we use cached historical data when available, saving API quota
        and providing faster responses, while maintaining real-time accuracy for live matches.

        Args:
            intent: Parsed user intent with filters (date, league, team, status)
            user_id: User identifier

        Returns:
            Response dictionary with match results
        """
        from datetime import UTC, datetime, timedelta

        try:
            # Prepare common parameters
            params: dict[str, Any] = {}

            # Determine date (default to today)
            if intent.date_range:
                date_start = intent.date_range.get("start")
                date_end = intent.date_range.get("end", date_start)
            else:
                today = datetime.now(UTC).date().isoformat()
                date_start = today
                date_end = today

            params["date"] = date_start

            # Add league filter if provided
            league_names = None
            if intent.leagues and len(intent.leagues) > 0:
                league_names = intent.leagues
                params["league_name"] = intent.leagues[0]

            # Add team filter if provided
            team_name = None
            if intent.home_team:
                team_name = intent.home_team
                params["team_name"] = intent.home_team
            elif intent.away_team:
                team_name = intent.away_team
                params["team_name"] = intent.away_team

            # Determine status (live vs finished)
            # Default to "FT" for results queries (most common case)
            status = "FT"  # Default: finished matches

            # STRATEGY: Database-first for historical data, API-Football for live data
            matches = []
            data_source = "unknown"

            # Step 1: Try database first for finished matches (historical data)
            if status in ["FT", "AET", "PEN", "ALL"]:
                self.logger.info(
                    f"Attempting database lookup for finished matches: date={date_start}, "
                    f"leagues={league_names}, team={team_name}"
                )

                try:
                    # Get Data MCP client
                    data_mcp = self.mcp_factory.create("data")

                    # Query database for finished matches
                    db_params: dict[str, Any] = {
                        "date_from": date_start,
                        "date_to": date_end,
                        "status": "finished",
                        "has_odds": False,  # Don't filter by odds for results queries
                        "limit": 100,
                    }

                    if league_names:
                        db_params["league_names"] = league_names

                    # Call Data MCP's search_fixtures tool
                    db_result = await data_mcp.call_tool("search_fixtures", db_params)
                    db_fixtures = db_result.get("fixtures", [])

                    # Filter by team name if provided (database query doesn't support team filter yet)
                    if team_name and db_fixtures:
                        team_lower = team_name.lower()
                        db_fixtures = [
                            f for f in db_fixtures
                            if (team_lower in f.get("home_team", "").lower()
                                or team_lower in f.get("away_team", "").lower())
                        ]

                    # Check if database has results with scores
                    finished_matches_with_scores = [
                        f for f in db_fixtures
                        if f.get("home_score") is not None and f.get("away_score") is not None
                    ]

                    if finished_matches_with_scores:
                        self.logger.info(
                            f"Database hit: Found {len(finished_matches_with_scores)} finished matches with scores"
                        )
                        matches.extend(self._convert_db_fixtures_to_api_format(finished_matches_with_scores))
                        data_source = "database"
                    else:
                        self.logger.info(
                            f"Database miss: No finished matches with scores found (total fixtures: {len(db_fixtures)})"
                        )

                except Exception as e:
                    self.logger.warning(
                        f"Database lookup failed, will fallback to API-Football: {e}"
                    )

            # Step 2: Fallback to API-Football if no database results or for live matches
            if not matches or status == "LIVE":
                self.logger.info(
                    f"Using API-Football fallback (live data or database miss): status={status}"
                )

                # Get Intelligence MCP client
                intelligence_mcp = self.mcp_factory.create("intelligence")

                # Use original params with status
                params["status"] = status

                # Call Intelligence MCP tool (API-Football real-time)
                api_result = await intelligence_mcp.call_tool("get_match_results", params)
                api_matches = api_result.get("matches", [])

                if api_matches:
                    self.logger.info(f"API-Football returned {len(api_matches)} matches")
                    matches.extend(api_matches)
                    data_source = "api-football" if not matches else "hybrid"

            # Build combined result
            result = {
                "matches": matches,
                "count": len(matches),
                "date": date_start,
                "status_filter": status,
                "league_filter": league_names[0] if league_names else None,
                "team_filter": team_name,
                "data_source": data_source,
            }

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

            # NEVER expose raw errors to users - provide friendly message
            friendly_message = (
                "I'm having trouble fetching match results right now. "
                "Please try again in a moment, or try:\n\n"
                "• Being more specific (e.g., 'Arsenal results yesterday')\n"
                "• Checking a different league or date\n"
                "• Asking for upcoming fixtures instead"
            )

            return {
                "message": friendly_message,
                "intent": "get_match_results",
                "data": None,
                "error": None,  # Don't expose error to user
            }

    def _convert_db_fixtures_to_api_format(
        self,
        db_fixtures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert Data MCP fixture format to API-Football format.

        Ensures compatibility between database fixtures and API-Football fixtures
        so the same formatting code can handle both sources.

        Args:
            db_fixtures: Fixtures from Data MCP (database format)

        Returns:
            Fixtures in API-Football format
        """
        api_format_fixtures = []

        for fixture in db_fixtures:
            # Convert database fixture to API-Football structure
            api_fixture = {
                "fixture": {
                    "id": fixture.get("id"),
                    "date": fixture.get("scheduled_at"),
                    "status": {
                        "short": "FT",  # Database only has finished matches
                        "long": "Match Finished",
                    },
                    "venue": fixture.get("metadata", {}).get("venue", {}),
                    "referee": fixture.get("metadata", {}).get("referee"),
                },
                "league": {
                    "id": fixture.get("league_id"),
                    "name": fixture.get("league", "Unknown"),
                    "country": fixture.get("metadata", {}).get("country", ""),
                    "season": fixture.get("metadata", {}).get("season"),
                },
                "teams": {
                    "home": {
                        "id": fixture.get("home_team_id"),
                        "name": fixture.get("home_team", "Unknown"),
                        "logo": None,
                    },
                    "away": {
                        "id": fixture.get("away_team_id"),
                        "name": fixture.get("away_team", "Unknown"),
                        "logo": None,
                    },
                },
                "goals": {
                    "home": fixture.get("home_score"),
                    "away": fixture.get("away_score"),
                },
                "score": {
                    "halftime": {
                        "home": fixture.get("metadata", {}).get("halftime_home_score"),
                        "away": fixture.get("metadata", {}).get("halftime_away_score"),
                    },
                    "fulltime": {
                        "home": fixture.get("home_score"),
                        "away": fixture.get("away_score"),
                    },
                    "extratime": {
                        "home": None,
                        "away": None,
                    },
                    "penalty": {
                        "home": None,
                        "away": None,
                    },
                },
            }

            api_format_fixtures.append(api_fixture)

        return api_format_fixtures

    def _format_fixtures_with_pagination(
        self,
        fixtures: list[dict[str, Any]],
        count: int,
        filters_applied: dict[str, Any],
        params: dict[str, Any],
        max_length: int = 1600,
    ) -> str:
        """Format fixtures in condensed format with automatic pagination.

        Condensed format examples:
        - Scheduled: ⚽ 15:00 Arsenal v Chelsea (PL) - 2.50/3.20/2.80
        - Finished: ✅ Arsenal 2-1 Chelsea (Premier League)
        - Live: 🔴 Arsenal 1-0 Chelsea 45' (Premier League)

        Args:
            fixtures: List of fixture dictionaries
            count: Total count of fixtures
            filters_applied: Filters that were applied
            params: Query parameters
            max_length: Maximum message length (default 1600 chars for WhatsApp)

        Returns:
            Formatted fixture message (or first page if pagination needed)
        """
        from datetime import datetime

        # Build header
        header = f"📅 Fixtures ({count} found)\n"
        if filters_applied.get("leagues"):
            header += f"🔍 {', '.join(filters_applied['leagues'])}\n"
        header += "\n"

        lines = []

        for fixture in fixtures:
            home = fixture.get("home_team", "Unknown")
            away = fixture.get("away_team", "Unknown")
            league = fixture.get("league", "")
            status = fixture.get("status", "NS")  # NS, FT, 1H, 2H, etc.
            scheduled_at = fixture.get("scheduled_at", "")

            # Extract time (HH:MM)
            time_part = ""
            if scheduled_at and "T" in scheduled_at:
                time_part = scheduled_at.split("T")[1][:5]

            # Get odds
            h_odds = fixture.get("best_home_odds")
            d_odds = fixture.get("best_draw_odds")
            a_odds = fixture.get("best_away_odds")

            # Get results (for finished matches)
            home_score = fixture.get("home_score")
            away_score = fixture.get("away_score")

            # Abbreviate league name for compact display
            league_abbrev = self._abbreviate_league(league)

            # Format based on status
            if status == "FT" and home_score is not None and away_score is not None:
                # Finished match with result
                line = f"✅ {home} {home_score}-{away_score} {away}"
                if league_abbrev:
                    line += f" ({league_abbrev})"
            elif status in ("1H", "2H", "HT", "LIVE"):
                # Live match
                minute = fixture.get("elapsed", "")
                score_str = ""
                if home_score is not None and away_score is not None:
                    score_str = f" {home_score}-{away_score}"
                line = f"🔴{score_str} {home} v {away}"
                if minute:
                    line += f" {minute}'"
                if league_abbrev:
                    line += f" ({league_abbrev})"
            else:
                # Scheduled match (NS, TBD, etc.)
                line = f"⚽ {time_part} {home} v {away}"
                if league_abbrev:
                    line += f" ({league_abbrev})"
                # Add odds if available
                if h_odds and d_odds and a_odds:
                    line += f" - {h_odds:.2f}/{d_odds:.2f}/{a_odds:.2f}"

            lines.append(line)

        # Join all lines
        full_message = header + "\n".join(lines)

        # Check if pagination needed
        if len(full_message) <= max_length:
            return full_message

        # Pagination needed - split into chunks
        return self._paginate_message(header, lines, max_length, count)

    def _abbreviate_league(self, league: str) -> str:
        """Abbreviate common league names for compact display."""
        abbrev_map = {
            "Premier League": "PL",
            "UEFA Champions League": "UCL",
            "UEFA Europa League": "UEL",
            "UEFA Conference League": "UECL",
            "La Liga": "LaLiga",
            "Serie A": "Serie A",
            "Bundesliga": "BuLi",
            "Ligue 1": "L1",
            "Eredivisie": "Eredivisie",
            "Championship": "Champ",
        }
        return abbrev_map.get(league, league[:20])  # Max 20 chars for unknown leagues

    def _paginate_message(
        self,
        header: str,
        lines: list[str],
        max_length: int,
        total_count: int,
    ) -> str:
        """Split fixtures into multiple pages automatically.

        Returns all pages separated by special marker that daemon will split and send separately.
        Uses [PAGE_BREAK] marker to indicate message boundaries.
        """
        pages = []
        page_lines = []
        current_length = len(header)

        for i, line in enumerate(lines):
            line_length = len(line) + 1  # +1 for newline

            # Check if adding this line would exceed limit
            if current_length + line_length > (max_length - 150):  # Reserve for page footer
                # Save current page
                page_num = len(pages) + 1
                footer = f"\n\n📄 Page {page_num}/{((total_count - 1) // len(page_lines)) + 1}"
                pages.append(header + "\n".join(page_lines) + footer)

                # Start new page
                page_lines = [line]
                current_length = len(header) + line_length
            else:
                page_lines.append(line)
                current_length += line_length

        # Add last page
        if page_lines:
            page_num = len(pages) + 1
            estimated_total_pages = ((total_count - 1) // max(len(lines) // max(1, len(pages)), 1)) + 1
            footer = f"\n\n📄 Page {page_num}"
            if len(pages) > 0:  # Multiple pages
                footer += f"/{estimated_total_pages}"
            pages.append(header + "\n".join(page_lines) + footer)

        # Join pages with special marker for daemon to split
        return "[PAGE_BREAK]".join(pages)

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

        self.logger.info(
            f"Handling show_fixtures request for user {user_id}",
            extra={"user_id": user_id, "intent_type": intent.intent_type}
        )

        try:
            # Get Data MCP client
            data_mcp = self.mcp_factory.create("data")

            # Prepare parameters for search_fixtures tool
            params: dict[str, Any] = {}

            # Extract date range (default to next 7 days)
            if intent.date_range:
                params["date_from"] = intent.date_range.get("start")
                params["date_to"] = intent.date_range.get("end", intent.date_range.get("start"))
                self.logger.debug(f"Using date range from intent: {params['date_from']} to {params['date_to']}")
            else:
                # Default to next 7 days
                today = datetime.now(UTC).date()
                params["date_from"] = today.isoformat()
                params["date_to"] = (today + timedelta(days=7)).isoformat()
                self.logger.debug(f"Using default date range: {params['date_from']} to {params['date_to']}")

            # Extract league/country filters
            league_names = []

            # Check for explicit league names in intent
            if intent.leagues:
                league_names.extend(intent.leagues)

            # Check for country/location in extracted entities or original query
            entities = intent.extracted_entities or {}

            # Map country names to league names
            # Use comprehensive league mappings (380 competitions) from sipap-common
            from sipap_common.data import find_league_matches

            # Find league matches from user query (country names, competition aliases, etc.)
            matched_leagues = find_league_matches(intent.original_query)

            if matched_leagues:
                league_names.extend(matched_leagues)
                params["league_names"] = league_names
                self.logger.info(
                    f"Matched leagues from query: {matched_leagues}",
                    extra={"query": intent.original_query, "matched": matched_leagues}
                )
            else:
                self.logger.debug("No league filter applied, querying all leagues")

            # Show upcoming matches (API-Football uses 'NS' for Not Started, not 'scheduled')
            params["status"] = "NS"  # Match API-Football status codes
            params["has_odds"] = False  # Don't filter by odds - show all fixtures
            params["limit"] = 50  # Limit to 50 fixtures

            self.logger.info(
                "Calling Data MCP search_fixtures",
                extra={"params": params}
            )

            # Call Data MCP tool
            result = await data_mcp.call_tool("search_fixtures", params)

            # Extract fixtures from result
            fixtures = result.get("fixtures", [])
            count = result.get("count", 0)
            filters_applied = result.get("filters_applied", {})

            self.logger.info(
                f"Data MCP returned {count} fixtures",
                extra={"count": count, "filters": filters_applied}
            )

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

            # Format fixture listings for WhatsApp (condensed format with pagination)
            message = self._format_fixtures_with_pagination(
                fixtures=fixtures,
                count=count,
                filters_applied=filters_applied,
                params=params
            )

            return {
                "message": message,
                "intent": "show_fixtures",
                "data": result,
                "error": None,
            }

        except Exception as e:
            self.logger.error(f"Show fixtures failed: {e}", exc_info=True)

            # NEVER expose raw errors to users - provide friendly message
            friendly_message = (
                "I'm having trouble fetching fixtures right now. "
                "Please try again in a moment, or try:\n\n"
                "• Being more specific (e.g., 'Premier League fixtures today')\n"
                "• Checking a different league or date range\n"
                "• Asking for predictions instead"
            )

            return {
                "message": friendly_message,
                "intent": "show_fixtures",
                "data": None,
                "error": None,  # Don't expose error to user
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
