"""Daemon Mode - Continuous SQS polling and message processing.

Pattern adapted from Sentinel's daemon architecture.

Provides:
- Continuous SQS polling loop with long polling (20s)
- Graceful shutdown handling (SIGTERM/SIGINT)
- Error classification and retry logic
- Heartbeat-based liveness probes
- Message processing coordination

Architecture:
1. Poll SQS queue with 20-second long polling
2. Parse WhatsApp message from SQS body
3. Process message (generate prediction)
4. Send WhatsApp response via Twilio
5. Delete message from queue (success) or return to queue (transient error)
6. Update heartbeat file for ECS health checks
7. Repeat until shutdown signal received

Example:
    >>> from sipap.core.daemon import start_daemon
    >>> start_daemon(
    ...     queue_url="https://sqs.us-east-1.amazonaws.com/.../queue.fifo",
    ...     region="us-east-1"
    ... )
"""

import asyncio
import logging
import os
import signal
import sys
import threading
import time
from typing import Any

from sipap.aws.sqs import Message, SQSAdapter
from sipap.core.errors import ErrorType, classify_error
from sipap.core.heartbeat import Heartbeat
from sipap.core.orchestrator import MainOrchestrator
from sipap.integrations.twilio import TwilioWhatsAppClient
from sipap_common.cache.redis_adapter import RedisCache

logger = logging.getLogger(__name__)


