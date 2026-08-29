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


# Maximum markets allowed per batch prediction request
# Users must specify which markets they want to avoid evaluating all 44 markets
MAX_MARKETS_PER_REQUEST = 5

# Guidance message for users who don't specify markets
MARKET_GUIDANCE_MESSAGE = """Please specify which markets you want predictions for (max 5 per request).

*Popular Markets:*
• Match Winner (1X2)
• Both Teams to Score (BTTS)
• Over/Under 2.5 Goals (OU2.5)
• Double Chance (DC)
• Draw No Bet (DNB)

*Combination Markets:*
• BTTS + Over 2.5
• Winner + BTTS
• Chance Mix

*Example requests:*
"BTTS and Over 2.5 for Premier League"
"Match winner, DC and DNB for La Liga today"
"Give me 1X2 and BTTS predictions for Spain"

What markets would you like?"""

# Patterns for recognizing subscription cancellation requests
CANCEL_SUBSCRIPTION_PATTERNS = [
    r"cancel\s*(my)?\s*subscription",
    r"stop\s*(my)?\s*subscription",
    r"unsubscribe",
    r"cancel\s*(my)?\s*plan",
    r"end\s*(my)?\s*subscription",
    r"terminate\s*(my)?\s*subscription",
    r"don'?t\s*renew",
    r"stop\s*charging",
]


