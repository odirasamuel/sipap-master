"""SQS Adapter - Amazon SQS Queue Operations.

Pattern adapted from Sentinel's SQS adapter with simplifications for SIPAP.

Provides:
- Long polling (20s wait time)
- Message receive/delete operations
- Visibility timeout management
- Batch operations for efficiency

Example:
    >>> adapter = SQSAdapter(queue_url="https://sqs.us-east-1.amazonaws.com/...")
    >>> messages = adapter.receive_messages(max_messages=1, wait_time=20)
    >>> for message in messages:
    ...     process(message)
    ...     adapter.delete_message(message.receipt_handle)
"""

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """SQS Message wrapper.

    Attributes:
        message_id: SQS message ID (UUID)
        body: Parsed message body (dict from JSON)
        receipt_handle: For deletion/visibility control
        sent_timestamp: Unix timestamp (milliseconds) when message sent to queue
        attributes: SQS system attributes
        message_attributes: Custom message attributes
    """

    message_id: str
    body: dict[str, Any]
    receipt_handle: str
    sent_timestamp: int
    attributes: dict[str, Any]
    message_attributes: dict[str, Any]


class SQSAdapter:
    """Amazon SQS Queue Adapter.

    Provides operations for FIFO queues with long polling support.

    Args:
        queue_url: Full SQS queue URL
        region: AWS region (default: us-east-1)

    Example:
        >>> adapter = SQSAdapter(
        ...     queue_url="https://sqs.us-east-1.amazonaws.com/.../queue.fifo"
        ... )
        >>> messages = adapter.receive_messages()
    """

    def __init__(self, queue_url: str, region: str = "us-east-1"):
        """Initialize SQS adapter.

        Args:
            queue_url: Full SQS queue URL
            region: AWS region
        """
        self.queue_url = queue_url
        self.region = region
        self.sqs_client = boto3.client("sqs", region_name=region)

        logger.info(
            "SQS adapter initialized",
            extra={"queue_url": queue_url, "region": region}
        )

    def _parse_twilio_form_data(self, body: str) -> dict[str, Any]:
        """Parse Twilio form-urlencoded webhook data preserving original field names.

        Twilio sends webhooks as form-urlencoded data with fields like:
        - From=whatsapp%3A%2B2347025761599
        - Body=What+are+the+matches+available...
        - MessageSid=SM...

        This preserves the Twilio field names so parse_whatsapp_message()
        can handle it without modifications.

        Args:
            body: Raw form-urlencoded string from Twilio webhook

        Returns:
            Dict with Twilio field names: From, Body, MessageSid, etc.

        Raises:
            ValueError: If required fields are missing
        """
        # Parse form data (returns dict with lists as values)
        parsed = parse_qs(body)

        # Convert from {key: [value]} to {key: value} format
        # Keep all Twilio fields for compatibility with parse_whatsapp_message()
        result = {}
        for key, values in parsed.items():
            # Use first value from list
            result[key] = values[0] if values else ""

        # Validate required fields
        if not result.get("From"):
            raise ValueError("Missing 'From' field in Twilio webhook")
        if not result.get("Body"):
            raise ValueError("Missing 'Body' field in Twilio webhook")

        return result

    def receive_messages(
        self,
        max_messages: int = 1,
        wait_time: int = 20,
    ) -> list[Message]:
        """Receive messages from queue with long polling.

        Uses 20-second long polling to reduce API calls and costs.
        FIFO queues return at most 1 message per message group ID.

        Args:
            max_messages: Maximum messages to receive (1-10)
            wait_time: Long polling wait time in seconds (default: 20)

        Returns:
            List of Message objects

        Example:
            >>> messages = adapter.receive_messages(max_messages=1, wait_time=20)
            >>> for msg in messages:
            ...     print(f"Received: {msg.message_id}")
        """
        try:
            response = self.sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )

            if "Messages" not in response:
                logger.debug("No messages received from queue")
                return []

            messages = []
            for msg in response["Messages"]:
                # Parse body - try JSON first, then Twilio form data
                try:
                    body = json.loads(msg["Body"])
                except json.JSONDecodeError:
                    # Not JSON - try parsing as Twilio form-urlencoded data
                    try:
                        body = self._parse_twilio_form_data(msg["Body"])
                        logger.debug(
                            "Parsed Twilio form data",
                            extra={"message_id": msg["MessageId"], "phone": body.get("phone")}
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to parse message body as JSON or Twilio form data: {e}",
                            extra={"message_id": msg["MessageId"], "body": msg["Body"][:200]}
                        )
                        # Delete malformed message (permanent error)
                        self.delete_message(msg["ReceiptHandle"])
                        continue

                # Extract sent timestamp
                sent_timestamp = int(msg.get("Attributes", {}).get("SentTimestamp", 0))

                message = Message(
                    message_id=msg["MessageId"],
                    body=body,
                    receipt_handle=msg["ReceiptHandle"],
                    sent_timestamp=sent_timestamp,
                    attributes=msg.get("Attributes", {}),
                    message_attributes=msg.get("MessageAttributes", {}),
                )

                messages.append(message)

            logger.info(
                f"Received {len(messages)} message(s) from queue",
                extra={"count": len(messages)}
            )

            return messages

        except ClientError as e:
            logger.error(f"Failed to receive messages: {e}", exc_info=True)
            return []

    def delete_message(self, receipt_handle: str) -> bool:
        """Delete message from queue (after successful processing).

        Args:
            receipt_handle: Message receipt handle from receive_message

        Returns:
            True if deleted successfully, False otherwise

        Example:
            >>> success = adapter.delete_message(message.receipt_handle)
        """
        try:
            self.sqs_client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
            )
            logger.debug("Message deleted from queue")
            return True

        except ClientError as e:
            logger.error(f"Failed to delete message: {e}", exc_info=True)
            return False

    def return_to_queue(self, receipt_handle: str) -> bool:
        """Return message to queue for immediate redelivery.

        Sets visibility timeout to 0, making message immediately available
        for other consumers. Used for transient errors that should be retried
        immediately.

        Args:
            receipt_handle: Message receipt handle

        Returns:
            True if visibility changed successfully, False otherwise

        Example:
            >>> adapter.return_to_queue(message.receipt_handle)
        """
        try:
            self.sqs_client.change_message_visibility(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=0,
            )
            logger.debug("Message returned to queue (visibility timeout = 0)")
            return True

        except ClientError as e:
            logger.error(f"Failed to return message to queue: {e}", exc_info=True)
            return False

    def get_approximate_message_count(self) -> int:
        """Get approximate number of messages in queue.

        Returns:
            Approximate message count (may be slightly stale)

        Example:
            >>> count = adapter.get_approximate_message_count()
            >>> print(f"Queue has ~{count} messages")
        """
        try:
            response = self.sqs_client.get_queue_attributes(
                QueueUrl=self.queue_url,
                AttributeNames=["ApproximateNumberOfMessages"]
            )

            count = int(response["Attributes"].get("ApproximateNumberOfMessages", 0))
            return count

        except ClientError as e:
            logger.error(f"Failed to get queue attributes: {e}", exc_info=True)
            return 0