class HeartbeatKeeper:
    """Background thread to keep heartbeat alive during long processing.

    The ECS health check monitors heartbeat file age (default: 30 seconds max).
    During long processing (e.g., batch predictions taking 5+ minutes),
    the heartbeat must be updated periodically to prevent ECS from killing the task.

    This class runs a background thread that updates the heartbeat every `interval`
    seconds while processing is ongoing.

    Example:
        >>> heartbeat_keeper = HeartbeatKeeper(heartbeat, interval=10)
        >>> heartbeat_keeper.start(message_id="msg-123")
        >>> # ... long processing ...
        >>> heartbeat_keeper.stop()
    """

    def __init__(self, heartbeat: Heartbeat, interval: int = 10):
        """Initialize heartbeat keeper.

        Args:
            heartbeat: Heartbeat instance to update
            interval: Seconds between heartbeat updates (default: 10)
        """
        self.heartbeat = heartbeat
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_message_id: str | None = None

    def start(self, message_id: str) -> None:
        """Start keeping heartbeat alive for a message.

        Args:
            message_id: SQS message ID being processed
        """
        self._current_message_id = message_id
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.debug(f"HeartbeatKeeper started for message {message_id}")

    def stop(self) -> None:
        """Stop the heartbeat keeper."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        logger.debug("HeartbeatKeeper stopped")

    def _run(self) -> None:
        """Background thread that updates heartbeat periodically."""
        while not self._stop_event.is_set():
            try:
                self.heartbeat.record_processing(self._current_message_id)
            except Exception as e:
                logger.warning(f"HeartbeatKeeper failed to update heartbeat: {e}")
            self._stop_event.wait(self.interval)


class MessageDeduplicator:
    """Prevent duplicate message processing using Redis.

    When a task is killed mid-processing (e.g., by ECS health check), the SQS
    message may not have been deleted. After the visibility timeout, another
    task picks it up and processes it again, causing duplicate responses.

    This class tracks processed MessageSids in Redis to prevent duplicates.

    Example:
        >>> deduplicator = MessageDeduplicator(redis_client, ttl_seconds=3600)
        >>> if deduplicator.is_processed("SM123"):
        ...     print("Already processed, skipping")
        ... else:
        ...     # process message
        ...     deduplicator.mark_processed("SM123")
    """

    def __init__(self, redis_client: RedisCache | None, ttl_seconds: int = 3600):
        """Initialize message deduplicator.

        Args:
            redis_client: Redis cache client (None to disable deduplication)
            ttl_seconds: Time-to-live for processed message keys (default: 1 hour)
        """
        self.redis = redis_client
        self.ttl = ttl_seconds
        self.key_prefix = "sipap:processed:"

    def is_processed(self, message_sid: str) -> bool:
        """Check if message was already processed.

        Args:
            message_sid: Twilio message SID (e.g., "SM...")

        Returns:
            True if message was already processed, False otherwise
        """
        if not self.redis or not message_sid:
            return False

        try:
            key = f"{self.key_prefix}{message_sid}"
            result = self.redis.get(key)
            return result is not None
        except Exception as e:
            logger.warning(f"Deduplication check failed: {e}")
            return False  # Allow processing on Redis failure

    def mark_processed(self, message_sid: str) -> None:
        """Mark message as processed with TTL.

        Args:
            message_sid: Twilio message SID to mark as processed
        """
        if not self.redis or not message_sid:
            return

        try:
            key = f"{self.key_prefix}{message_sid}"
            self.redis.set(key, "1", ttl=self.ttl)
            logger.debug(f"Marked message {message_sid} as processed (TTL: {self.ttl}s)")
        except Exception as e:
            logger.warning(f"Failed to mark message as processed: {e}")


class VisibilityTimeoutExtender:
    """Periodically extend SQS visibility timeout during long processing.

    When processing takes longer than the default visibility timeout (30s),
    the message becomes visible to other consumers and may be processed again.
    This class runs a background thread that extends the visibility timeout
    periodically, preventing duplicate processing at the SQS level.

    Works in conjunction with MessageDeduplicator for defense-in-depth:
    - VisibilityTimeoutExtender: Prevents message from becoming visible (SQS level)
    - MessageDeduplicator: Catches duplicates if visibility extension fails (Redis level)

    Example:
        >>> extender = VisibilityTimeoutExtender(sqs_adapter, interval=60, extension=120)
        >>> extender.start(receipt_handle)
        >>> # ... long processing ...
        >>> extender.stop()
    """

    def __init__(
        self,
        sqs_adapter: SQSAdapter,
        interval: int = 60,
        extension: int = 120,
    ):
        """Initialize visibility timeout extender.

        Args:
            sqs_adapter: SQS adapter instance
            interval: Seconds between extension calls (default: 60)
            extension: Visibility timeout to set in seconds (default: 120)
        """
        self.sqs_adapter = sqs_adapter
        self.interval = interval
        self.extension = extension
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._receipt_handle: str | None = None

    def start(self, receipt_handle: str) -> None:
        """Start extending visibility timeout for a message.

        Args:
            receipt_handle: SQS message receipt handle
        """
        self._receipt_handle = receipt_handle
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.debug(f"VisibilityTimeoutExtender started (interval={self.interval}s, extension={self.extension}s)")

    def stop(self) -> None:
        """Stop extending visibility timeout."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        logger.debug("VisibilityTimeoutExtender stopped")

    def _run(self) -> None:
        """Background thread that extends visibility timeout periodically."""
        while not self._stop_event.is_set():
            # Wait for interval before first extension (message just received)
            if self._stop_event.wait(self.interval):
                break  # Stop requested

            if self._receipt_handle:
                try:
                    success = self.sqs_adapter.extend_visibility_timeout(
                        self._receipt_handle, self.extension
                    )
                    if not success:
                        logger.warning("Failed to extend visibility timeout")
                except Exception as e:
                    logger.warning(f"VisibilityTimeoutExtender error: {e}")