class LeagueEntity(BaseModel):
    """Structured league entity with API-Football ID for unambiguous resolution.

    This model ensures leagues are resolved to their unique API-Football IDs,
    eliminating string matching ambiguity (e.g., "Premier League" exists in
    multiple countries: England=39, Wales=113, Belarus=117).

    The id field is the API-Football competition ID which maps directly to
    the external_id column in the database leagues table.

    Example:
        >>> league = LeagueEntity(id=140, name="La Liga", country="Spain")
        >>> # Can now query: WHERE external_id = '140'
    """

    id: int  # API-Football competition ID (e.g., 140 for La Liga)
    name: str  # Canonical name (e.g., "La Liga")
    country: str | None = None  # Country for disambiguation (e.g., "Spain")

    model_config = ConfigDict(frozen=True)  # Immutable once created


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

    LEAGUE RESOLUTION:
    The leagues field now contains LeagueEntity objects with API-Football IDs.
    This enables unambiguous resolution:
    - "La Liga" → LeagueEntity(id=140, name="La Liga", country="Spain")
    - "Premier League" (England) → LeagueEntity(id=39, name="Premier League", country="England")
    - "Premier League" (Belarus) → LeagueEntity(id=117, name="Premier League", country="Belarus")

    Example:
        >>> intent = RequestIntent(
        ...     intent_type="batch_prediction",
        ...     confidence=0.9,
        ...     target_odds=20.0,  # Accumulate until sum >= 20
        ...     accumulation_mode=True,
        ...     leagues=[LeagueEntity(id=140, name="La Liga", country="Spain")],
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
        "cancel_subscription",  # User wants to cancel their subscription
        "unknown",  # Cannot determine intent
    ]
    confidence: float = Field(ge=0.0, le=1.0)  # Confidence score 0.0-1.0

    # Batch prediction parameters (ACCUMULATION MODE)
    target_odds: float | None = Field(default=None, ge=1.0, le=100.0)  # Target accumulated odds
    accumulation_mode: bool = False  # True when user wants accumulated odds (default behavior)
    num_matches: int | None = Field(default=None, ge=1, le=50)  # Explicit fixture count (rare)

    leagues: list[LeagueEntity] | None = None  # [LeagueEntity(id=140, name="La Liga", country="Spain"), ...]
    date_range: dict[str, str] | None = None  # {"start": "2026-08-03", "end": "2026-08-10"}
    markets: list[str] | None = None  # Market codes extracted by Claude NLU (e.g., ["BTTS", "1X2"])
    quality_threshold: Literal["highest", "high", "medium"] | None = None
    sort_by: Literal["ev", "confidence", "probability"] | None = "ev"

    # Single prediction parameters
    home_team: str | None = None
    away_team: str | None = None
    match_id: str | None = None

    # Context
    original_query: str
    extracted_entities: dict[str, Any] = Field(default_factory=dict)

    # Guidance for incomplete batch prediction requests
    needs_market_specification: bool = False  # True when user must specify markets
    guidance_message: str | None = None  # Message to send when request needs clarification

    # Subscription-based date validation
    needs_date_adjustment: bool = False  # True when requested date exceeds subscription period

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

        # Check for subscription cancellation FIRST (before Claude NLU)
        if self._is_cancellation_request(message):
            self.logger.info("Detected subscription cancellation request")
            return RequestIntent(
                intent_type="cancel_subscription",
                confidence=1.0,
                original_query=message,
            )

        # Primary: Claude-based NLU
        try:
            claude_intent = await self._parse_with_claude(message, conversation_context)

            if claude_intent.confidence >= 0.5:
                self.logger.info(
                    f"Claude NLU parsed: {claude_intent.intent_type} "
                    f"(confidence: {claude_intent.confidence:.2f})"
                )
                # Validate batch prediction markets before returning
                return self._validate_batch_markets(claude_intent)

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
            # Validate batch prediction markets before returning
            return self._validate_batch_markets(regex_intent)

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

    def _validate_batch_markets(self, intent: RequestIntent) -> RequestIntent:
        """Validate market specification for batch prediction requests.

        For batch predictions, users MUST specify which markets they want to avoid
        evaluating all 44 markets per fixture (which takes ~14 hours).

        Rules:
        1. Users must specify at least one market
        2. Maximum 5 markets per request
        3. If rules violated, return intent with guidance message

        Args:
            intent: Parsed RequestIntent to validate

        Returns:
            RequestIntent with needs_market_specification=True and guidance_message
            if validation fails, otherwise the original intent
        """
        # Only validate batch_prediction intents
        if intent.intent_type != "batch_prediction":
            return intent

        # Case 1: No markets specified - need clarification
        if intent.markets is None or len(intent.markets) == 0:
            self.logger.info(
                "Batch prediction missing market specification - requesting clarification",
                extra={"original_query": intent.original_query[:50]},
            )
            return RequestIntent(
                intent_type=intent.intent_type,
                confidence=intent.confidence,
                target_odds=intent.target_odds,
                accumulation_mode=intent.accumulation_mode,
                num_matches=intent.num_matches,
                leagues=intent.leagues,
                date_range=intent.date_range,
                markets=None,
                quality_threshold=intent.quality_threshold,
                sort_by=intent.sort_by,
                home_team=intent.home_team,
                away_team=intent.away_team,
                match_id=intent.match_id,
                original_query=intent.original_query,
                extracted_entities=intent.extracted_entities,
                needs_market_specification=True,
                guidance_message=MARKET_GUIDANCE_MESSAGE,
            )

        # Case 2: Too many markets - limit to 5 and provide guidance
        if len(intent.markets) > MAX_MARKETS_PER_REQUEST:
            suggested = intent.markets[:MAX_MARKETS_PER_REQUEST]
            self.logger.info(
                f"Batch prediction has too many markets ({len(intent.markets)}) - limiting to {MAX_MARKETS_PER_REQUEST}",
                extra={"markets": intent.markets, "suggested": suggested},
            )
            return RequestIntent(
                intent_type=intent.intent_type,
                confidence=intent.confidence,
                target_odds=intent.target_odds,
                accumulation_mode=intent.accumulation_mode,
                num_matches=intent.num_matches,
                leagues=intent.leagues,
                date_range=intent.date_range,
                markets=suggested,  # First 5 as suggestion
                quality_threshold=intent.quality_threshold,
                sort_by=intent.sort_by,
                home_team=intent.home_team,
                away_team=intent.away_team,
                match_id=intent.match_id,
                original_query=intent.original_query,
                extracted_entities=intent.extracted_entities,
                needs_market_specification=True,
                guidance_message=(
                    f"Please limit to {MAX_MARKETS_PER_REQUEST} markets per request. "
                    f"You requested {len(intent.markets)} markets.\n\n"
                    f"Suggested: {', '.join(suggested)}\n\n"
                    f"Send another message with additional markets if needed."
                ),
            )

        # Valid: 1-5 markets specified
        self.logger.debug(
            f"Batch prediction has valid market specification: {intent.markets}"
        )
        return intent

    def _is_cancellation_request(self, message: str) -> bool:
        """Check if message is a subscription cancellation request.

        Args:
            message: User message to check

        Returns:
            True if the message matches cancellation patterns

        Example:
            >>> nlu._is_cancellation_request("cancel my subscription")
            True
            >>> nlu._is_cancellation_request("give me btts predictions")
            False
        """
        message_lower = message.lower().strip()
        for pattern in CANCEL_SUBSCRIPTION_PATTERNS:
            if re.search(pattern, message_lower):
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

        Uses Claude Sonnet 4.5 via AWS Bedrock to parse user messages into
        structured RequestIntent with intelligent entity extraction.

        Args:
            message: User query string
            context: Conversation context

        Returns:
            RequestIntent with parsed intent and entities
        """
        # Lazy initialize Claude client
        if self._claude_agent is None and self.use_claude:
            try:
                from sipap.conversation.claude_nlu import ClaudeNLUClient
                self._claude_agent = ClaudeNLUClient()
            except Exception as e:
                self.logger.error(f"Failed to initialize Claude NLU client: {e}")
                self.use_claude = False
                return await self._parse_with_basic_heuristics(message, context)

        if not self.use_claude or self._claude_agent is None:
            return await self._parse_with_basic_heuristics(message, context)

        try:
            # Call Claude to parse intent
            intent_data = await self._invoke_claude_for_intent(message, context)

            # Build RequestIntent from Claude's response
            return self._build_intent_from_claude_response(intent_data, message)

        except Exception as e:
            self.logger.error(f"Claude intent parsing failed: {e}, falling back to heuristics")
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
        # Core betting/sports terms (static)
        core_sports_keywords = {
            "odds", "odd", "prediction", "predictions", "match", "matches",
            "fixture", "fixtures", "bet", "betting", "accumulator", "parlay",
            "selection", "selections", "game", "games", "vs", "against",
            "team", "teams", "league", "leagues", "soccer", "football",
            "basketball", "tennis", "sport", "sports", "score", "scores",
            "result", "results",
        }

        # Dynamic league keywords from LEAGUE_REFERENCE (no hardcoding!)
        try:
            from sipap_common.data.league_reference import get_sports_context_keywords
            league_keywords = set(get_sports_context_keywords())  # Convert list to set
        except ImportError:
            league_keywords = set()  # Fallback if import fails

        # Combine static + dynamic keywords
        sports_keywords = core_sports_keywords | league_keywords
        has_sports_context = any(keyword in message_lower for keyword in sports_keywords)

        # Detect intent type (order matters - check most specific first)

        # Check for explicit fixture requests FIRST (highest priority)
        fixtures_keywords = ["fixture", "fixtures", "upcoming", "scheduled", "matches today", "games today"]
        has_fixtures_request = any(keyword in message_lower for keyword in fixtures_keywords)

        # Check for match results queries (scores, results of finished/live matches)
        results_keywords = ["score", "scores", "result", "results", "outcome", "outcomes", "final score"]
        # Note: "today" is NOT a results indicator - it's ambiguous and defaults to fixtures
        past_time_indicators = ["yesterday", "last", "previous", "finished", "ended", "final", "played"]
        has_results_request = any(keyword in message_lower for keyword in results_keywords)
        has_past_time = any(indicator in message_lower for indicator in past_time_indicators)

        # FIXTURES FIRST: If user asks for fixtures, it's show_fixtures regardless of other keywords
        if has_fixtures_request:
            intent_type = "show_fixtures"
            confidence = 0.85 if has_sports_context else 0.6
        # Patterns that indicate get_match_results intent:
        # - "What was the result/score in/of X"
        # - "Show me X results/scores"
        # - "X results yesterday/last week"
        # - "How did X do"
        # - "Did X win"
        elif has_results_request or has_past_time or "how did" in message_lower or "did.*win" in message_lower:
            # Distinguish between:
            # 1. get_match_results: "Show me Arsenal results" (actual match scores)
            # 2. track_results: "How did your predictions do" (tracking our past predictions)
            if any(term in message_lower for term in ["your", "suggested", "selections", "picks", "prediction"]) and not has_results_request:
                # User asking about OUR predictions (track_results)
                intent_type = "track_results"
                confidence = 0.8
            elif has_results_request or has_past_time or "how did" in message_lower:
                # User asking about actual match results (get_match_results)
                intent_type = "get_match_results"
                confidence = 0.8 if has_sports_context else 0.6
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

            # Check for "[League] today" pattern - defaults to show_fixtures
            # This catches "Spanish LaLiga today", "Premier League today", etc.
            has_today = "today" in message_lower
            has_league_context = has_sports_context  # League names are in sports_keywords

            # Fixture queries with no quality/number indicators
            is_fixture_query = any(
                term in message_lower for term in ["available matches", "fixtures available", "what are the"]
            ) and not has_quality

            # "[League] today" without results keywords = show_fixtures (upcoming matches)
            if has_today and has_league_context and not has_results_request:
                intent_type = "show_fixtures"
                confidence = 0.80
            elif is_fixture_query and not has_number:
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

        # CRITICAL: Use ID-first resolution with API-Football IDs
        # This eliminates string matching ambiguity (e.g., "Premier League" exists in multiple countries)
        from sipap_common.data.league_reference import resolve_league_query

        resolved = resolve_league_query(message)
        leagues: list[LeagueEntity] | None = None

        if resolved:
            # Convert to LeagueEntity objects with API-Football IDs
            leagues = [
                LeagueEntity(
                    id=league["id"],
                    name=league["name"],
                    country=league.get("country")
                )
                for league in resolved
            ]
            entities["leagues"] = leagues  # list[LeagueEntity]
            entities["league_ids"] = [l.id for l in leagues]  # Quick ID access
            self.logger.debug(
                f"Resolved leagues to IDs: {[(l.id, l.name, l.country) for l in leagues]}",
                extra={"query": message[:50], "league_ids": [l.id for l in leagues]}
            )

        # HYBRID MARKET EXTRACTION:
        # Users CAN specify markets explicitly (e.g., "BTTS picks", "1X2 selections")
        # or via natural language (e.g., "both teams to score", "over 2.5 goals").
        # If no markets detected, system intelligently selects the best market per fixture.
        #
        # Examples:
        #   User: "I need 20 odds with highest positive outcome"
        #   NLU: target_odds=20, quality="highest", markets=None (system decides)
        #
        #   User: "Give me 10 BTTS picks"
        #   NLU: num_matches=10, markets=["BTTS"] (user specified)
        #
        #   User: "20 sure BTTS odds in Premier League"
        #   NLU: target_odds=20, quality="highest", markets=["BTTS"], leagues=[39]
        markets = self._extract_market_codes(message)
        if markets:
            entities["markets"] = markets
            self.logger.debug(
                f"Extracted market codes from user message: {markets}",
                extra={"query": message[:50], "markets": markets}
            )

        # Extract date range
        date_range = None
        today = datetime.now(UTC).date()

        if "yesterday" in message_lower:
            yesterday = today - timedelta(days=1)
            date_range = {
                "start": yesterday.isoformat(),
                "end": yesterday.isoformat(),
            }
            entities["date"] = "yesterday"
        elif "today" in message_lower:
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
        elif "this week" in message_lower:
            # This week = today until next Sunday
            days_until_sunday = 6 - today.weekday()  # Sunday is 6
            if days_until_sunday < 0:
                days_until_sunday = 0  # Already Sunday
            end_of_week = today + timedelta(days=days_until_sunday)
            date_range = {
                "start": today.isoformat(),
                "end": end_of_week.isoformat(),
            }
            entities["date"] = "this week"

        # Extract relative durations (e.g., "next 2 weeks", "next 7 days", "2 weeks")
        if not date_range:
            # Forward-looking patterns (next X weeks/days)
            # Pattern: "next X weeks" or "X weeks"
            weeks_match = re.search(r"(?:next\s+)?(\d+)\s+weeks?", message_lower)
            if weeks_match:
                num_weeks = int(weeks_match.group(1))
                end_date = today + timedelta(weeks=num_weeks)
                date_range = {
                    "start": today.isoformat(),
                    "end": end_date.isoformat(),
                }
                entities["date"] = f"next {num_weeks} week{'s' if num_weeks > 1 else ''}"

            # Pattern: "next X days" or "X days"
            if not date_range:
                days_match = re.search(r"(?:next\s+)?(\d+)\s+days?", message_lower)
                if days_match:
                    num_days = int(days_match.group(1))
                    end_date = today + timedelta(days=num_days)
                    date_range = {
                        "start": today.isoformat(),
                        "end": end_date.isoformat(),
                    }
                    entities["date"] = f"next {num_days} day{'s' if num_days > 1 else ''}"

            # Backward-looking patterns (last X weeks/days) for historical match results
            if not date_range:
                # Pattern: "last week" or "past week"
                if "last week" in message_lower or "past week" in message_lower:
                    start_of_last_week = today - timedelta(days=7)
                    date_range = {
                        "start": start_of_last_week.isoformat(),
                        "end": today.isoformat(),
                    }
                    entities["date"] = "last week"

                # Pattern: "last X days" or "past X days"
                elif not date_range:
                    last_days_match = re.search(r"(?:last|past)\s+(\d+)\s+days?", message_lower)
                    if last_days_match:
                        num_days = int(last_days_match.group(1))
                        start_date = today - timedelta(days=num_days)
                        date_range = {
                            "start": start_date.isoformat(),
                            "end": today.isoformat(),
                        }
                        entities["date"] = f"last {num_days} day{'s' if num_days > 1 else ''}"

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
            markets=markets,  # Extracted from user messages (hybrid approach) or None (system decides)
            quality_threshold=quality_threshold,  # type: ignore[arg-type]
            home_team=home_team,
            away_team=away_team,
            original_query=message,
            extracted_entities=entities,
        )

    def _extract_market_codes(self, message: str) -> list[str] | None:
        """Extract market codes from user message using market registry aliases.

        Hybrid approach for market extraction:
        - Explicit codes (BTTS, 1X2, OU2.5) are extracted
        - Natural language aliases ("both teams to score") are mapped to codes
        - Quality-only requests ("sure odds") return None (system decides)

        Args:
            message: User's original message

        Returns:
            List of market codes (e.g., ["BTTS", "OU2.5"]) or None if no markets detected

        Examples:
            >>> _extract_market_codes("Give me 10 BTTS picks")
            ["BTTS"]

            >>> _extract_market_codes("fixtures where both teams will score")
            ["BTTS"]

            >>> _extract_market_codes("BTTS and over 2.5 predictions")
            ["BTTS", "OU2.5"]

            >>> _extract_market_codes("20 sure odds")
            None  # No market specified, system will decide
        """
        from sipap.sports.soccer.markets import REGISTRY

        message_lower = message.lower()
        detected_markets: list[str] = []

        # Check explicit market codes and natural language aliases
        for market in REGISTRY.get_all():
            # Check for explicit market code (case-insensitive)
            # Use word boundary to avoid false positives (e.g., "dc" in "predictions")
            code_lower = market.code.lower()
            # Check for exact code match with word boundaries
            if re.search(rf'\b{re.escape(code_lower)}\b', message_lower):
                if market.code not in detected_markets:
                    detected_markets.append(market.code)
                    continue  # Skip alias check if code found

            # Check for natural language aliases
            for alias in market.aliases:
                alias_lower = alias.lower()
                if alias_lower in message_lower:
                    if market.code not in detected_markets:
                        detected_markets.append(market.code)
                    break  # Found an alias, no need to check more

        return detected_markets if detected_markets else None

    def _extract_leagues_with_context(self, query: str) -> list[dict[str, Any]]:
        """Extract structured league data with country context and competition type.

        This method properly parses league mentions in user queries and preserves:
        1. Canonical league name (from sipap-common mappings)
        2. Country context (from query phrasing)
        3. Competition type (national_league vs international_tournament)
        4. Original query text (for debugging and fallback)

        Args:
            query: User's original query

        Returns:
            List of structured league dictionaries with fields:
            - canonical_name: Official league name (e.g., "Premier League")
            - country: Country context if national league (e.g., "Wales"), None for international
            - competition_type: "national_league" or "international_tournament"
            - raw_text: Original phrasing from query (e.g., "Wales Premier League")

        Examples:
            >>> _extract_leagues_with_context("Wales Premier League results")
            [{
                "canonical_name": "Premier League",
                "country": "Wales",
                "competition_type": "national_league",
                "raw_text": "Wales Premier League"
            }]

            >>> _extract_leagues_with_context("Champions League matches")
            [{
                "canonical_name": "UEFA Champions League",
                "country": None,
                "competition_type": "international_tournament",
                "raw_text": "Champions League"
            }]

            >>> _extract_leagues_with_context("results in Armenia")
            [{
                "canonical_name": "Premier League",
                "country": "Armenia",
                "competition_type": "national_league",
                "raw_text": "in Armenia"
            }]
        """
        from sipap_common.data import find_league_matches

        # International/continental tournaments (never have country context)
        INTERNATIONAL_TOURNAMENTS = {
            "uefa champions league", "uefa europa league", "uefa europa conference league",
            "uefa nations league", "uefa super cup", "uefa youth league",
            "world cup", "euro championship", "copa america", "africa cup of nations",
            "asian cup", "concacaf gold cup", "conmebol libertadores", "conmebol sudamericana",
            "caf champions league", "afc champions league", "concacaf champions league",
            "fifa club world cup", "friendlies clubs"
        }

        # Country name mappings (100+ countries)
        COUNTRY_NAMES = {
            "albania", "armenia", "austria", "azerbaijan", "belgium", "bulgaria", "croatia",
            "cyprus", "czech", "denmark", "england", "estonia", "finland", "france", "georgia",
            "germany", "greece", "hungary", "iceland", "ireland", "israel", "italy", "latvia",
            "lithuania", "malta", "moldova", "montenegro", "netherlands", "norway", "poland",
            "portugal", "romania", "russia", "scotland", "serbia", "slovakia", "slovenia",
            "spain", "sweden", "switzerland", "turkey", "ukraine", "wales",
            "argentina", "bolivia", "brazil", "canada", "chile", "colombia", "costa rica",
            "ecuador", "mexico", "paraguay", "peru", "usa", "united states", "uruguay", "venezuela",
            "australia", "bahrain", "china", "india", "indonesia", "iran", "iraq", "japan",
            "jordan", "kuwait", "malaysia", "qatar", "saudi arabia", "singapore", "south korea",
            "korea", "thailand", "uae", "vietnam",
            "algeria", "egypt", "ghana", "kenya", "morocco", "nigeria", "south africa",
            "tunisia", "uganda", "zambia", "zimbabwe"
        }

        # Find canonical league names
        canonical_leagues = find_league_matches(query)

        if not canonical_leagues:
            return []

        # For each canonical league, extract country context and determine type
        leagues_data = []
        query_lower = query.lower()

        for canonical_name in canonical_leagues:
            # Determine if this is an international tournament
            is_international = canonical_name.lower() in INTERNATIONAL_TOURNAMENTS

            # Extract country context
            country = None
            raw_text = canonical_name

            if not is_international:
                # Try to extract country from query
                # Pattern 1: "[Country] [League]" (e.g., "Wales Premier League")
                # Pattern 2: "in [Country]" (e.g., "results in Armenia")
                # Pattern 3: "[Country] league" (e.g., "Austria league")

                for country_name in COUNTRY_NAMES:
                    if country_name in query_lower:
                        country = country_name.title()  # Capitalize
                        # Try to extract the raw text that includes country + league
                        if canonical_name.lower() in query_lower:
                            # Find the country and league mentions
                            raw_text = f"{country} {canonical_name}"
                        else:
                            raw_text = f"in {country}"
                        break

            leagues_data.append({
                "canonical_name": canonical_name,
                "country": country,
                "competition_type": "international_tournament" if is_international else "national_league",
                "raw_text": raw_text,
            })

        return leagues_data

    async def _invoke_claude_for_intent(
        self,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Invoke Claude to extract structured intent from user message.

        Uses AWS Bedrock prompt caching for cost optimization:
        - Static system prompt is cached (1,200+ tokens, 1hr TTL)
        - Dynamic user query is not cached
        - Expected 37% reduction in input token costs with 80% cache hit rate

        Args:
            message: User's natural language query
            context: Conversation context

        Returns:
            Dictionary with intent data from Claude

        Example Claude response:
            {
                "intent_type": "get_match_results",
                "confidence": 0.9,
                "leagues": ["UEFA Europa League"],
                "date_range": {"start": "2026-08-14", "end": "2026-08-14"},
                "reasoning": "User wants match results for Europa League today"
            }
        """
        import json

        from datetime import UTC, datetime

        # Import cached system prompt (1,200+ tokens for Bedrock caching)
        from sipap.conversation.prompts import NLU_SYSTEM_PROMPT

        # Get current date for "today" reference
        today_date = datetime.now(UTC).date().isoformat()

        # Build dynamic user prompt (not cached)
        user_prompt = f"""Parse this user query into structured intent:

**CURRENT DATE:** {today_date}

USER QUERY: "{message}"

IMPORTANT: When user says "today", use {today_date} for the date_range.

Return JSON format:
{{
    "intent_type": "get_match_results|show_fixtures|batch_prediction|single_prediction|track_results|check_odds|explain|unknown",
    "confidence": 0.0-1.0,
    "leagues": ["exact league phrase from user query"],
    "teams": {{"home": "team1", "away": "team2"}},
    "date_range": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}},
    "target_odds": null,
    "markets": ["BTTS", "1X2"],
    "reasoning": "brief explanation"
}}

CRITICAL: Extract leagues EXACTLY as user says them."""

        # Invoke Claude via Bedrock with prompt caching enabled
        # Structure: static prompt with cache_control, dynamic content without
        try:
            response = self._claude_agent.bedrock.invoke_model(
                modelId=self._claude_agent.model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 500,
                    "temperature": 0.3,  # Lower temperature for more consistent parsing
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    # Static system prompt - CACHED (1,200+ tokens)
                                    "type": "text",
                                    "text": NLU_SYSTEM_PROMPT,
                                    "cache_control": {
                                        "type": "ephemeral",
                                        "ttl": "1h"
                                    }
                                },
                                {
                                    # Dynamic user query - NOT cached
                                    "type": "text",
                                    "text": user_prompt
                                }
                            ]
                        }
                    ]
                })
            )

            # Parse response
            response_body = json.loads(response["body"].read())
            content = response_body["content"][0]["text"]

            # Log cache performance metrics if available
            usage = response_body.get("usage", {})
            cache_read = usage.get("cache_read_input_tokens", 0)
            cache_creation = usage.get("cache_creation_input_tokens", 0)
            if cache_read > 0 or cache_creation > 0:
                self.logger.debug(
                    "Claude NLU cache metrics",
                    extra={
                        "cache_read_tokens": cache_read,
                        "cache_creation_tokens": cache_creation,
                        "input_tokens": usage.get("input_tokens", 0),
                    }
                )

            # Extract JSON from Claude's response (may have markdown)
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                intent_data = json.loads(json_match.group(0))
                return intent_data
            else:
                raise ValueError("No JSON found in Claude response")

        except Exception as e:
            self.logger.error(f"Claude invocation failed: {e}")
            raise

    def _build_intent_from_claude_response(
        self,
        intent_data: dict[str, Any],
        original_query: str,
    ) -> RequestIntent:
        """
        Build RequestIntent from Claude's structured response.

        Args:
            intent_data: Parsed JSON from Claude
            original_query: Original user message

        Returns:
            RequestIntent object
        """
        from datetime import UTC, datetime

        # Extract intent type and confidence
        intent_type = intent_data.get("intent_type", "unknown")
        confidence = float(intent_data.get("confidence", 0.5))

        # CRITICAL: Use ID-first resolution with API-Football IDs
        # This eliminates string matching ambiguity (e.g., "Premier League" exists in multiple countries)
        from sipap_common.data.league_reference import resolve_league_query

        raw_leagues = intent_data.get("leagues", [])
        leagues: list[LeagueEntity] | None = None

        if raw_leagues:
            # Resolve each league phrase to LeagueEntity with API-Football ID
            all_resolved: list[LeagueEntity] = []
            for raw_league in raw_leagues:
                resolved = resolve_league_query(raw_league)
                for league_data in resolved:
                    all_resolved.append(LeagueEntity(
                        id=league_data["id"],
                        name=league_data["name"],
                        country=league_data.get("country")
                    ))
            leagues = all_resolved if all_resolved else None
            self.logger.info(
                f"Claude NLU resolved leagues to IDs: {[(l.id, l.name, l.country) for l in all_resolved] if all_resolved else 'None'}",
                extra={"raw_leagues": raw_leagues, "resolved_ids": [l.id for l in all_resolved] if all_resolved else []}
            )
        else:
            # Also try to resolve from original query as fallback
            resolved = resolve_league_query(original_query)
            if resolved:
                leagues = [
                    LeagueEntity(
                        id=league_data["id"],
                        name=league_data["name"],
                        country=league_data.get("country")
                    )
                    for league_data in resolved
                ]
                self.logger.info(
                    f"Claude NLU extracted leagues from query: {[(l.id, l.name, l.country) for l in leagues]}",
                    extra={"query": original_query[:50], "resolved_ids": [l.id for l in leagues]}
                )

        # Extract teams (handle null from Claude)
        teams = intent_data.get("teams") or {}
        home_team = teams.get("home") if teams else None
        away_team = teams.get("away") if teams else None

        # Extract date range
        date_range = intent_data.get("date_range")

        # Check if date_range is valid (not None and has valid start/end)
        if date_range:
            # Ensure start and end are not None
            if not date_range.get("start") or not date_range.get("end"):
                date_range = None

        # Default to today for intents that need dates
        if not date_range and intent_type in ["get_match_results", "show_fixtures"]:
            today = datetime.now(UTC).date().isoformat()
            date_range = {"start": today, "end": today}

        # Extract target odds
        target_odds = intent_data.get("target_odds")

        # Extract markets from Claude's response (intelligent extraction)
        # Claude understands natural language like "both teams to score" → BTTS
        markets = intent_data.get("markets")
        if markets:
            # Validate market codes against registry
            from sipap.sports.soccer.markets import REGISTRY
            valid_codes = {m.code for m in REGISTRY.get_all()}
            markets = [m for m in markets if m in valid_codes]
            if not markets:
                markets = None  # No valid markets extracted
            else:
                self.logger.info(
                    f"Claude NLU extracted markets: {markets}",
                    extra={"original_query": original_query[:50]}
                )

        # Build entities dict with API-Football IDs for traceability
        entities = {
            "leagues": leagues,  # list[LeagueEntity] | None
            "league_ids": [l.id for l in leagues] if leagues else [],  # For quick ID access
            "raw_leagues": raw_leagues,  # Original phrases from Claude
            "teams": teams,
            "date_range": date_range,
            "target_odds": target_odds,
            "markets": markets,  # Market codes from Claude
            "claude_reasoning": intent_data.get("reasoning", "")
        }

        return RequestIntent(
            intent_type=intent_type,  # type: ignore[arg-type]
            confidence=confidence,
            leagues=leagues if leagues else None,
            date_range=date_range,
            home_team=home_team,
            away_team=away_team,
            target_odds=target_odds,
            markets=markets,  # Include markets from Claude's intelligent extraction
            original_query=original_query,
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

        # CRITICAL: Use ID-first resolution with API-Football IDs
        # This eliminates string matching ambiguity (e.g., "Premier League" exists in multiple countries)
        from sipap_common.data.league_reference import resolve_league_query

        leagues: list[LeagueEntity] | None = None
        resolved_leagues = resolve_league_query(original_query)
        if resolved_leagues:
            # Convert to LeagueEntity objects with API-Football IDs
            leagues = [
                LeagueEntity(
                    id=league["id"],
                    name=league["name"],
                    country=league.get("country")
                )
                for league in resolved_leagues
            ]
            self.logger.info(
                f"Regex fallback resolved leagues to IDs: {[(l.id, l.name, l.country) for l in leagues]}",
                extra={"query": original_query[:50], "league_ids": [l.id for l in leagues]}
            )

        return RequestIntent(
            intent_type=intent_type,  # type: ignore[arg-type]
            confidence=confidence,
            home_team=entities.get("home_team"),
            away_team=entities.get("away_team"),
            leagues=leagues,  # FIXED: Now includes extracted leagues
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
                    # intent.leagues is list[LeagueEntity], extract names
                    league_context = f"{', '.join(league.name for league in intent.leagues)} "

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

    async def suggest_corrections(
        self,
        user_query: str,
        failed_entity: str,
        extracted_value: str | None = None,
        country: str | None = None,
    ) -> str:
        """
        Generate intelligent suggestions when no matches are found.

        Uses BOTH fuzzy matching (fast, deterministic) AND Claude AI (smart, context-aware)
        to suggest corrections when user's query doesn't match any data.

        Strategy:
        1. Try fuzzy matching first (instant, no API cost)
        2. If fuzzy matching returns good suggestions (score >= 75), use those
        3. Otherwise, use Claude for intelligent, context-aware suggestions

        Args:
            user_query: Full user query that failed
            failed_entity: Type of entity that failed ("league", "team", "competition")
            extracted_value: The extracted value that didn't match (optional)
            country: Detected country context (optional, helps narrow suggestions)

        Returns:
            Formatted suggestion message for WhatsApp

        Example:
            >>> message = await clarifier.suggest_corrections(
            ...     user_query="Spanish LaLiga fixtures",
            ...     failed_entity="league",
            ...     extracted_value="Spanish LaLiga",
            ...     country="Spain"
            ... )
            >>> print(message)
            "No matches found for 'Spanish LaLiga'. Did you mean:
             • La Liga (Spain)
             • Segunda División (Spain)

             Try: 'La Liga fixtures' or 'Spain fixtures'"
        """
        from sipap_common.data import find_similar_leagues

        # Step 1: Try fuzzy matching for leagues
        if failed_entity == "league" and extracted_value:
            suggestions = find_similar_leagues(
                query=extracted_value,
                country=country,
                max_suggestions=3,
            )

            # If we have high-confidence fuzzy matches (score >= 75), use them
            if suggestions and suggestions[0]["score"] >= 75:
                self.logger.info(
                    f"Using fuzzy matching for suggestions: {len(suggestions)} found",
                    extra={"query": extracted_value, "top_score": suggestions[0]["score"]}
                )

                # Format suggestions for WhatsApp
                suggestion_lines = []
                for s in suggestions[:3]:  # Top 3
                    country_label = f" ({s['country']})" if s['country'] != "International" else ""
                    suggestion_lines.append(f"• {s['league']}{country_label}")

                # Build message
                message_parts = [
                    f"No matches found for '{extracted_value}'. Did you mean:",
                    "",
                    *suggestion_lines,
                    "",
                    f"Try: '{suggestions[0]['league']} fixtures'"
                ]

                if country:
                    message_parts.append(f" or '{country} fixtures'")

                return "\n".join(message_parts)

        # Step 2: Fallback to Claude for intelligent, context-aware suggestions
        if self.use_claude and self._claude_client:
            try:
                self.logger.info(
                    "Using Claude for intelligent suggestions",
                    extra={"query": user_query, "failed_entity": failed_entity}
                )

                # Call Claude to generate context-aware suggestions
                claude_message = await self._claude_client.suggest_corrections(
                    user_query=user_query,
                    failed_entity=failed_entity,
                    extracted_value=extracted_value,
                    country_context=country,
                )

                return claude_message

            except Exception as e:
                self.logger.warning(
                    f"Claude suggestion failed: {e}. Using simple fallback.",
                    exc_info=True
                )
                # Continue to simple fallback below

        # Step 3: Simple fallback when both fuzzy matching and Claude fail
        entity_label = failed_entity.title()
        value_label = f" '{extracted_value}'" if extracted_value else ""

        message_parts = [
            f"No matches found for{value_label}.",
            "",
            "Try one of these:",
            "• Use a different league name (e.g., 'Premier League', 'La Liga')",
            "• Ask for a specific country (e.g., 'Spain fixtures')",
            "• Request all available matches (e.g., 'Show me all today's fixtures')",
        ]

        return "\n".join(message_parts)
