"""Claude-powered conversational NLU for intelligent clarification.

Uses AWS Bedrock Claude Sonnet 4.5 to generate natural, context-aware
clarification responses instead of hardcoded templates.

Pattern adapted from Sentinel's Claude integration.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from sipap_common.logging import get_logger


class ClaudeNLUClient:
    """Claude AI client for conversational NLU clarification.

    Uses AWS Bedrock Claude Sonnet 4.5 to generate intelligent,
    context-aware clarification responses that:
    - Understand user intent even when unclear
    - Provide helpful guidance in natural language
    - Stay under 1600 characters (WhatsApp limit)
    - Maintain SIPAP's friendly, professional tone

    Example:
        >>> client = ClaudeNLUClient()
        >>> response = await client.generate_clarification(
        ...     query="I want matches",
        ...     intent_confidence=0.3,
        ...     detected_intent="unknown"
        ... )
        >>> print(response)
        "I see you're looking for matches! To help you better, could you tell me..."
    """

    def __init__(
        self,
        region: str = "us-east-1",
        model_id: str | None = None,
        logger: logging.Logger | None = None,
    ):
        """Initialize Claude NLU client.

        Args:
            region: AWS region for Bedrock
            model_id: Claude model/profile ID or ARN (default: from BEDROCK_PROFILE_ARN env var)
            logger: Optional logger instance
        """
        self.region = region
        self.logger = logger or get_logger(__name__)

        # Use inference profile ARN from environment if available, fallback to model_id parameter
        # Bedrock requires inference profile ARN, not model ID directly
        self.model_id = model_id or os.getenv(
            "BEDROCK_PROFILE_ARN",
            "anthropic.claude-sonnet-4-5-20250929-v1:0"
        )

        # Initialize Bedrock runtime client
        self.bedrock = boto3.client(
            service_name="bedrock-runtime",
            region_name=region
        )

        self.logger.info(
            f"Claude NLU client initialized (model/profile: {self.model_id}, region: {region})"
        )

    async def generate_clarification(
        self,
        query: str,
        intent_confidence: float,
        detected_intent: str = "unknown",
        extracted_entities: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """Generate intelligent clarification using Claude.

        Args:
            query: User's original query
            intent_confidence: Confidence score (0.0-1.0)
            detected_intent: Best-guess intent type
            extracted_entities: Any entities extracted (leagues, teams, dates, etc.)
            conversation_history: Previous messages in conversation

        Returns:
            Natural language clarification response (< 1600 chars)

        Example:
            >>> response = await client.generate_clarification(
            ...     query="show me some games",
            ...     intent_confidence=0.4,
            ...     detected_intent="show_fixtures",
            ...     extracted_entities={}
            ... )
        """
        extracted_entities = extracted_entities or {}
        conversation_history = conversation_history or []

        # Build prompt with context
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            query=query,
            intent_confidence=intent_confidence,
            detected_intent=detected_intent,
            extracted_entities=extracted_entities,
            conversation_history=conversation_history,
        )

        try:
            # Call Claude via Bedrock
            response = self._invoke_claude(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=600,  # ~1500 chars max (safety margin for 1600 limit)
            )

            self.logger.info(
                "Claude clarification generated",
                extra={
                    "query": query[:50],
                    "confidence": intent_confidence,
                    "response_length": len(response),
                }
            )

            return response

        except Exception as e:
            self.logger.error(f"Claude clarification failed: {e}", exc_info=True)
            # Return None to trigger fallback to hardcoded rules
            raise

    def _build_system_prompt(self) -> str:
        """Build system prompt defining SIPAP's role and constraints.

        This prompt configures Claude to:
        - Understand SIPAP's capabilities
        - Generate helpful, concise responses
        - Stay under character limit
        - Maintain friendly tone
        """
        return """You are SIPAP's conversational assistant - an AI-powered sports intelligence platform that helps users find smart betting opportunities through WhatsApp.

