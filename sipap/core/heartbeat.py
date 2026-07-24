"""Heartbeat - File-based liveness probe for ECS health checks.

Pattern adapted from Sentinel's heartbeat mechanism.

Provides:
- File-based liveness probe (atomic writes)
- Polling status tracking
- Message processing tracking
- Health check endpoint for ECS

The heartbeat file is written atomically (write to .tmp then rename) to prevent
partial reads by health check probes.

ECS health check can monitor file age:
- If file age > visibility timeout → task is stuck, should be killed
- During long processing: file updated = still alive, no timeout

Example:
    >>> heartbeat = Heartbeat(path="/tmp/sipap-heartbeat")
    >>> heartbeat.record_poll()  # At start of poll loop
    >>> heartbeat.record_processing(message_id)  # When processing message
    >>> heartbeat.record_success()  # After successful processing
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HeartbeatStatus:
    """Heartbeat status data.

    Attributes:
        status: Current status (polling, processing, idle)
        timestamp: Unix timestamp of last update
        poll_count: Total number of poll iterations
        messages_processed: Total messages successfully processed
        messages_failed: Total messages that failed
        current_message_id: ID of message currently being processed (if any)
        last_error: Last error message (if any)
    """

    status: str
    timestamp: float
    poll_count: int
    messages_processed: int
    messages_failed: int
    current_message_id: str | None = None
    last_error: str | None = None


class Heartbeat:
    """File-based heartbeat for ECS liveness probes.

    Writes JSON status to a file atomically (write to temp, then rename).
    ECS health checks can monitor file age to detect stuck tasks.

    Args:
        path: Path to heartbeat file (default: /tmp/sipap-heartbeat)

    Example:
        >>> heartbeat = Heartbeat()
        >>> heartbeat.record_poll()
        >>> heartbeat.record_processing("msg-123")
        >>> heartbeat.record_success()
    """

    def __init__(self, path: str = "/tmp/sipap-heartbeat"):
        """Initialize heartbeat.

        Args:
            path: Path to heartbeat file
        """
        self.path = path
        self.poll_count = 0
        self.messages_processed = 0
        self.messages_failed = 0
        self.current_message_id: str | None = None
        self.last_error: str | None = None

        # Write initial heartbeat
        self._write(status="initialized")

        logger.info(f"Heartbeat initialized at {path}")

    def record_poll(self) -> None:
        """Record poll loop iteration.

        Called at the start of each poll loop iteration.

        Example:
            >>> heartbeat.record_poll()
        """
        self.poll_count += 1
        self.current_message_id = None
        self._write(status="polling")

        logger.debug(f"Poll {self.poll_count}: Heartbeat recorded")

    def record_processing(self, message_id: str) -> None:
        """Record that a message is being processed.

        Args:
            message_id: SQS message ID

        Example:
            >>> heartbeat.record_processing("msg-123-456")
        """
        self.current_message_id = message_id
        self._write(status="processing")

        logger.debug(f"Processing message {message_id}: Heartbeat recorded")

    def record_success(self) -> None:
        """Record successful message processing.

        Example:
            >>> heartbeat.record_success()
        """
        self.messages_processed += 1
        self.current_message_id = None
        self.last_error = None
        self._write(status="polling")

        logger.debug(
            f"Message processed successfully (total: {self.messages_processed})"
        )

    def record_failure(self, error: str) -> None:
        """Record failed message processing.

        Args:
            error: Error message

        Example:
            >>> heartbeat.record_failure("Connection timeout")
        """
        self.messages_failed += 1
        self.last_error = error
        self._write(status="error")

        logger.debug(
            f"Message processing failed (total: {self.messages_failed}): {error}"
        )

    def record_shutdown(self) -> None:
        """Record graceful shutdown.

        Example:
            >>> heartbeat.record_shutdown()
        """
        self._write(status="shutdown")
        logger.info("Heartbeat recorded shutdown")

    def _write(self, status: str, **kwargs: Any) -> None:
        """Write heartbeat file atomically.

        Uses temporary file + rename for atomic write (prevents partial reads).

        Args:
            status: Current status
            **kwargs: Additional fields to include
        """
        data = HeartbeatStatus(
            status=status,
            timestamp=time.time(),
            poll_count=self.poll_count,
            messages_processed=self.messages_processed,
            messages_failed=self.messages_failed,
            current_message_id=self.current_message_id,
            last_error=self.last_error,
        )

        # Atomic write: write to temp file, then rename
        tmp_path = self.path + ".tmp"

        try:
            with open(tmp_path, "w") as f:
                json.dump(asdict(data), f, indent=2)

            # Atomic rename (no partial reads possible)
            os.rename(tmp_path, self.path)

        except Exception as e:
            logger.error(f"Failed to write heartbeat: {e}", exc_info=True)

    @classmethod
    def read_heartbeat(cls, path: str = "/tmp/sipap-heartbeat") -> dict[str, Any] | None:
        """Read heartbeat file (utility for health checks).

        Args:
            path: Path to heartbeat file

        Returns:
            Heartbeat data dict, or None if file doesn't exist

        Example:
            >>> data = Heartbeat.read_heartbeat()
            >>> if time.time() - data['timestamp'] > 3600:
            ...     print("Task is stuck!")
        """
        try:
            with open(path, "r") as f:
                data: dict[str, Any] = json.load(f)
                return data
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to read heartbeat: {e}", exc_info=True)
            return None
