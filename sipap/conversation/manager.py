"""Conversation state management for SIPAP.

Manages multi-turn conversations with Redis-based state persistence.
Enables users to have natural conversations across multiple requests.

Pattern adapted from Sentinel's session management architecture.
"""

import logging
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

from sipap_common.cache.redis_adapter import RedisCache
from sipap_common.exceptions import CacheError


class ConversationManager:
    """
    Manages conversation state across multiple user interactions.

    Stores conversation history, extracted entities, and user context in Redis
    for multi-turn conversations. Supports graceful degradation if Redis fails.

    Conversation State Schema:
    {
        "user_id": "whatsapp:+1234567890",
        "session_id": "uuid-string",
        "messages": [
            {"role": "user", "content": "Show me Arsenal fixtures", "timestamp": "..."},
            {"role": "assistant", "content": "...", "timestamp": "..."}
        ],
        "context": {
            "last_team": "Arsenal",
            "last_league": "Premier League",
            "last_match_id": "uuid",
            "preferences": {}
        },
        "created_at": "2026-08-02T...",
        "updated_at": "2026-08-02T...",
    }

    Example:
        >>> manager = ConversationManager()
        >>> # Start new conversation
        >>> manager.add_user_message(user_id="whatsapp:+123", content="Show Arsenal fixtures")
        >>> # Get conversation history
        >>> state = manager.get_conversation(user_id="whatsapp:+123")
        >>> # Add assistant response
        >>> manager.add_assistant_message(user_id="whatsapp:+123", content="Here are the fixtures...")
        >>> # Update context
        >>> manager.update_context(user_id="whatsapp:+123", {"last_team": "Arsenal"})
    """

    def __init__(
        self,
        redis_host: str | None = None,
        redis_port: int | None = None,
        redis_password: str | None = None,
        conversation_ttl: int = 3600,  # 1 hour default
        logger: logging.Logger | None = None,
    ):
        """
        Initialize conversation manager.

        Args:
            redis_host: Redis server hostname (from env if None)
            redis_port: Redis server port (from env if None)
            redis_password: Redis password (from env if None)
            conversation_ttl: Conversation TTL in seconds (default 3600 = 1 hour)
            logger: Optional logger instance

        Environment Variables:
            REDIS_HOST: Redis hostname (default: localhost)
            REDIS_PORT: Redis port (default: 6379)
            REDIS_PASSWORD: Redis password (optional)
        """
        self.logger = logger or logging.getLogger(__name__)
        self.conversation_ttl = conversation_ttl

        # Get Redis configuration from env or parameters
        host = redis_host or os.environ.get("REDIS_HOST", "localhost")
        port = redis_port or int(os.environ.get("REDIS_PORT", "6379"))
        password = redis_password or os.environ.get("REDIS_PASSWORD")

        try:
            self.cache = RedisCache(
                host=host,
                port=port,
                password=password,
                default_ttl=conversation_ttl,
                db=1,  # Use DB 1 for conversations (DB 0 for general cache)
            )
            self.logger.info(f"ConversationManager initialized with Redis at {host}:{port}")
        except CacheError as e:
            self.logger.warning(f"Redis initialization failed: {e}. Running without conversation state.")
            self.cache = None

    def _get_conversation_key(self, user_id: str) -> str:
        """
        Generate Redis key for conversation state.

        Args:
            user_id: User identifier (e.g., "whatsapp:+1234567890")

        Returns:
            Redis key string
        """
        return f"conversation:{user_id}"

    def get_conversation(self, user_id: str) -> dict[str, Any] | None:
        """
        Get conversation state for a user.

        Args:
            user_id: User identifier

        Returns:
            Conversation state dictionary or None if not found

        Example:
            >>> state = manager.get_conversation("whatsapp:+123")
            >>> if state:
            ...     print(f"Found {len(state['messages'])} messages")
        """
        if not self.cache:
            return None

        try:
            key = self._get_conversation_key(user_id)
            state = self.cache.get(key)
            return state
        except CacheError as e:
            self.logger.error(f"Failed to get conversation for {user_id}: {e}")
            return None

    def create_conversation(self, user_id: str) -> dict[str, Any]:
        """
        Create a new conversation for a user.

        Args:
            user_id: User identifier

        Returns:
            New conversation state dictionary

        Example:
            >>> state = manager.create_conversation("whatsapp:+123")
            >>> print(state["session_id"])
        """
        now = datetime.utcnow().isoformat()
        state = {
            "user_id": user_id,
            "session_id": str(uuid4()),
            "messages": [],
            "context": {},
            "created_at": now,
            "updated_at": now,
        }

        if self.cache:
            try:
                key = self._get_conversation_key(user_id)
                self.cache.set(key, state, ttl=self.conversation_ttl)
                self.logger.info(f"Created new conversation for {user_id}")
            except CacheError as e:
                self.logger.error(f"Failed to save conversation for {user_id}: {e}")

        return state

    def add_user_message(self, user_id: str, content: str) -> None:
        """
        Add user message to conversation history.

        Args:
            user_id: User identifier
            content: Message content

        Example:
            >>> manager.add_user_message("whatsapp:+123", "Show me Arsenal fixtures")
        """
        # Get or create conversation
        state = self.get_conversation(user_id)
        if not state:
            state = self.create_conversation(user_id)

        # Add message
        message = {
            "role": "user",
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }
        state["messages"].append(message)
        state["updated_at"] = datetime.utcnow().isoformat()

        # Save updated state
        if self.cache:
            try:
                key = self._get_conversation_key(user_id)
                self.cache.set(key, state, ttl=self.conversation_ttl)
            except CacheError as e:
                self.logger.error(f"Failed to save user message for {user_id}: {e}")

    def add_assistant_message(self, user_id: str, content: str) -> None:
        """
        Add assistant response to conversation history.

        Args:
            user_id: User identifier
            content: Message content

        Example:
            >>> manager.add_assistant_message("whatsapp:+123", "Here are Arsenal's fixtures...")
        """
        state = self.get_conversation(user_id)
        if not state:
            self.logger.warning(f"No conversation found for {user_id}")
            return

        # Add message
        message = {
            "role": "assistant",
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }
        state["messages"].append(message)
        state["updated_at"] = datetime.utcnow().isoformat()

        # Save updated state
        if self.cache:
            try:
                key = self._get_conversation_key(user_id)
                self.cache.set(key, state, ttl=self.conversation_ttl)
            except CacheError as e:
                self.logger.error(f"Failed to save assistant message for {user_id}: {e}")

    def update_context(self, user_id: str, context_updates: dict[str, Any]) -> None:
        """
        Update conversation context with extracted entities.

        Args:
            user_id: User identifier
            context_updates: Dictionary of context updates

        Example:
            >>> manager.update_context("whatsapp:+123", {
            ...     "last_team": "Arsenal",
            ...     "last_league": "Premier League"
            ... })
        """
        state = self.get_conversation(user_id)
        if not state:
            state = self.create_conversation(user_id)

        # Update context
        state["context"].update(context_updates)
        state["updated_at"] = datetime.utcnow().isoformat()

        # Save updated state
        if self.cache:
            try:
                key = self._get_conversation_key(user_id)
                self.cache.set(key, state, ttl=self.conversation_ttl)
            except CacheError as e:
                self.logger.error(f"Failed to update context for {user_id}: {e}")

    def get_context(self, user_id: str) -> dict[str, Any]:
        """
        Get current conversation context.

        Args:
            user_id: User identifier

        Returns:
            Context dictionary (empty dict if not found)

        Example:
            >>> context = manager.get_context("whatsapp:+123")
            >>> last_team = context.get("last_team")
        """
        state = self.get_conversation(user_id)
        if state:
            return state.get("context", {})
        return {}

    def get_message_history(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get recent message history for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of messages to return (default 10)

        Returns:
            List of message dictionaries (most recent first)

        Example:
            >>> messages = manager.get_message_history("whatsapp:+123", limit=5)
            >>> for msg in messages:
            ...     print(f"{msg['role']}: {msg['content']}")
        """
        state = self.get_conversation(user_id)
        if not state:
            return []

        messages = state.get("messages", [])
        # Return most recent messages (reversed)
        return list(reversed(messages[-limit:]))

    def clear_conversation(self, user_id: str) -> None:
        """
        Clear conversation state for a user.

        Args:
            user_id: User identifier

        Example:
            >>> manager.clear_conversation("whatsapp:+123")
        """
        if not self.cache:
            return

        try:
            key = self._get_conversation_key(user_id)
            self.cache.delete(key)
            self.logger.info(f"Cleared conversation for {user_id}")
        except CacheError as e:
            self.logger.error(f"Failed to clear conversation for {user_id}: {e}")

    def extend_ttl(self, user_id: str) -> None:
        """
        Extend conversation TTL (reset expiration time).

        Args:
            user_id: User identifier

        Example:
            >>> manager.extend_ttl("whatsapp:+123")  # Reset to 1 hour TTL
        """
        state = self.get_conversation(user_id)
        if not state or not self.cache:
            return

        try:
            key = self._get_conversation_key(user_id)
            self.cache.set(key, state, ttl=self.conversation_ttl)
            self.logger.debug(f"Extended TTL for conversation {user_id}")
        except CacheError as e:
            self.logger.error(f"Failed to extend TTL for {user_id}: {e}")