**SIPAP's Core Capabilities:**
1. **Predictions (Batch Mode)** - Find multiple matches with accumulated odds (e.g., "Give me 20 odds with highest success")
2. **Fixture Discovery** - Show available matches by league, date, or country (e.g., "Show me Premier League fixtures today")
3. **Results Tracking** - Check match results and scores (e.g., "Arsenal results today")
4. **Single Match Analysis** - Predict specific match outcomes (e.g., "Arsenal vs Chelsea prediction")

**Your Role:**
When a user's request is unclear, generate a friendly, helpful clarification response that:
1. Acknowledges what you understand from their query
2. Asks specific, actionable questions to clarify their intent
3. Provides 2-3 concrete examples of how to phrase their request
4. Maintains a warm, professional tone (not robotic)
5. **CRITICAL: Stays under 1500 characters total**

**Tone Guidelines:**
- Friendly and approachable (use "I" and "you")
- Professional but not formal
- Helpful without being pushy
- Use emojis sparingly (⚽ for matches, 🎯 for predictions, 📊 for results)
- Never apologize excessively - focus on moving forward

**Examples of Good Clarifications:**

User: "I want matches"
You: "I can help with matches! Are you looking for:
- Today's fixture schedule?
- Predictions for specific games?
- Results from recent matches?

Let me know which one, and I'll get you exactly what you need! ⚽"

User: "give me something good"
You: "I'd love to help! SIPAP specializes in finding high-value betting opportunities. Try:
- 'Give me 20 odds with highest success' - for smart predictions
- 'Show me Premier League fixtures today' - to see available matches
- 'Arsenal results' - to check recent scores

What sounds most useful to you?"

**Character Limit:**
Your response MUST be under 1500 characters. Be concise and actionable."""

    def _build_user_prompt(
        self,
        query: str,
        intent_confidence: float,
        detected_intent: str,
        extracted_entities: dict[str, Any],
        conversation_history: list[dict[str, str]],
    ) -> str:
        """Build user prompt with context for clarification.

        Args:
            query: User's original query
            intent_confidence: How confident we are about intent (0.0-1.0)
            detected_intent: Our best guess at what they want
            extracted_entities: What we extracted (leagues, teams, dates, etc.)
            conversation_history: Previous messages

        Returns:
            Formatted prompt for Claude
        """
        # Format conversation history if present
        history_text = ""
        if conversation_history:
            history_text = "\n**Recent Conversation:**\n"
            for msg in conversation_history[-3:]:  # Last 3 messages only
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_text += f"- {role.capitalize()}: {content[:100]}\n"

        # Format extracted entities
        entities_text = ""
        if extracted_entities:
            entities_text = "\n**Extracted Information:**\n"
            for key, value in extracted_entities.items():
                entities_text += f"- {key}: {value}\n"

        # Build full prompt
        prompt = f"""**User Query:** "{query}"

**Analysis:**
- Detected Intent: {detected_intent}
- Confidence: {intent_confidence:.0%}
{entities_text}{history_text}

**Task:**
The user's request is unclear. Generate a friendly, helpful clarification response that:
1. Acknowledges what you understand
2. Asks specific questions to clarify
3. Provides 2-3 concrete examples
4. Stays under 1500 characters

