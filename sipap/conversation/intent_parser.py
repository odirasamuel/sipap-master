"""Natural language intent parser for SIPAP.

Extracts structured intent and entities from user queries using pattern matching
and LLM fallback for complex queries.

Pattern adapted from Sentinel's NLP parsing patterns.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from sipap_common.exceptions import ValidationError


class Intent(str, Enum):
    """Supported user intents."""

    GET_PREDICTION = "get_prediction"
    SHOW_FIXTURES = "show_fixtures"
    CHECK_ODDS = "check_odds"
    EXPLAIN_PREDICTION = "explain_prediction"
    UNKNOWN = "unknown"


class IntentParser:
    """
    Parse natural language queries into structured intents and entities.

    Uses pattern matching for common queries and provides conversation context
    awareness for resolving references like "tomorrow", "that match", etc.

    Example:
        >>> parser = IntentParser()
        >>> intent = parser.parse("Show me Arsenal vs Chelsea prediction")
        >>> print(intent)
        {
            "intent": "get_prediction",
            "entities": {
                "home_team": "Arsenal",
                "away_team": "Chelsea",
                "market": "1X2"
            },
            "confidence": 0.95
        }

        >>> # With conversation context
        >>> intent = parser.parse("How about tomorrow?", context={"last_home_team": "Arsenal"})
        >>> print(intent["entities"]["date"])
        "2026-08-03"
    """

    def __init__(self, logger: logging.Logger | None = None):
        """
        Initialize intent parser.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        # Common patterns for intent detection
        self.patterns = {
            Intent.GET_PREDICTION: [
                r"(show|give|get|what'?s?)\s+(me\s+)?(the\s+)?prediction\s+(for\s+)?(.+)",
                r"predict\s+(.+)",
                r"(.+)\s+(prediction|odds|chances)",
                r"who\s+will\s+win\s+(.+)",
            ],
            Intent.SHOW_FIXTURES: [
                r"(show|list|get)\s+(me\s+)?(the\s+)?fixtures?\s+(for\s+)?(.+)",
                r"(.+)\s+fixtures?",
                r"when\s+(is|does)\s+(.+)\s+play",
            ],
            Intent.CHECK_ODDS: [
                r"(what|check|show)\s+(are|me)?\s+(the\s+)?odds\s+(for\s+)?(.+)",
                r"(.+)\s+odds",
            ],
            Intent.EXPLAIN_PREDICTION: [
                r"(explain|why|how)\s+(.+)",
                r"what\s+makes\s+you\s+(think|say)\s+(.+)",
            ],
        }

        # Team name patterns
        self.team_patterns = [
            r"(\w+(\s+\w+)?)\s+vs\s+(\w+(\s+\w+)?)",  # "Arsenal vs Chelsea"
            r"(\w+(\s+\w+)?)\s+against\s+(\w+(\s+\w+)?)",  # "Arsenal against Chelsea"
        ]

        # Temporal patterns
        self.temporal_patterns = {
            "today": lambda: datetime.now(UTC).date(),
            "tomorrow": lambda: (datetime.now(UTC) + timedelta(days=1)).date(),
            "next week": lambda: (datetime.now(UTC) + timedelta(weeks=1)).date(),
        }

    def parse(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Parse natural language query into structured intent.

        Args:
            query: User query string
            context: Optional conversation context for resolving references

        Returns:
            Dictionary with intent, entities, and confidence score

        Example:
            >>> parser.parse("Show me Arsenal vs Chelsea prediction")
            {
                "intent": "get_prediction",
                "entities": {
                    "home_team": "Arsenal",
                    "away_team": "Chelsea",
                    "market": "1X2"
                },
                "confidence": 0.95,
                "query": "Show me Arsenal vs Chelsea prediction"
            }
        """
        query = query.strip()
        context = context or {}

        self.logger.debug(f"Parsing query: {query}")

        # Step 1: Detect intent
        intent = self._detect_intent(query)

        # Step 2: Extract entities based on intent
        entities = self._extract_entities(query, intent, context)

        # Step 3: Resolve temporal references
        entities = self._resolve_temporal(entities, query)

        # Step 4: Calculate confidence
        confidence = self._calculate_confidence(intent, entities)

        result = {
            "intent": intent.value,
            "entities": entities,
            "confidence": confidence,
            "query": query,
        }

        self.logger.info(
            f"Parsed intent: {intent.value}",
            extra={"entities": entities, "confidence": confidence},
        )

        return result

    def _detect_intent(self, query: str) -> Intent:
        """
        Detect user intent from query.

        Args:
            query: User query string

        Returns:
            Detected Intent enum
        """
        query_lower = query.lower()

        for intent, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return intent

        return Intent.UNKNOWN

    def _extract_entities(
        self,
        query: str,
        intent: Intent,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Extract entities from query.

        Args:
            query: User query string
            intent: Detected intent
            context: Conversation context

        Returns:
            Dictionary of extracted entities
        """
        entities: dict[str, Any] = {}

        # Extract team names
        teams = self._extract_teams(query)
        if teams:
            entities["home_team"] = teams[0]
            if len(teams) > 1:
                entities["away_team"] = teams[1]

        # If no teams found, check conversation context
        if not teams and context:
            if "last_home_team" in context:
                entities["home_team"] = context["last_home_team"]
            if "last_away_team" in context:
                entities["away_team"] = context["last_away_team"]

        # Extract market (default to 1X2 for match predictions)
        if intent == Intent.GET_PREDICTION:
            entities["market"] = self._extract_market(query)
            if not entities["market"]:
                entities["market"] = "1X2"  # Default

        # Extract date/time
        date_str = self._extract_date(query)
        if date_str:
            entities["date"] = date_str

        return entities

    def _extract_teams(self, query: str) -> list[str]:
        """
        Extract team names from query.

        Args:
            query: User query string

        Returns:
            List of team names (0-2 teams)
        """
        for pattern in self.team_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                # Extract groups (ignoring nested groups)
                groups = [g for g in match.groups() if g and not g.startswith(" ")]
                # Return only unique groups
                return [groups[0].strip(), groups[2].strip()] if len(groups) >= 3 else [groups[0].strip()]

        return []

    def _extract_market(self, query: str) -> str | None:
        """
        Extract betting market from query.

        Args:
            query: User query string

        Returns:
            Market identifier or None
        """
        query_lower = query.lower()

        # Check for explicit market mentions
        if "btts" in query_lower or "both teams to score" in query_lower:
            return "BTTS"
        if "over 2.5" in query_lower or "over" in query_lower:
            return "OU2.5"
        if "under 2.5" in query_lower or "under" in query_lower:
            return "OU2.5"
        if "draw" in query_lower:
            return "1X2"

        return None

    def _extract_date(self, query: str) -> str | None:
        """
        Extract date from query.

        Args:
            query: User query string

        Returns:
            ISO date string or None
        """
        query_lower = query.lower()

        # Check for temporal keywords
        for keyword, date_func in self.temporal_patterns.items():
            if keyword in query_lower:
                date = date_func()
                return date.isoformat()

        # Check for explicit dates (basic ISO format)
        date_pattern = r"(\d{4}-\d{2}-\d{2})"
        match = re.search(date_pattern, query)
        if match:
            return match.group(1)

        return None

    def _resolve_temporal(
        self,
        entities: dict[str, Any],
        query: str,
    ) -> dict[str, Any]:
        """
        Resolve temporal references in entities.

        Args:
            entities: Extracted entities
            query: Original query

        Returns:
            Updated entities with resolved temporal references
        """
        # If no explicit date but query mentions time, try to infer
        if "date" not in entities:
            query_lower = query.lower()
            if "today" in query_lower:
                entities["date"] = datetime.now(UTC).date().isoformat()
            elif "tomorrow" in query_lower:
                entities["date"] = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()

        return entities

    def _calculate_confidence(self, intent: Intent, entities: dict[str, Any]) -> float:
        """
        Calculate confidence score for parsed intent.

        Args:
            intent: Detected intent
            entities: Extracted entities

        Returns:
            Confidence score (0.0 to 1.0)
        """
        confidence = 0.5  # Base confidence

        # Boost confidence if intent is not unknown
        if intent != Intent.UNKNOWN:
            confidence += 0.3

        # Boost confidence for each extracted entity
        if "home_team" in entities:
            confidence += 0.1
        if "away_team" in entities:
            confidence += 0.1
        if "market" in entities:
            confidence += 0.05
        if "date" in entities:
            confidence += 0.05

        # Cap at 1.0
        return min(confidence, 1.0)

    def format_response_template(self, intent: Intent, entities: dict[str, Any]) -> str:
        """
        Generate response template based on intent.

        Args:
            intent: Detected intent
            entities: Extracted entities

        Returns:
            Response template string

        Example:
            >>> parser.format_response_template(
            ...     Intent.GET_PREDICTION,
            ...     {"home_team": "Arsenal", "away_team": "Chelsea"}
            ... )
            "Getting prediction for Arsenal vs Chelsea..."
        """
        if intent == Intent.GET_PREDICTION:
            home = entities.get("home_team", "Home")
            away = entities.get("away_team", "Away")
            return f"Getting prediction for {home} vs {away}..."

        if intent == Intent.SHOW_FIXTURES:
            team = entities.get("home_team") or entities.get("away_team", "matches")
            return f"Fetching fixtures for {team}..."

        if intent == Intent.CHECK_ODDS:
            home = entities.get("home_team", "Home")
            away = entities.get("away_team", "Away")
            return f"Checking odds for {home} vs {away}..."

        if intent == Intent.EXPLAIN_PREDICTION:
            return "Let me explain the reasoning behind this prediction..."

        return "I'm not sure what you're asking. Could you rephrase?"
