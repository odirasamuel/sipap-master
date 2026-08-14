"""Natural Language Understanding Agent for SIPAP.

Parses WhatsApp user messages into structured RequestIntent objects using Claude AI
with graceful fallback to regex-based parsing.

This replaces the simple regex-based IntentParser with a Claude-powered NLU system
that can handle complex, unstructured natural language queries.

Pattern adapted from Sentinel's routing agent architecture.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sipap.conversation.intent_parser import Intent, IntentParser
from sipap_common.logging import get_logger


class RequestIntent(BaseModel):
    """Structured user intent with extracted entities.

    This model represents the parsed output of a user's natural language query.
    All NLU systems (Claude, regex) must output this structure.

    CRITICAL BUSINESS LOGIC:
    In sports betting, "X odds" means ACCUMULATED ODDS (not number of matches).
    When user says "I need 20 odds", SIPAP should:
    1. Analyze fixtures and select best outcomes per fixture
    2. Accumulate: sum(bookmaker_odds_per_fixture) until sum >= target_odds
    3. Example: Fixture1 (2.5 odds) + Fixture2 (3.0 odds) + ... = 20+ total

    Example:
        >>> intent = RequestIntent(
        ...     intent_type="batch_prediction",
        ...     confidence=0.9,
        ...     target_odds=20.0,  # Accumulate until sum >= 20
        ...     accumulation_mode=True,
        ...     quality_threshold="highest",
        ...     original_query="I need 20 odds with highest positive outcome"
        ... )
    """

    # Intent classification
    intent_type: Literal[
        "batch_prediction",  # User wants accumulated odds from multiple fixtures
        "single_prediction",  # User wants one specific match prediction
        "track_results",  # User asks for results of previous predictions
        "get_match_results",  # User wants actual match results/scores (live or finished)
        "explain",  # User wants explanation of a prediction
        "show_fixtures",  # User wants to see available fixtures (no predictions)
        "check_odds",  # User wants to check odds
        "unknown",  # Cannot determine intent
    ]
    confidence: float = Field(ge=0.0, le=1.0)  # Confidence score 0.0-1.0

    # Batch prediction parameters (ACCUMULATION MODE)
    target_odds: float | None = Field(default=None, ge=1.0, le=100.0)  # Target accumulated odds
    accumulation_mode: bool = False  # True when user wants accumulated odds (default behavior)
    num_matches: int | None = Field(default=None, ge=1, le=50)  # Explicit fixture count (rare)

    leagues: list[str] | None = None  # ["Premier League", "LaLiga", ...]
    date_range: dict[str, str] | None = None  # {"start": "2026-08-03", "end": "2026-08-10"}
    markets: list[str] | None = None  # INTERNAL USE ONLY - Not extracted from user messages
    quality_threshold: Literal["highest", "high", "medium"] | None = None
    sort_by: Literal["ev", "confidence", "probability"] | None = "ev"

    # Single prediction parameters
    home_team: str | None = None
    away_team: str | None = None
    match_id: str | None = None

    # Context
    original_query: str
    extracted_entities: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=False)  # Allow modifications for context resolution


class NLUAgent:
    """
    Natural Language Understanding agent for sports betting intelligence.

    Uses Claude AI (via Strands Agents) as primary NLU engine with graceful fallback
    to regex-based parsing when Claude fails or returns low confidence.

    Architecture:
        1. Primary: Claude-based NLU with structured output (RequestIntent)
        2. Fallback: Regex-based IntentParser for simple queries
        3. Graceful degradation: Returns "unknown" intent if both fail

    Example:
        >>> nlu = NLUAgent()
        >>> intent = await nlu.parse_user_message(
        ...     "I need 20 odds with highest positive outcome"
        ... )
        >>> print(intent.intent_type)
        "batch_prediction"
        >>> print(intent.num_matches)
        20
    """

    def __init__(self, logger: logging.Logger | None = None, use_claude: bool = True):
        """
        Initialize NLU agent.

        Args:
            logger: Optional logger instance
            use_claude: Use Claude for clarifications (default: True)
        """
        self.logger = logger or get_logger(__name__)
        self.use_claude = use_claude

        # Regex fallback parser (existing IntentParser)
        self.regex_parser = IntentParser(logger=self.logger)

        # Claude agent will be initialized lazily
        self._claude_agent: Any | None = None

        # Clarification agent for intelligent error handling
        self.clarification_agent = ClarificationAgent(logger=self.logger, use_claude=self.use_claude)

        claude_status = "enabled" if self.use_claude else "disabled"
        self.logger.info(f"NLUAgent initialized with Claude + regex fallback + clarification (Claude NLU: {claude_status})")

    async def parse_user_message(
        self,
        message: str,
        conversation_context: dict[str, Any] | None = None,
    ) -> RequestIntent:
        """
        Parse user message with Claude NLU, fallback to regex.

        Flow:
        1. Try Claude-based NLU (structured output)
        2. If confidence < 0.5, try regex parser
        3. If both fail, return Intent.UNKNOWN with low confidence

        Args:
            message: User query string
            conversation_context: Optional conversation context for entity resolution

        Returns:
            RequestIntent with parsed intent and entities

        Example:
            >>> intent = await nlu.parse_user_message(
            ...     "Give me 10 matches today with very high success chance"
            ... )
            >>> assert intent.intent_type == "batch_prediction"
            >>> assert intent.num_matches == 10
            >>> assert intent.quality_threshold == "highest"
        """
        message = message.strip()
        conversation_context = conversation_context or {}

        self.logger.debug(f"Parsing user message: {message[:50]}...")

        # Primary: Claude-based NLU
        try:
            claude_intent = await self._parse_with_claude(message, conversation_context)

            if claude_intent.confidence >= 0.5:
                self.logger.info(
                    f"Claude NLU parsed: {claude_intent.intent_type} "
                    f"(confidence: {claude_intent.confidence:.2f})"
                )
                return claude_intent

            self.logger.warning(
                f"Claude NLU low confidence: {claude_intent.confidence:.2f}, trying regex fallback"
            )

        except Exception as e:
            self.logger.error(f"Claude NLU failed: {e}, falling back to regex")

        # Fallback: Regex parser
        try:
            regex_result = self.regex_parser.parse(message, context=conversation_context)

            # Convert regex result to RequestIntent
            regex_intent = self._convert_regex_to_request_intent(regex_result, message)

            self.logger.info(
                f"Regex parser used as fallback: {regex_intent.intent_type} "
                f"(confidence: {regex_intent.confidence:.2f})"
            )
            return regex_intent

        except Exception as e:
            self.logger.error(f"Regex parser also failed: {e}")

        # Both failed - return unknown intent
        return RequestIntent(
            intent_type="unknown",
            confidence=0.0,
            original_query=message,
            extracted_entities={},
        )

    def needs_clarification(self, intent: RequestIntent) -> bool:
        """
        Determine if an intent needs clarification.

        Clarification is needed when:
        1. Confidence < 0.7 (uncertain intent)
        2. Intent is "unknown"
        3. Intent is clear but missing critical entities
        4. Parameters are vague or problematic

        Args:
            intent: Parsed intent

        Returns:
            True if clarification is needed

        Example:
            >>> intent = RequestIntent(
            ...     intent_type="single_prediction",
            ...     confidence=0.7,
            ...     home_team=None,
            ...     away_team=None,
            ...     original_query="Show me the prediction"
            ... )
            >>> assert nlu.needs_clarification(intent) == True
        """
        # Always clarify unknown intents
        if intent.intent_type == "unknown":
            return True

        # Clarify low confidence intents
        if intent.confidence < 0.7:
            return True

        # Check for missing critical entities based on intent type
        if intent.intent_type == "single_prediction":
            if not intent.home_team and not intent.away_team and not intent.match_id:
                return True

        if intent.intent_type == "batch_prediction":
            # Missing target_odds is acceptable (system defaults to 20)
            # But if target_odds > 80, clarify to refine
            if intent.target_odds and intent.target_odds > 80:
                return True

        if intent.intent_type == "get_match_results":
            # Missing league and team means no filter (show all results)
            # But very broad, might want to clarify
            if not intent.leagues and not intent.home_team and not intent.away_team:
                # Only clarify if confidence is not high
                if intent.confidence < 0.8:
                    return True

        return False

    async def generate_clarification(
        self,
        intent: RequestIntent,
        conversation_context: dict[str, Any] | None = None,
    ) -> ClarificationResponse:
        """
        Generate intelligent clarification for unclear intent.

        Delegates to ClarificationAgent to analyze the intent and generate
        contextual, helpful clarification messages.

        Args:
            intent: Parsed intent needing clarification
            conversation_context: Optional conversation context

        Returns:
            ClarificationResponse with message and suggested actions

        Example:
            >>> intent = RequestIntent(
            ...     intent_type="unknown",
            ...     confidence=0.2,
            ...     original_query="Give me something"
            ... )
            >>> clarification = await nlu.generate_clarification(intent)
            >>> assert clarification.clarification_type == "guide_to_feature"
        """
        return await self.clarification_agent.generate_clarification(intent, conversation_context)

    async def _parse_with_claude(
        self,
        message: str,
        context: dict[str, Any],
    ) -> RequestIntent:
        """
        Parse message with Claude NLU agent.

        This method will use Strands Agents framework with Claude 3.5 Sonnet
        to parse the message into structured RequestIntent output.

        The system prompt is loaded from sipap/sports/soccer/agents/nlu.yml

        Args:
            message: User query string
            context: Conversation context

        Returns:
            RequestIntent with parsed intent and entities

        Note:
            This is a placeholder implementation. Full Claude integration will be
            added once nlu.yml system prompt is complete.
        """
        # TODO: Implement Claude agent integration with Strands
        # For now, return low confidence to trigger regex fallback during tests
        self.logger.debug("Claude parsing not yet implemented, using regex fallback")

        # Placeholder: Parse basic patterns until Claude is integrated
        return await self._parse_with_basic_heuristics(message, context)

    async def _parse_with_basic_heuristics(
        self,
        message: str,
        context: dict[str, Any],  # noqa: ARG002 - Reserved for future context resolution
    ) -> RequestIntent:
        """
        Basic heuristic parsing (temporary until Claude is integrated).

        This provides better-than-regex parsing for common patterns while we
        integrate Claude. Will be replaced by _parse_with_claude once complete.

        Args:
            message: User query string
            context: Conversation context

        Returns:
            RequestIntent with parsed intent and entities
        """
        message_lower = message.lower()
        entities: dict[str, Any] = {}

        # Check for sports/betting keywords to ensure context is relevant
        # CRITICAL: Require domain-specific keywords to avoid false positives
        sports_keywords = [
            "odds", "odd", "prediction", "predictions", "match", "matches",
            "fixture", "fixtures", "bet", "betting", "accumulator", "parlay",
            "selection", "selections", "game", "games", "vs", "against",
            "team", "teams", "league", "leagues", "soccer", "football",
            "basketball", "tennis", "sport", "sports"
        ]
        has_sports_context = any(keyword in message_lower for keyword in sports_keywords)

        # Detect intent type (order matters - check most specific first)
        if any(term in message_lower for term in ["update", "result", "how did", "what happened", "wrong"]):
            # Track results if asking about past predictions
            if any(term in message_lower for term in ["your", "suggested", "selections", "picks", "wrong"]):
                intent_type = "track_results"
                confidence = 0.8
            else:
                intent_type = "unknown"
                confidence = 0.5
        elif any(term in message_lower for term in ["why", "explain", "reasoning"]) and "what" not in message_lower:
            intent_type = "explain"
            confidence = 0.8
        else:
            # Check for batch prediction indicators
            has_number = bool(
                re.search(r"\b(\d+)\s+(odds|matches|selections)", message_lower)
                or re.search(r"of\s+(\d+)\s+(odds|matches|selections)", message_lower)
            )
            has_quality = any(
                term in message_lower
                for term in ["sure", "best", "highest", "positive", "success", "good"]
            )
            has_multiple_teams = len(re.findall(r"\bvs\b|\bagainst\b", message_lower)) > 1

            # Fixture queries with no quality/number indicators
            is_fixture_query = any(
                term in message_lower for term in ["available matches", "fixtures available", "what are the"]
            ) and not has_quality

            if is_fixture_query and not has_number:
                intent_type = "show_fixtures"
                confidence = 0.7 if has_sports_context else 0.4
            elif has_number and has_sports_context:
                # Explicit number + sports context = high confidence batch prediction
                intent_type = "batch_prediction"
                confidence = 0.8
            elif has_number and not has_sports_context:
                # Number but no sports context = unknown (e.g., "I need 20 items")
                intent_type = "unknown"
                confidence = 0.3
            elif has_quality and has_sports_context and not is_fixture_query:
                # Quality terms + sports context = batch prediction
                intent_type = "batch_prediction"
                confidence = 0.7
            elif has_quality and not has_sports_context:
                # Quality terms but no sports context = unknown (e.g., "Show me something good")
                intent_type = "unknown"
                confidence = 0.3
            elif has_multiple_teams and "what do you think" in message_lower:
                # Multiple fixtures asked about = batch prediction
                intent_type = "batch_prediction"
                confidence = 0.7
            elif "vs" in message_lower or "against" in message_lower:
                intent_type = "single_prediction"
                confidence = 0.7
            else:
                intent_type = "unknown"
                confidence = 0.3

        # Extract target_odds and accumulation_mode
        # CRITICAL: In sports betting, "X odds" means ACCUMULATED ODDS (sum of bookmaker odds)
        # NOT number of matches!
        target_odds = None
        accumulation_mode = False

        # Find all numbers followed by odds/matches/selections (with 0-2 words between)
        # This prevents matching "1 need 30 sure odds" as a single match
        all_matches = list(
            re.finditer(r"\b(\d+)\s+(?:\w+\s+){0,2}(odds|matches|selections)", message_lower)
        )

        if all_matches:
            # If multiple matches, prefer the largest number (likely the actual request)
            # This handles cases like "1 need 30 sure odds" (finds both 1 and 30, picks 30)
            best_match = max(all_matches, key=lambda m: int(m.group(1)))
            number = int(best_match.group(1))
            keyword = best_match.group(2)

            # "X odds" or "X matches" in betting context = accumulated odds
            if keyword in ["odds", "matches", "selections"]:
                target_odds = min(float(number), 100.0)  # Cap at 100 odds
                accumulation_mode = True
                entities["target_odds"] = target_odds
                entities["accumulation_mode"] = True
        else:
            # Pattern 2: "of X odds/matches/selections"
            match = re.search(r"of\s+(\d+)\s+(?:\w+\s+){0,2}(odds|matches|selections)", message_lower)
            if not match:
                # Pattern 3: "selections of X"
                match = re.search(r"(selections|matches|odds)\s+of\s+(\d+)", message_lower)
                if match:
                    target_odds = min(float(match.group(2)), 100.0)
                    accumulation_mode = True
                    entities["target_odds"] = target_odds
                    entities["accumulation_mode"] = True
            elif match:
                target_odds = min(float(match.group(1)), 100.0)
                accumulation_mode = True
                entities["target_odds"] = target_odds
                entities["accumulation_mode"] = True

        # Extract quality threshold
        quality_threshold = None
        if any(term in message_lower for term in ["sure", "highest", "very high"]):
            quality_threshold = "highest"
            entities["quality_terms"] = ["sure", "highest positive", "very high success"]
        elif any(term in message_lower for term in ["best", "good", "positive", "success"]):
            quality_threshold = "high"
            entities["quality_terms"] = ["best possible", "good chance", "success"]

        # Extract leagues using comprehensive mappings (380 competitions) from sipap-common
        from sipap_common.data import find_league_matches

        leagues = find_league_matches(message)

        if leagues:
            entities["leagues"] = leagues
            self.logger.debug(
                f"Matched leagues: {leagues}",
                extra={"query": message[:50], "leagues": leagues}
            )

        # NOTE: Markets are NOT extracted from user messages
        # Users don't specify markets - they only express intent and quality requirements.
        # The system intelligently selects the best market per fixture by:
        # 1. Evaluating multiple markets (1X2, BTTS, OU2.5, DC, etc.)
        # 2. Comparing EV and confidence across markets
        # 3. Selecting the market with highest expected value
        # 4. Including market explanation in response ("BTTS Yes @ 2.5 odds")
        #
        # Example:
        #   User: "I need 20 odds with highest positive outcome"
        #   NLU: target_odds=20, quality="highest", markets=None
        #   BatchOrchestrator: For each fixture, evaluate all markets, pick best
        #   Response: "Arsenal vs Chelsea - BTTS Yes @ 2.5 odds (72% conf, +10% EV)"

        # Extract date range
        date_range = None
        today = datetime.now(UTC).date()

        if "today" in message_lower:
            date_range = {
                "start": today.isoformat(),
                "end": today.isoformat(),
            }
            entities["date"] = "today"
        elif "tomorrow" in message_lower:
            tomorrow = today + timedelta(days=1)
            date_range = {
                "start": tomorrow.isoformat(),
                "end": tomorrow.isoformat(),
            }
            entities["date"] = "tomorrow"
        elif "weekend" in message_lower or "this weekend" in message_lower:
            # Find next Saturday
            days_ahead = 5 - today.weekday()  # Saturday is 5
            if days_ahead <= 0:
                days_ahead += 7
            saturday = today + timedelta(days=days_ahead)
            sunday = saturday + timedelta(days=1)
            date_range = {
                "start": saturday.isoformat(),
                "end": sunday.isoformat(),
            }
            entities["date"] = "this weekend"

        # Extract explicit date ranges (e.g., "3rd of August, 2026 to 10th of August, 2026")
        date_range_match = re.search(
            r"(\d+)(?:st|nd|rd|th)?\s+of\s+(\w+),?\s+(\d{4})\s+to\s+(\d+)(?:st|nd|rd|th)?\s+of\s+(\w+),?\s+(\d{4})",
            message,
            re.IGNORECASE,
        )
        if date_range_match:
            try:
                start_day = int(date_range_match.group(1))
                start_month = date_range_match.group(2)
                start_year = int(date_range_match.group(3))
                end_day = int(date_range_match.group(4))
                end_month = date_range_match.group(5)
                end_year = int(date_range_match.group(6))

                # Parse month names
                month_map = {
                    "january": 1,
                    "february": 2,
                    "march": 3,
                    "april": 4,
                    "may": 5,
                    "june": 6,
                    "july": 7,
                    "august": 8,
                    "september": 9,
                    "october": 10,
                    "november": 11,
                    "december": 12,
                }

                start_month_num = month_map.get(start_month.lower(), 1)
                end_month_num = month_map.get(end_month.lower(), 1)

                start_date = datetime(start_year, start_month_num, start_day).date()
                end_date = datetime(end_year, end_month_num, end_day).date()

                date_range = {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }
                entities["date_range"] = f"{start_date} to {end_date}"

            except (ValueError, KeyError) as e:
                self.logger.warning(f"Failed to parse date range: {e}")

        # Alternative date format: 7/3/2026 - 7/10/2026
        if not date_range:
            date_range_match2 = re.search(r"(\d+)/(\d+)/(\d{4})\s*-\s*(\d+)/(\d+)/(\d{4})", message)
            if date_range_match2:
                try:
                    start_date = datetime(
                        int(date_range_match2.group(3)),  # year
                        int(date_range_match2.group(1)),  # month
                        int(date_range_match2.group(2)),  # day
                    ).date()
                    end_date = datetime(
                        int(date_range_match2.group(6)),  # year
                        int(date_range_match2.group(4)),  # month
                        int(date_range_match2.group(5)),  # day
                    ).date()

                    date_range = {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                    }
                    entities["date_range"] = f"{start_date} to {end_date}"

                except ValueError as e:
                    self.logger.warning(f"Failed to parse date range: {e}")

        # Extract teams (for single prediction)
        home_team = None
        away_team = None
        # Better pattern: Team name starts with capital letter
        teams_match = re.search(
            r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+vs\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)",
            message,
        )
        if teams_match:
            home_team = teams_match.group(1).strip()
            away_team = teams_match.group(2).strip()
            entities["home_team"] = home_team
            entities["away_team"] = away_team

        # Build RequestIntent
        return RequestIntent(
            intent_type=intent_type,  # type: ignore[arg-type]
            confidence=confidence,
            target_odds=target_odds,
            accumulation_mode=accumulation_mode,
            leagues=leagues if leagues else None,
            date_range=date_range,
            markets=None,  # NOT extracted from user messages - system decides best market
            quality_threshold=quality_threshold,  # type: ignore[arg-type]
            home_team=home_team,
            away_team=away_team,
            original_query=message,
            extracted_entities=entities,
        )

    def _convert_regex_to_request_intent(
        self,
        regex_result: dict[str, Any],
        original_query: str,
    ) -> RequestIntent:
        """
        Convert regex parser result to RequestIntent format.

        Args:
            regex_result: Result from IntentParser.parse()
            original_query: Original user query

        Returns:
            RequestIntent matching the regex result
        """
        intent_str = regex_result.get("intent", "unknown")
        entities = regex_result.get("entities", {})
        confidence = regex_result.get("confidence", 0.5)

        # Map old Intent enum to new intent_type literal
        intent_map = {
            Intent.GET_PREDICTION.value: "single_prediction",
            Intent.SHOW_FIXTURES.value: "show_fixtures",
            Intent.CHECK_ODDS.value: "check_odds",
            Intent.EXPLAIN_PREDICTION.value: "explain",
            Intent.UNKNOWN.value: "unknown",
        }

        intent_type = intent_map.get(intent_str, "unknown")

        return RequestIntent(
            intent_type=intent_type,  # type: ignore[arg-type]
            confidence=confidence,
            home_team=entities.get("home_team"),
            away_team=entities.get("away_team"),
            markets=None,  # NOT extracted - system decides best market per fixture
            date_range=(
                {"start": entities["date"], "end": entities["date"]} if entities.get("date") else None
            ),
            original_query=original_query,
            extracted_entities=entities,
        )


class ClarificationResponse(BaseModel):
    """Structured clarification response for unclear user requests."""

    clarification_type: Literal[
        "ask_for_missing_entity",  # Know intent but missing key info
        "disambiguate_intent",  # Multiple possible intents
        "guide_to_feature",  # Very unclear, guide to capabilities
        "refine_request",  # Intent clear but parameters vague
    ]
    message: str  # Friendly clarification message for WhatsApp user
    suggested_actions: list[dict[str, Any]]  # Numbered actions with examples
    follow_up_context: dict[str, Any] | None = None  # Context to preserve

    model_config = ConfigDict(frozen=False)


class ClarificationAgent:
    """
    Generates intelligent clarification messages for unclear user requests.

    Uses Claude AI to analyze low-confidence intents and generate contextual,
    helpful responses that guide users toward what they need.

    Strategies:
    1. ask_for_missing_entity: Intent clear, missing critical data
    2. disambiguate_intent: Multiple possible interpretations
    3. guide_to_feature: Very unclear, show capabilities
    4. refine_request: Intent clear but parameters vague

    Example:
        >>> clarifier = ClarificationAgent()
        >>> response = await clarifier.generate_clarification(
        ...     intent=RequestIntent(
        ...         intent_type="single_prediction",
        ...         confidence=0.7,
        ...         home_team=None,
        ...         away_team=None,
        ...         original_query="Show me the prediction"
        ...     )
        ... )
        >>> print(response.message)
        "I'd be happy to show you a prediction! Which match are you interested in?"
    """

    def __init__(self, logger: logging.Logger | None = None, use_claude: bool = True):
        """Initialize clarification agent.

        Args:
            logger: Optional logger instance
            use_claude: Use Claude for dynamic clarifications (default: True)
                       Falls back to rules if Claude fails or is disabled
        """
        self.logger = logger or get_logger(__name__)
        self.use_claude = use_claude

        # Initialize Claude NLU client for conversational clarifications
        self._claude_client: Any | None = None
        if use_claude:
            try:
                from sipap.conversation.claude_nlu import ClaudeNLUClient
                self._claude_client = ClaudeNLUClient(logger=self.logger)
                self.logger.info("ClarificationAgent initialized with Claude support")
            except Exception as e:
                self.logger.warning(
                    f"Failed to initialize Claude NLU client: {e}. "
                    "Falling back to rule-based clarifications."
                )
                self.use_claude = False
        else:
            self.logger.info("ClarificationAgent initialized (rule-based mode)")

    async def generate_clarification(
        self,
        intent: RequestIntent,
        conversation_context: dict[str, Any] | None = None,
    ) -> ClarificationResponse:
        """
        Generate intelligent clarification message for unclear intent.

        Args:
            intent: Parsed intent with low confidence or missing entities
            conversation_context: Optional conversation history

        Returns:
            ClarificationResponse with message and suggested actions

        Example:
            >>> response = await clarifier.generate_clarification(
            ...     intent=RequestIntent(
            ...         intent_type="unknown",
            ...         confidence=0.2,
            ...         original_query="Give me something good",
            ...         extracted_entities={}
            ...     )
            ... )
            >>> assert response.clarification_type == "guide_to_feature"
        """
        conversation_context = conversation_context or {}

        # Try Claude first for dynamic, conversational clarifications
        if self.use_claude and self._claude_client:
            try:
                claude_response = await self._generate_with_claude(intent, conversation_context)
                self.logger.info(
                    "Generated Claude-powered clarification",
                    extra={
                        "confidence": intent.confidence,
                        "intent_type": intent.intent_type,
                        "response_length": len(claude_response.message),
                    }
                )
                return claude_response
            except Exception as e:
                self.logger.warning(
                    f"Claude clarification failed: {e}. Falling back to rules.",
                    exc_info=True
                )
                # Continue to rule-based fallback below

        # Fallback: Rule-based clarification
        clarification_type = self._determine_strategy(intent)
        response = await self._generate_with_rules(intent, clarification_type, conversation_context)

        self.logger.info(
            f"Generated rule-based clarification: {clarification_type}",
            extra={"confidence": intent.confidence, "intent_type": intent.intent_type},
        )

        return response

    async def _generate_with_claude(
        self,
        intent: RequestIntent,
        context: dict[str, Any],
    ) -> ClarificationResponse:
        """
        Generate clarification using Claude AI (conversational, dynamic).

        This replaces hardcoded templates with intelligent, context-aware
        responses generated by Claude 3.5 Sonnet.

        Args:
            intent: Parsed intent with low confidence or missing entities
            context: Conversation context (history, user preferences, etc.)

        Returns:
            ClarificationResponse with Claude-generated message

        Raises:
            Exception: If Claude API call fails (caller should fallback to rules)
        """
        # Extract conversation history if available
        conversation_history = context.get("conversation_history", [])

        # Call Claude to generate clarification
        message_text = await self._claude_client.generate_clarification(
            query=intent.original_query,
            intent_confidence=intent.confidence,
            detected_intent=intent.intent_type,
            extracted_entities=intent.extracted_entities,
            conversation_history=conversation_history,
        )

        # Validate character limit (should be enforced by Claude, but double-check)
        if len(message_text) > 1600:
            self.logger.warning(
                f"Claude response exceeded 1600 chars ({len(message_text)}). Truncating."
            )
            message_text = message_text[:1590] + "..."

        # Build ClarificationResponse
        # Claude generates free-form text, so we don't have structured suggested_actions
        # We'll return a simpler response format
        return ClarificationResponse(
            clarification_type="guide_to_feature",  # Generic type for Claude responses
            message=message_text,
            suggested_actions=[],  # Claude embeds examples in the message text
            follow_up_context={
                "claude_generated": True,
                "original_query": intent.original_query,
                "detected_intent": intent.intent_type,
                "confidence": intent.confidence,
            },
        )

    def _determine_strategy(self, intent: RequestIntent) -> str:
        """
        Determine appropriate clarification strategy.

        Decision tree:
        1. If confidence < 0.4 and no useful entities → guide_to_feature
        2. If confidence 0.4-0.6 with some entities → disambiguate_intent
        3. If confidence ≥ 0.5 but missing critical entities → ask_for_missing_entity
        4. If confidence ≥ 0.6 but vague parameters → refine_request

        Args:
            intent: Parsed intent

        Returns:
            Clarification strategy name
        """
        has_entities = bool(intent.extracted_entities and len(intent.extracted_entities) > 0)
        has_teams = bool(intent.home_team or intent.away_team)
        has_leagues = bool(intent.leagues and len(intent.leagues) > 0)

        # Very low confidence, no useful entities
        if intent.confidence < 0.4 and not has_entities:
            return "guide_to_feature"

        # Medium confidence with some context
        if 0.4 <= intent.confidence < 0.6 and (has_leagues or has_teams or has_entities):
            return "disambiguate_intent"

        # Clear intent but missing critical data
        if intent.confidence >= 0.5:
            # Check for missing critical entities based on intent
            if intent.intent_type == "single_prediction" and not has_teams:
                return "ask_for_missing_entity"
            if intent.intent_type == "batch_prediction" and intent.target_odds is None:
                return "ask_for_missing_entity"
            if intent.intent_type == "get_match_results" and not (has_leagues or has_teams):
                return "ask_for_missing_entity"

            # Has intent and entities but vague parameters
            if intent.target_odds and intent.target_odds > 80:  # Too ambitious
                return "refine_request"

            # Default for moderate confidence
            return "ask_for_missing_entity"

        # Default fallback
        return "guide_to_feature"

    async def _generate_with_rules(
        self,
        intent: RequestIntent,
        clarification_type: str,
        context: dict[str, Any],  # noqa: ARG002 - Reserved for future context-aware responses
    ) -> ClarificationResponse:
        """
        Generate clarification using rule-based templates.

        This is a placeholder until Claude agent integration is complete.

        Args:
            intent: Parsed intent
            clarification_type: Clarification strategy
            context: Conversation context

        Returns:
            ClarificationResponse with message and actions
        """
        # Strategy 1: ask_for_missing_entity
        if clarification_type == "ask_for_missing_entity":
            if intent.intent_type == "single_prediction":
                return ClarificationResponse(
                    clarification_type="ask_for_missing_entity",
                    message="I'd be happy to show you a prediction! Which match are you interested in?",
                    suggested_actions=[
                        {
                            "number": "1",
                            "label": "Example format",
                            "example": "Arsenal vs Chelsea",
                        }
                    ],
                    follow_up_context={
                        "detected_intent": "single_prediction",
                        "awaiting": "team_names",
                        "original_query": intent.original_query,
                    },
                )
            elif intent.intent_type == "batch_prediction":
                league_context = ""
                if intent.leagues and len(intent.leagues) > 0:
                    league_context = f"{', '.join(intent.leagues)} "

                return ClarificationResponse(
                    clarification_type="ask_for_missing_entity",
                    message=f"Got it, you want {league_context}predictions. How many accumulated odds are you targeting?",
                    suggested_actions=[
                        {"number": "1", "label": "20 odds (recommended)", "example": "Give me 20 odds"},
                        {"number": "2", "label": "30 odds", "example": "Give me 30 odds"},
                        {"number": "3", "label": "Let SIPAP decide", "example": "Best possible outcome"},
                    ],
                    follow_up_context={
                        "detected_intent": "batch_prediction",
                        "leagues": intent.leagues,
                        "awaiting": "target_odds",
                        "original_query": intent.original_query,
                    },
                )
            elif intent.intent_type == "get_match_results":
                return ClarificationResponse(
                    clarification_type="ask_for_missing_entity",
                    message="I can show you match results! Which competition or team are you interested in?",
                    suggested_actions=[
                        {"number": "1", "label": "Specific team", "example": "Arsenal results today"},
                        {
                            "number": "2",
                            "label": "Specific competition",
                            "example": "Premier League results",
                        },
                        {"number": "3", "label": "All live matches", "example": "Show me live matches"},
                    ],
                    follow_up_context={
                        "detected_intent": "get_match_results",
                        "awaiting": "league_or_team",
                        "original_query": intent.original_query,
                    },
                )

        # Strategy 2: disambiguate_intent
        elif clarification_type == "disambiguate_intent":
            # Check what entities we have
            if intent.home_team or intent.away_team:
                team_name = intent.home_team or intent.away_team or "this team"
                return ClarificationResponse(
                    clarification_type="disambiguate_intent",
                    message=f"I see you're asking about {team_name} matches. What would you like?",
                    suggested_actions=[
                        {
                            "number": "1",
                            "label": "🎯 Prediction for best outcome",
                            "example": f"{team_name} prediction",
                        },
                        {"number": "2", "label": "📊 Recent match results", "example": f"{team_name} results"},
                        {"number": "3", "label": "📅 Upcoming fixtures", "example": f"{team_name} schedule"},
                    ],
                    follow_up_context={
                        "detected_team": team_name,
                        "awaiting": "intent_disambiguation",
                        "original_query": intent.original_query,
                    },
                )
            elif intent.leagues and len(intent.leagues) > 0:
                league_name = intent.leagues[0]
                return ClarificationResponse(
                    clarification_type="disambiguate_intent",
                    message=f"I can help with {league_name}! What are you looking for?",
                    suggested_actions=[
                        {
                            "number": "1",
                            "label": "🎯 Best predictions (accumulated odds)",
                            "example": f"20 odds from {league_name}",
                        },
                        {
                            "number": "2",
                            "label": "📊 Recent results/scores",
                            "example": f"{league_name} results today",
                        },
                        {
                            "number": "3",
                            "label": "📅 Upcoming matches",
                            "example": f"{league_name} fixtures",
                        },
                    ],
                    follow_up_context={
                        "detected_league": league_name,
                        "awaiting": "intent_disambiguation",
                        "original_query": intent.original_query,
                    },
                )

        # Strategy 3: guide_to_feature
        elif clarification_type == "guide_to_feature":
            # Check if it's a greeting
            if any(
                greeting in intent.original_query.lower() for greeting in ["hi", "hello", "hey", "good morning"]
            ):
                return ClarificationResponse(
                    clarification_type="guide_to_feature",
                    message="Hey! 👋 I'm SIPAP. I help you find smart betting opportunities. Try:",
                    suggested_actions=[
                        {"number": "1", "label": "Get predictions", "example": "Give me 20 odds"},
                        {"number": "2", "label": "Check results", "example": "Arsenal results today"},
                        {"number": "3", "label": "See fixtures", "example": "What matches are available?"},
                    ],
                    follow_up_context=None,
                )
            else:
                return ClarificationResponse(
                    clarification_type="guide_to_feature",
                    message="I'm here to help! Here's what I can do for you:",
                    suggested_actions=[
                        {
                            "number": "1",
                            "label": "🎯 Get predictions (accumulated odds)",
                            "example": "Give me 20 odds with highest success",
                        },
                        {
                            "number": "2",
                            "label": "📊 Check match results/scores",
                            "example": "Show me Arsenal results today",
                        },
                        {
                            "number": "3",
                            "label": "📅 View upcoming fixtures",
                            "example": "What matches are available?",
                        },
                    ],
                    follow_up_context=None,
                )

        # Strategy 4: refine_request
        elif clarification_type == "refine_request":
            if intent.target_odds and intent.target_odds > 80:
                return ClarificationResponse(
                    clarification_type="refine_request",
                    message=f"{intent.target_odds:.0f} odds is quite ambitious! For better quality predictions, I recommend:",
                    suggested_actions=[
                        {
                            "number": "1",
                            "label": "20-30 odds (highest quality)",
                            "example": "Give me 20 odds",
                        },
                        {"number": "2", "label": "30-50 odds (high quality)", "example": "Give me 40 odds"},
                        {
                            "number": "3",
                            "label": f"Keep {intent.target_odds:.0f} odds (lower quality)",
                            "example": f"Proceed with {intent.target_odds:.0f} odds",
                        },
                    ],
                    follow_up_context={
                        "original_target_odds": intent.target_odds,
                        "awaiting": "refined_target_odds",
                        "original_query": intent.original_query,
                    },
                )

        # Default fallback
        return ClarificationResponse(
            clarification_type="guide_to_feature",
            message="I didn't quite understand that. I can help you with:",
            suggested_actions=[
                {"number": "1", "label": "Get predictions", "example": "Give me 20 odds"},
                {"number": "2", "label": "Check results", "example": "Arsenal results"},
                {"number": "3", "label": "See fixtures", "example": "What matches are available?"},
            ],
            follow_up_context=None,
        )
