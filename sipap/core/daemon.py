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

logger = logging.getLogger(__name__)


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
    twilio_client: "TwilioWhatsAppClient" | None
) -> bool:
    """Send WhatsApp response via Twilio API.

    Supports dry-run mode via ENABLE_WHATSAPP_DELIVERY environment variable.
    When disabled, logs the message instead of sending it.

    Args:
        phone: User phone number (E.164 format)
        response: Response dict with response_text
        twilio_client: Initialized Twilio WhatsApp client (None if disabled)

    Returns:
        True if sent successfully (or logged in dry-run), False otherwise

    Example:
        >>> success = await send_whatsapp_response(
        ...     phone="+1234567890",
        ...     response={"response_text": "Hello!"},
        ...     twilio_client=client
        ... )
    """
    # Check if WhatsApp delivery is enabled
    enable_delivery = os.getenv("ENABLE_WHATSAPP_DELIVERY", "false").lower() == "true"

    if not enable_delivery or twilio_client is None:
        # Dry-run mode: Log message instead of sending
        logger.info(
            "📱 [DRY-RUN] WhatsApp message would be sent (delivery disabled)",
            extra={
                "phone": phone,
                "response_length": len(response["response_text"]),
                "preview": response["response_text"][:200] + "..." if len(response["response_text"]) > 200 else response["response_text"]
            }
        )
        logger.info(f"📱 [DRY-RUN] Full message to {phone}:\n{response['response_text']}")
        return True

    # Production mode: Send via Twilio
    try:
        message_sid = await twilio_client.send_message_with_retry(
            to_phone=phone,
            message_text=response["response_text"],
            max_retries=3
        )

        logger.info(
            "WhatsApp response sent successfully",
            extra={
                "phone": phone,
                "message_sid": message_sid,
                "response_length": len(response["response_text"])
            }
        )

        return True

    except Exception as e:
        logger.error(
            f"Failed to send WhatsApp response: {e}",
            exc_info=True,
            extra={"phone": phone}
        )
        return False


async def process_message(
    message: Message,
    orchestrator: MainOrchestrator,
    sqs_adapter: SQSAdapter,
    heartbeat: Heartbeat,
    twilio_client: TwilioWhatsAppClient | None,
) -> bool:
    """Process a single SQS message.

    Steps:
    1. Update heartbeat (processing)
    2. Parse WhatsApp message
    3. Generate prediction
    4. Send WhatsApp response (or log in dry-run mode)
    5. Delete message from queue (success)
    6. Update heartbeat (success)

    On error:
    - Permanent: Delete message, log error
    - Transient: Return to queue, will retry

    Args:
        message: SQS message
        orchestrator: Main orchestrator
        sqs_adapter: SQS adapter
        heartbeat: Heartbeat tracker
        twilio_client: Twilio WhatsApp client (None if delivery disabled)

    Returns:
        True if processed successfully, False otherwise
    """
    try:
        # Update heartbeat
        heartbeat.record_processing(message.message_id)

        logger.info(
            f"Processing message {message.message_id}",
            extra={"message_id": message.message_id}
        )

        # Parse WhatsApp message
        whatsapp_msg = parse_whatsapp_message(message.body)

        # Process message (generate prediction)
        response = await process_whatsapp_message(whatsapp_msg, orchestrator)

        # Send WhatsApp response
        success = await send_whatsapp_response(
            whatsapp_msg["phone"], response, twilio_client
        )

        if not success:
            raise ConnectionError("Failed to send WhatsApp response")

        # Delete message from queue (success)
        sqs_adapter.delete_message(message.receipt_handle)

        # Update heartbeat
        heartbeat.record_success()

        logger.info(
            f"Message {message.message_id} processed successfully",
            extra={"message_id": message.message_id}
        )

        return True

    except Exception as e:
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
    poll_interval: int = 1,
) -> None:
    """Main daemon polling loop.

    Continuously polls SQS queue and processes messages until shutdown.

    Args:
        sqs_adapter: SQS adapter
        orchestrator: Main orchestrator
        shutdown_event: Event to signal shutdown
        heartbeat: Heartbeat tracker
        twilio_client: Twilio WhatsApp client (None if delivery disabled)
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

    while not shutdown_event.is_set():
        try:
            # Update heartbeat
            heartbeat.record_poll()

            # Poll SQS (20-second long polling)
            messages = sqs_adapter.receive_messages(max_messages=1, wait_time=20)

            if not messages:
                # No messages, loop again
                continue

            # Process message
            message = messages[0]

            # Run async processing in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                success = loop.run_until_complete(
                    process_message(
                        message, orchestrator, sqs_adapter, heartbeat, twilio_client
                    )
                )
            finally:
                loop.close()

            if not success:
                # Processing failed (logged in process_message)
                pass

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
            time.sleep(5)  # Backoff on error

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
        )
    except Exception as e:
        logger.error(f"Daemon failed: {e}", exc_info=True)
        sys.exit(1)

    logger.info("Daemon stopped")
    sys.exit(0)