class CircuitBreaker:
    """Circuit breaker to prevent cascading failures.

    After N consecutive failures, the circuit "opens" and processing is paused
    for a cooldown period. This prevents:
    - Runaway retry loops that waste resources
    - Overwhelming downstream services during outages
    - Sending multiple error messages to users

    States:
    - CLOSED: Normal operation, processing allowed
    - OPEN: Too many failures, processing blocked for cooldown period
    - HALF_OPEN: Testing if system recovered, allow one request through

    Example:
        >>> breaker = CircuitBreaker(failure_threshold=5, reset_timeout=300)
        >>> if breaker.can_process():
        ...     try:
        ...         process_message()
        ...         breaker.record_success()
        ...     except Exception:
        ...         breaker.record_failure()
        ... else:
        ...     logger.info("Circuit open, skipping processing")
    """

    # Circuit states
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: int = 300,
        half_open_max_calls: int = 1,
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Consecutive failures before opening circuit (default: 5)
            reset_timeout: Seconds to wait before trying again (default: 300 = 5 minutes)
            half_open_max_calls: Calls allowed in half-open state (default: 1)
        """
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Get current circuit state (may transition from OPEN to HALF_OPEN)."""
        with self._lock:
            if self._state == self.OPEN:
                # Check if reset timeout has passed
                if self._last_failure_time:
                    elapsed = time.time() - self._last_failure_time
                    if elapsed >= self.reset_timeout:
                        logger.info(
                            f"Circuit breaker transitioning OPEN → HALF_OPEN "
                            f"(reset timeout {self.reset_timeout}s elapsed)"
                        )
                        self._state = self.HALF_OPEN
                        self._half_open_calls = 0
            return self._state

    def can_process(self) -> bool:
        """Check if processing is allowed.

        Returns:
            True if processing allowed, False if circuit is open
        """
        state = self.state  # May trigger OPEN → HALF_OPEN transition

        if state == self.CLOSED:
            return True
        elif state == self.HALF_OPEN:
            with self._lock:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False
        else:  # OPEN
            return False

    def record_success(self) -> None:
        """Record successful processing."""
        with self._lock:
            if self._state == self.HALF_OPEN:
                # Success in half-open state, close circuit
                logger.info("Circuit breaker transitioning HALF_OPEN → CLOSED (success)")
                self._state = self.CLOSED
                self._failure_count = 0
                self._success_count = 1
            elif self._state == self.CLOSED:
                self._success_count += 1
                # Reset failure count on success
                if self._failure_count > 0:
                    logger.debug(f"Circuit breaker: failure count reset (was {self._failure_count})")
                    self._failure_count = 0

    def record_failure(self) -> None:
        """Record failed processing."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == self.HALF_OPEN:
                # Failure in half-open state, reopen circuit
                logger.warning("Circuit breaker transitioning HALF_OPEN → OPEN (failure)")
                self._state = self.OPEN
            elif self._state == self.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    logger.warning(
                        f"Circuit breaker transitioning CLOSED → OPEN "
                        f"({self._failure_count} consecutive failures)"
                    )
                    self._state = self.OPEN

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        with self._lock:
            return {
                "state": self._state,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self.failure_threshold,
                "reset_timeout": self.reset_timeout,
                "last_failure_time": self._last_failure_time,
            }


# Default request timeout for processing (30 minutes)
# Batch predictions with many fixtures and sequential tool execution
# can take significant time. 30 minutes provides safe headroom.
# Configurable via REQUEST_TIMEOUT environment variable.
DEFAULT_REQUEST_TIMEOUT = 1800


def setup_signal_handlers(shutdown_event: threading.Event) -> None:
    """Register signal handlers for graceful shutdown.

    Handles:
    - SIGTERM: ECS task stop
    - SIGINT: Ctrl+C (for local testing)

    Args:
        shutdown_event: Event to set on shutdown signal

    Example:
        >>> shutdown_event = threading.Event()
        >>> setup_signal_handlers(shutdown_event)
    """

    def handle_shutdown(signum: int, frame: Any) -> None:
        """Handle shutdown signal."""
        signal_name = signal.Signals(signum).name
        logger.info(
            f"Received {signal_name} (signal {signum}), initiating graceful shutdown..."
        )
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logger.info("Signal handlers registered (SIGTERM, SIGINT)")


def parse_whatsapp_message(body: dict[str, Any]) -> dict[str, Any]:
    """Parse WhatsApp message from SQS message body.

    Expected format (from API Gateway → SQS):
    {
        "From": "whatsapp:+1234567890",
        "Body": "Predict Man United vs Liverpool",
        "MessageSid": "SM...",
        "AccountSid": "AC...",
        ...
    }

    Args:
        body: SQS message body (from API Gateway)

    Returns:
        Parsed message dict with:
        - phone: User phone number (e.g., "+1234567890")
        - text: Message text
        - message_sid: Twilio message SID
        - timestamp: Message timestamp

    Raises:
        KeyError: If required fields missing
        ValueError: If data format invalid

    Example:
        >>> parsed = parse_whatsapp_message({
        ...     "From": "whatsapp:+1234567890",
        ...     "Body": "Hello"
        ... })
        >>> assert parsed["phone"] == "+1234567890"
    """
    # Validate required fields
    if "From" not in body:
        raise KeyError("Missing required field: From")
    if "Body" not in body:
        raise KeyError("Missing required field: Body")

    # Extract phone number (remove "whatsapp:" prefix)
    from_field = body["From"]
    if from_field.startswith("whatsapp:"):
        phone = from_field[len("whatsapp:"):]
    else:
        phone = from_field

    # Parse message
    parsed = {
        "phone": phone,
        "text": body["Body"].strip(),
        "message_sid": body.get("MessageSid", ""),
        "account_sid": body.get("AccountSid", ""),
    }

    logger.info(
        "Parsed WhatsApp message",
        extra={
            "phone": phone,
            "text_length": len(parsed["text"]),
            "message_sid": parsed["message_sid"]
        }
    )

    return parsed


async def process_whatsapp_message(
    whatsapp_msg: dict[str, Any],
    orchestrator: MainOrchestrator,
) -> dict[str, Any]:
    """Process WhatsApp message and generate prediction.

    Steps:
    1. Parse user intent from message text with NLU agent
    2. Route to appropriate handler (batch prediction, single prediction, etc.)
    3. Generate predictions with AI agents
    4. Format response for WhatsApp

    Args:
        whatsapp_msg: Parsed WhatsApp message
        orchestrator: Main orchestrator instance

    Returns:
        Response dict with:
        - response_text: Text to send back to user
        - prediction: Full prediction object (if applicable)

    Example:
        >>> response = await process_whatsapp_message(
        ...     whatsapp_msg={"phone": "+1234567890", "text": "I need 20 odds with highest positive outcome"},
        ...     orchestrator=orchestrator
        ... )
    """
    user_text = whatsapp_msg["text"]
    phone = whatsapp_msg["phone"]

    logger.info(
        f"Processing WhatsApp message from {phone}",
        extra={"phone": phone, "text": user_text}
    )

    # Call MainOrchestrator.handle_user_message for full NLU + prediction flow
    try:
        result = await orchestrator.handle_user_message(
            user_id=phone,
            message=user_text,
        )

        # Extract response text
        response_text = result.get("message", "")

        # Log intent for debugging
        logger.info(
            f"Prediction complete for {phone}",
            extra={
                "phone": phone,
                "intent": result.get("intent"),
                "has_data": result.get("data") is not None,
                "has_error": result.get("error") is not None,
            },
        )

        return {
            "response_text": response_text,
            "prediction": result.get("data"),
            "intent": result.get("intent"),
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error(
            f"Failed to process message from {phone}: {e}",
            exc_info=True,
            extra={"phone": phone},
        )

        # Return error response
        return {
            "response_text": (
                f"❌ Processing Error\n\n"
                f"I encountered an error processing your request: {str(e)}\n\n"
                f"Please try again or rephrase your message."
            ),
            "prediction": None,
            "intent": "error",
            "error": str(e),
        }


async def send_whatsapp_response(
    phone: str,
    response: dict[str, Any],
    twilio_client: TwilioWhatsAppClient | None
) -> bool:
    """Send WhatsApp response via Twilio API.

    Supports automatic pagination - if response contains [PAGE_BREAK] markers,
    splits into multiple messages and sends sequentially with 2-second delays.

    Supports dry-run mode via ENABLE_WHATSAPP_DELIVERY environment variable.
    When disabled, logs the message instead of sending it.

    Args:
        phone: User phone number (E.164 format)
        response: Response dict with response_text (may contain [PAGE_BREAK] markers)
        twilio_client: Initialized Twilio WhatsApp client (None if disabled)

    Returns:
        True if sent successfully (or logged in dry-run), False otherwise

    Example:
        >>> success = await send_whatsapp_response(
        ...     phone="+1234567890",
        ...     response={"response_text": "Page 1[PAGE_BREAK]Page 2"},
        ...     twilio_client=client
        ... )
    """
    # Check if WhatsApp delivery is enabled
    enable_delivery = os.getenv("ENABLE_WHATSAPP_DELIVERY", "false").lower() == "true"

    # Split response into pages if pagination marker present
    response_text = response["response_text"]
    pages = response_text.split("[PAGE_BREAK]") if "[PAGE_BREAK]" in response_text else [response_text]

    if not enable_delivery or twilio_client is None:
        # Dry-run mode: Log message instead of sending
        for i, page in enumerate(pages, 1):
            logger.info(
                f"📱 [DRY-RUN] WhatsApp message {i}/{len(pages)} would be sent (delivery disabled)",
                extra={
                    "phone": phone,
                    "page": i,
                    "total_pages": len(pages),
                    "response_length": len(page),
                    "preview": page[:200] + "..." if len(page) > 200 else page
                }
            )
            logger.info(f"📱 [DRY-RUN] Full message {i}/{len(pages)} to {phone}:\n{page}")
        return True

    # Production mode: Send via Twilio
    try:
        for i, page in enumerate(pages, 1):
            message_sid = await twilio_client.send_message_with_retry(
                to_phone=phone,
                message_text=page,
                max_retries=3
            )

            logger.info(
                f"WhatsApp response {i}/{len(pages)} sent successfully",
                extra={
                    "phone": phone,
                    "page": i,
                    "total_pages": len(pages),
                    "message_sid": message_sid,
                    "response_length": len(page)
                }
            )

            # Add delay between messages to avoid rate limiting (except for last message)
            if i < len(pages):
                await asyncio.sleep(2)  # 2-second delay between messages

        return True

    except Exception as e:
        logger.error(
            f"Failed to send WhatsApp response: {e}",
            exc_info=True,
            extra={"phone": phone}
        )
        # Re-raise exception to preserve error type for classification
        # (don't return False - let caller handle the exception)
        raise


async def process_message(
    message: Message,
    orchestrator: MainOrchestrator,
    sqs_adapter: SQSAdapter,
    heartbeat: Heartbeat,
    twilio_client: TwilioWhatsAppClient | None,
    deduplicator: MessageDeduplicator | None = None,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> bool:
    """Process a single SQS message with timeout and visibility management.

    Steps:
    1. Check for duplicate (skip if already processed)
    2. Start background heartbeat keeper
    3. Start visibility timeout extender
    4. Parse WhatsApp message
    5. Generate prediction (with timeout)
    6. Send WhatsApp response (or log in dry-run mode)
    7. Mark as processed (for deduplication)
    8. Delete message from queue (success)
    9. Stop background threads
    10. Update heartbeat (success)

    On error:
    - Timeout: Return to queue for retry, log error
    - Permanent: Delete message, log error
    - Transient: Return to queue, will retry

    Args:
        message: SQS message
        orchestrator: Main orchestrator
        sqs_adapter: SQS adapter
        heartbeat: Heartbeat tracker
        twilio_client: Twilio WhatsApp client (None if delivery disabled)
        deduplicator: Message deduplicator (None to disable)
        request_timeout: Maximum seconds for processing (default: 300 = 5 minutes)

    Returns:
        True if processed successfully, False otherwise
    """
    # Start background heartbeat keeper to survive long processing
    heartbeat_keeper = HeartbeatKeeper(heartbeat, interval=10)

    # Start visibility timeout extender to prevent SQS from making message visible
    # Extend by 120s every 60s (always ahead of SQS default 30s visibility)
    visibility_extender = VisibilityTimeoutExtender(sqs_adapter, interval=60, extension=120)

    try:
        # Update heartbeat
        heartbeat.record_processing(message.message_id)

        logger.info(
            f"Processing message {message.message_id}",
            extra={"message_id": message.message_id}
        )

        # Parse WhatsApp message
        whatsapp_msg = parse_whatsapp_message(message.body)
        message_sid = whatsapp_msg.get("message_sid", "")

        # Check for duplicate processing (skip if already processed)
        if deduplicator and message_sid and deduplicator.is_processed(message_sid):
            logger.info(
                f"Skipping duplicate message {message_sid}",
                extra={"message_id": message.message_id, "message_sid": message_sid}
            )
            sqs_adapter.delete_message(message.receipt_handle)
            heartbeat.record_success()
            return True

        # Start background threads BEFORE long processing
        heartbeat_keeper.start(message.message_id)
        visibility_extender.start(message.receipt_handle)

        # Process message with timeout (prevents hung requests)
        try:
            async with asyncio.timeout(request_timeout):
                # Process message (generate prediction) - this can take several minutes
                response = await process_whatsapp_message(whatsapp_msg, orchestrator)

                # Send WhatsApp response (raises exception on failure)
                await send_whatsapp_response(
                    whatsapp_msg["phone"], response, twilio_client
                )

        except asyncio.TimeoutError:
            # Request timed out - log and return to queue for retry
            logger.error(
                f"Request timed out after {request_timeout}s for message {message.message_id}",
                extra={"message_id": message.message_id, "timeout": request_timeout}
            )
            # Stop background threads
            heartbeat_keeper.stop()
            visibility_extender.stop()
            # Return to queue with delay (not immediate retry)
            sqs_adapter.extend_visibility_timeout(message.receipt_handle, 60)
            heartbeat.record_failure(f"Timeout after {request_timeout}s")
            return False

        # Mark as processed AFTER successful Twilio send (for deduplication)
        if deduplicator and message_sid:
            deduplicator.mark_processed(message_sid)

        # Delete message from queue (success)
        sqs_adapter.delete_message(message.receipt_handle)

        # Stop background threads
        heartbeat_keeper.stop()
        visibility_extender.stop()

        # Update heartbeat
        heartbeat.record_success()

        logger.info(
            f"Message {message.message_id} processed successfully",
            extra={"message_id": message.message_id}
        )

        return True

    except Exception as e:
        # Stop background threads on error
        heartbeat_keeper.stop()
        visibility_extender.stop()

        # Classify error
        error_type = classify_error(e)

        logger.error(
            f"Message processing failed: {type(e).__name__}: {e}",
            exc_info=True,
            extra={
                "message_id": message.message_id,
                "error_type": error_type.value
            }
        )

        if error_type == ErrorType.PERMANENT:
            # Permanent error: Delete message (don't retry)
            logger.warning(
                f"Permanent error, deleting message {message.message_id}"
            )
            sqs_adapter.delete_message(message.receipt_handle)
            heartbeat.record_failure(f"Permanent error: {type(e).__name__}")

        else:
            # Transient error: Return to queue (will retry)
            logger.info(
                f"Transient error, returning message {message.message_id} to queue"
            )
            sqs_adapter.return_to_queue(message.receipt_handle)
            heartbeat.record_failure(f"Transient error: {type(e).__name__}")

        return False


def daemon_loop(
    sqs_adapter: SQSAdapter,
    orchestrator: MainOrchestrator,
    shutdown_event: threading.Event,
    heartbeat: Heartbeat,
    twilio_client: TwilioWhatsAppClient | None,
    deduplicator: MessageDeduplicator | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
    poll_interval: int = 1,
) -> None:
    """Main daemon polling loop with circuit breaker protection.

    Continuously polls SQS queue and processes messages until shutdown.
    Uses circuit breaker to prevent cascading failures.

    Args:
        sqs_adapter: SQS adapter
        orchestrator: Main orchestrator
        shutdown_event: Event to signal shutdown
        heartbeat: Heartbeat tracker
        twilio_client: Twilio WhatsApp client (None if delivery disabled)
        deduplicator: Message deduplicator (None to disable)
        circuit_breaker: Circuit breaker for failure protection (None to disable)
        request_timeout: Maximum seconds for processing (default: 300)
        poll_interval: Seconds to wait between polls (default: 1)

    Example:
        >>> daemon_loop(
        ...     sqs_adapter=adapter,
        ...     orchestrator=orchestrator,
        ...     shutdown_event=shutdown_event,
        ...     heartbeat=heartbeat,
        ...     twilio_client=None  # Dry-run mode
        ... )
    """
    logger.info("Starting daemon polling loop")
    logger.info(f"Request timeout: {request_timeout}s")
    if circuit_breaker:
        logger.info(f"Circuit breaker enabled: threshold={circuit_breaker.failure_threshold}, reset={circuit_breaker.reset_timeout}s")
    else:
        logger.info("Circuit breaker: DISABLED")

    # Create event loop once and reuse for all messages
    # This prevents "Event loop is closed" errors with cached httpx clients in MCP factory
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        while not shutdown_event.is_set():
            try:
                # Update heartbeat
                heartbeat.record_poll()

                # Check circuit breaker before polling
                if circuit_breaker and not circuit_breaker.can_process():
                    stats = circuit_breaker.get_stats()
                    logger.warning(
                        f"Circuit breaker OPEN - pausing processing "
                        f"(failures={stats['failure_count']}, "
                        f"will retry after {circuit_breaker.reset_timeout}s)"
                    )
                    # Sleep during circuit open state but keep heartbeat alive
                    time.sleep(min(30, circuit_breaker.reset_timeout))
                    continue

                # Poll SQS (20-second long polling)
                messages = sqs_adapter.receive_messages(max_messages=1, wait_time=20)

                if not messages:
                    # No messages, loop again
                    continue

                # Process message
                message = messages[0]

                # Run async processing in shared event loop (reused across messages)
                success = loop.run_until_complete(
                    process_message(
                        message, orchestrator, sqs_adapter, heartbeat, twilio_client,
                        deduplicator, request_timeout
                    )
                )

                # Update circuit breaker based on result
                if circuit_breaker:
                    if success:
                        circuit_breaker.record_success()
                    else:
                        circuit_breaker.record_failure()

                # Brief pause between polls
                time.sleep(poll_interval)

            except KeyboardInterrupt:
                # Handle Ctrl+C gracefully
                logger.info("Received KeyboardInterrupt, shutting down...")
                shutdown_event.set()
                break

            except Exception as e:
                # Unexpected error in daemon loop itself
                logger.error(
                    f"Unexpected error in daemon loop: {type(e).__name__}: {e}",
                    exc_info=True
                )
                heartbeat.record_failure(f"Daemon loop error: {type(e).__name__}")

                # Record failure in circuit breaker
                if circuit_breaker:
                    circuit_breaker.record_failure()

                time.sleep(5)  # Backoff on error

    finally:
        # Close event loop on shutdown
        logger.info("Closing event loop...")
        loop.close()
        logger.info("Event loop closed")

        # Log final circuit breaker stats
        if circuit_breaker:
            stats = circuit_breaker.get_stats()
            logger.info(f"Circuit breaker final stats: {stats}")

    # Graceful shutdown
    heartbeat.record_shutdown()
    logger.info("Daemon loop stopped gracefully")


def start_daemon(
    queue_url: str,
    region: str = "us-east-1",
    heartbeat_path: str = "/tmp/sipap-heartbeat",
    twilio_secret_arn: str | None = None,
) -> None:
    """Start daemon mode with SQS polling.

    Main entry point for daemon mode. Initializes components and starts
    polling loop with graceful shutdown support.

    Args:
        queue_url: SQS queue URL
        region: AWS region (default: us-east-1)
        heartbeat_path: Path to heartbeat file (default: /tmp/sipap-heartbeat)
        twilio_secret_arn: AWS Secrets Manager ARN for Twilio credentials
                          (reads from TWILIO_SECRET_ARN env var if not provided)

    Example:
        >>> start_daemon(
        ...     queue_url="https://sqs.us-east-1.amazonaws.com/.../queue.fifo"
        ... )
    """
    # Check if WhatsApp delivery is enabled
    enable_whatsapp_delivery = os.getenv("ENABLE_WHATSAPP_DELIVERY", "false").lower() == "true"

    # Reduce Twilio SDK logging verbosity (default INFO is too verbose)
    # Twilio logs every HTTP request/response at INFO, generating 4-6 lines per API call
    logging.getLogger("twilio.http_client").setLevel(logging.WARNING)

    logger.info("=" * 70)
    logger.info("SIPAP Orchestrator - Daemon Mode")
    logger.info("=" * 70)
    logger.info(f"Queue URL: {queue_url}")
    logger.info(f"Region: {region}")
    logger.info(f"Heartbeat: {heartbeat_path}")
    logger.info(f"WhatsApp Delivery: {'ENABLED' if enable_whatsapp_delivery else 'DISABLED (Dry-Run Mode)'}")
    logger.info("=" * 70)

    # Initialize components
    sqs_adapter = SQSAdapter(queue_url=queue_url, region=region)
    orchestrator = MainOrchestrator(logger=logger)
    heartbeat = Heartbeat(path=heartbeat_path)
    shutdown_event = threading.Event()

    # Initialize Redis client for message deduplication
    deduplicator = None
    redis_endpoint = os.environ.get("REDIS_ENDPOINT")
    if redis_endpoint:
        try:
            redis_ssl = os.environ.get("REDIS_SSL", "false").lower() == "true"
            redis_client = RedisCache(
                host=redis_endpoint,
                port=int(os.environ.get("REDIS_PORT", "6379")),
                password=os.environ.get("REDIS_PASSWORD"),
                ssl=redis_ssl,
            )
            deduplicator = MessageDeduplicator(redis_client, ttl_seconds=3600)
            logger.info(f"Message deduplication ENABLED (Redis: {redis_endpoint})")
        except Exception as e:
            logger.warning(f"Failed to initialize Redis for deduplication: {e}")
            logger.warning("Message deduplication DISABLED - Continuing without deduplication")
    else:
        logger.warning("REDIS_ENDPOINT not set - Message deduplication DISABLED")

    # Initialize Twilio WhatsApp client (optional - only if delivery enabled)
    twilio_client = None
    if enable_whatsapp_delivery:
        if twilio_secret_arn is None:
            twilio_secret_arn = os.environ.get("TWILIO_SECRET_ARN")
            if not twilio_secret_arn:
                logger.error("TWILIO_SECRET_ARN environment variable not set")
                sys.exit(1)

        logger.info(f"Loading Twilio credentials from: {twilio_secret_arn}")
        twilio_client = TwilioWhatsAppClient(secret_arn=twilio_secret_arn, region=region)
    else:
        logger.warning("⚠️  WhatsApp delivery DISABLED - Running in dry-run mode (messages will be logged only)")

    # Initialize circuit breaker for failure protection
    # Default: 5 consecutive failures → 5 minute cooldown
    circuit_breaker = CircuitBreaker(
        failure_threshold=int(os.environ.get("CIRCUIT_BREAKER_THRESHOLD", "5")),
        reset_timeout=int(os.environ.get("CIRCUIT_BREAKER_RESET_TIMEOUT", "300")),
    )
    logger.info(
        f"Circuit breaker ENABLED (threshold={circuit_breaker.failure_threshold}, "
        f"reset={circuit_breaker.reset_timeout}s)"
    )

    # Get request timeout from environment (default: 5 minutes)
    request_timeout = int(os.environ.get("REQUEST_TIMEOUT", str(DEFAULT_REQUEST_TIMEOUT)))
    logger.info(f"Request timeout: {request_timeout}s")

    # Register signal handlers
    setup_signal_handlers(shutdown_event)

    # Start daemon loop
    try:
        daemon_loop(
            sqs_adapter=sqs_adapter,
            orchestrator=orchestrator,
            shutdown_event=shutdown_event,
            heartbeat=heartbeat,
            twilio_client=twilio_client,
            deduplicator=deduplicator,
            circuit_breaker=circuit_breaker,
            request_timeout=request_timeout,
        )
    except Exception as e:
        logger.error(f"Daemon failed: {e}", exc_info=True)
        sys.exit(1)

    logger.info("Daemon stopped")
    sys.exit(0)