Generate the clarification response now:"""

        return prompt

    def _invoke_claude(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 600,
    ) -> str:
        """Invoke Claude via AWS Bedrock.

        Args:
            system_prompt: System message defining role and constraints
            user_prompt: User message with context
            max_tokens: Maximum tokens to generate (~4 chars per token)

        Returns:
            Claude's response text

        Raises:
            ClientError: If Bedrock API call fails
        """
        # Construct request body (Claude Messages API format)
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
            "temperature": 0.7,  # Slightly creative but controlled
        }

        try:
            # Invoke Bedrock
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
            )

            # Parse response
            response_body = json.loads(response["body"].read())

            # Extract text from content blocks
            text_content = ""
            for content_block in response_body.get("content", []):
                if content_block.get("type") == "text":
                    text_content += content_block.get("text", "")

            # Log token usage for monitoring
            usage = response_body.get("usage", {})
            self.logger.debug(
                "Claude invocation successful",
                extra={
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "response_length": len(text_content),
                }
            )

            return text_content.strip()

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            self.logger.error(
                f"Bedrock API error: {error_code} - {error_message}",
                exc_info=True
            )
            raise

    async def suggest_corrections(
        self,
        user_query: str,
        failed_entity: str,
        extracted_value: str | None = None,
        country_context: str | None = None,
    ) -> str:
        """Generate intelligent suggestions when no matches are found.

        Uses Claude to analyze failed queries and suggest corrections based on
        context, understanding user intent even when exact matches fail.

        Args:
            user_query: Full user query that failed to match
            failed_entity: Type of entity that failed ("league", "team", "competition")
            extracted_value: The extracted value that didn't match (optional)
            country_context: Detected country context (optional)

        Returns:
            Natural language suggestion message (< 1600 chars)

        Example:
            >>> suggestions = await client.suggest_corrections(
            ...     user_query="Spanish LaLiga fixtures",
            ...     failed_entity="league",
            ...     extracted_value="Spanish LaLiga",
            ...     country_context="Spain"
            ... )
            >>> print(suggestions)
            "No matches found for 'Spanish LaLiga'. Try:
             • 'La Liga fixtures'
             • 'Spain fixtures'

             La Liga is Spain's top football division."
        """
        # Build context for Claude
        context_parts = [
            f"User query: '{user_query}'",
            f"Failed to match {failed_entity}: '{extracted_value or 'unknown'}'",
        ]

        if country_context:
            context_parts.append(f"Detected country: {country_context}")

        context_str = "\n".join(context_parts)

        # System prompt for suggestion generation
        system_prompt = f"""You are SIPAP's intelligent suggestion assistant for sports data queries.

When users' queries don't match any data, you help them by suggesting correct formats.

SIPAP covers:
- 380 competitions globally (Premier League, La Liga, Serie A, Bundesliga, etc.)
- Fixtures, results, predictions for football/soccer
- European leagues, international tournaments, domestic cups

Common league names:
- England: Premier League, Championship, FA Cup, League Cup
- Spain: La Liga (NOT LaLiga), Segunda División, Copa del Rey
- Germany: Bundesliga, 2. Bundesliga, DFB Pokal
- Italy: Serie A, Serie B, Coppa Italia
- France: Ligue 1, Ligue 2, Coupe de France

Your task: Analyze why the query failed and suggest 2-3 correct alternatives.

Guidelines:
- Keep response under 300 characters (WhatsApp friendly)
- Provide exact query formats user should try
- Be friendly and helpful, not technical
- If country is known, suggest country-specific leagues
- Use bullet points for clarity
- Include one brief explanation (1 sentence)

Context:
{context_str}

Generate a helpful suggestion message."""

        # Prepare Messages API request
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": f"The query '{user_query}' didn't match any {failed_entity}. Suggest corrections.",
                }
            ],
            "max_tokens": 500,
            "temperature": 0.7,
        }

        try:
            # Invoke Bedrock
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
            )

            # Parse response
            response_body = json.loads(response["body"].read())

            # Extract text
            text_content = ""
            for content_block in response_body.get("content", []):
                if content_block.get("type") == "text":
                    text_content += content_block.get("text", "")

            # Log usage
            usage = response_body.get("usage", {})
            self.logger.debug(
                "Claude suggestion generated",
                extra={
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "response_length": len(text_content),
                }
            )

            return text_content.strip()

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            self.logger.error(
                f"Bedrock API error in suggest_corrections: {error_code} - {error_message}",
                exc_info=True
            )
            raise
