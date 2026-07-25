"""Twilio WhatsApp API Client.

This module provides a client for sending WhatsApp messages via Twilio.

Example:
    >>> import asyncio
    >>> from sipap.integrations.twilio import TwilioWhatsAppClient
    >>>
    >>> async def main():
    ...     client = TwilioWhatsAppClient(
    ...         secret_arn="arn:aws:secretsmanager:us-east-1:123:secret:twilio"
    ...     )
    ...     await client.send_message(
    ...         to_phone="+254712345678",
    ...         message_text="Hello from SIPAP!"
    ...     )
    >>> asyncio.run(main())
"""

import json
import logging
from typing import Any

import boto3
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger(__name__)


class TwilioWhatsAppClient:
    """Client for sending WhatsApp messages via Twilio API.

    This client handles:
    - Loading credentials from AWS Secrets Manager
    - Sending WhatsApp messages
    - Error handling and retries
    - Message delivery tracking

    Attributes:
        secret_arn: AWS Secrets Manager ARN for Twilio credentials
        account_sid: Twilio Account SID (loaded from secrets)
        auth_token: Twilio Auth Token (loaded from secrets)
        whatsapp_number: Twilio WhatsApp number (loaded from secrets)
        client: Twilio REST API client

    Example:
        >>> client = TwilioWhatsAppClient(
        ...     secret_arn="arn:aws:secretsmanager:us-east-1:810278669998:secret:twilio-xxx"
        ... )
        >>> message_sid = await client.send_message(
        ...     to_phone="+254712345678",
        ...     message_text="Your prediction is ready!"
        ... )
        >>> print(f"Message sent: {message_sid}")
    """

    def __init__(self, secret_arn: str, region: str = "us-east-1"):
        """Initialize Twilio WhatsApp client.

        Args:
            secret_arn: AWS Secrets Manager ARN containing Twilio credentials
            region: AWS region for Secrets Manager (default: us-east-1)

        The secret should contain JSON with these fields:
        - account_sid: Twilio Account SID
        - auth_token: Twilio Auth Token
        - whatsapp_number: Twilio WhatsApp number (format: "whatsapp:+14155238886")

        Example:
            >>> client = TwilioWhatsAppClient(
            ...     secret_arn="arn:aws:secretsmanager:us-east-1:123:secret:twilio-xxx"
            ... )
        """
        self.secret_arn = secret_arn
        self.region = region

        # Load credentials from Secrets Manager
        credentials = self._load_credentials()

        self.account_sid = credentials["account_sid"]
        self.auth_token = credentials["auth_token"]
        self.whatsapp_number = credentials["whatsapp_number"]

        # Initialize Twilio client
        self.client = TwilioClient(self.account_sid, self.auth_token)

        logger.info(
            "Twilio WhatsApp client initialized",
            extra={
                "whatsapp_number": self.whatsapp_number,
                "account_sid": self.account_sid[:10] + "..."  # Masked for security
            }
        )

    def _load_credentials(self) -> dict[str, str]:
        """Load Twilio credentials from AWS Secrets Manager.

        Returns:
            Dictionary with account_sid, auth_token, whatsapp_number

        Raises:
            ValueError: If secret is missing required fields
            Exception: If Secrets Manager call fails

        Example:
            >>> credentials = client._load_credentials()
            >>> print(credentials["account_sid"])
            ACxxxxxxxxxxxxxxxxxxxxxxxxxxxx
        """
        try:
            sm_client = boto3.client("secretsmanager", region_name=self.region)
            response = sm_client.get_secret_value(SecretId=self.secret_arn)

            secret_string = response["SecretString"]
            credentials = json.loads(secret_string)

            # Validate required fields
            required_fields = ["account_sid", "auth_token", "whatsapp_number"]
            missing_fields = [f for f in required_fields if f not in credentials]

            if missing_fields:
                raise ValueError(
                    f"Secret missing required fields: {', '.join(missing_fields)}"
                )

            logger.info("Loaded Twilio credentials from Secrets Manager")
            return credentials

        except Exception as e:
            logger.error(
                f"Failed to load Twilio credentials: {e}",
                exc_info=True,
                extra={"secret_arn": self.secret_arn}
            )
            raise

    async def send_message(
        self,
        to_phone: str,
        message_text: str
    ) -> str:
        """Send a WhatsApp message via Twilio.

        Args:
            to_phone: Recipient phone number (E.164 format, e.g., "+254712345678")
            message_text: Message content (max 1600 characters for WhatsApp)

        Returns:
            Message SID from Twilio (unique message identifier)

        Raises:
            TwilioRestException: If Twilio API call fails
            ValueError: If phone number format is invalid

        Example:
            >>> message_sid = await client.send_message(
            ...     to_phone="+254712345678",
            ...     message_text="🤖 SIPAP: Liverpool vs Chelsea prediction ready!"
            ... )
            >>> print(f"Sent: {message_sid}")
        """
        # Validate phone number format
        if not to_phone.startswith("+"):
            raise ValueError(
                f"Phone number must be in E.164 format (start with +): {to_phone}"
            )

        # Format phone number for WhatsApp
        to_whatsapp = f"whatsapp:{to_phone}"

        try:
            message = self.client.messages.create(
                from_=self.whatsapp_number,
                to=to_whatsapp,
                body=message_text
            )

            logger.info(
                "WhatsApp message sent successfully",
                extra={
                    "to_phone": to_phone,
                    "message_sid": message.sid,
                    "status": message.status,
                    "message_length": len(message_text)
                }
            )

            return message.sid

        except TwilioRestException as e:
            logger.error(
                f"Twilio API error: {e}",
                exc_info=True,
                extra={
                    "to_phone": to_phone,
                    "error_code": e.code,
                    "error_message": e.msg,
                    "twilio_status": e.status
                }
            )
            raise

        except Exception as e:
            logger.error(
                f"Failed to send WhatsApp message: {e}",
                exc_info=True,
                extra={"to_phone": to_phone}
            )
            raise

    async def send_message_with_retry(
        self,
        to_phone: str,
        message_text: str,
        max_retries: int = 3
    ) -> str:
        """Send a WhatsApp message with automatic retries.

        Args:
            to_phone: Recipient phone number (E.164 format)
            message_text: Message content
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            Message SID from Twilio

        Raises:
            TwilioRestException: If all retries fail

        Example:
            >>> message_sid = await client.send_message_with_retry(
            ...     to_phone="+254712345678",
            ...     message_text="Prediction ready!",
            ...     max_retries=3
            ... )
        """
        last_exception = None

        for attempt in range(1, max_retries + 1):
            try:
                return await self.send_message(to_phone, message_text)

            except TwilioRestException as e:
                last_exception = e

                # Don't retry on client errors (4xx)
                if e.status and 400 <= e.status < 500:
                    logger.warning(
                        f"Client error (status {e.status}), not retrying",
                        extra={"error_code": e.code}
                    )
                    raise

                # Retry on server errors (5xx) or network issues
                if attempt < max_retries:
                    logger.warning(
                        f"Twilio API error (attempt {attempt}/{max_retries}), retrying...",
                        extra={"error_code": e.code, "status": e.status}
                    )
                    continue

        # All retries exhausted
        logger.error(
            f"Failed to send message after {max_retries} attempts",
            extra={"to_phone": to_phone}
        )
        raise last_exception  # type: ignore[misc]

    def get_message_status(self, message_sid: str) -> dict[str, Any]:
        """Get the delivery status of a sent message.

        Args:
            message_sid: Twilio message SID

        Returns:
            Dictionary with message status information:
            - sid: Message SID
            - status: Current status (queued, sent, delivered, failed, etc.)
            - to: Recipient number
            - from_: Sender number
            - date_sent: When message was sent
            - error_code: Error code if failed
            - error_message: Error message if failed

        Example:
            >>> status = client.get_message_status("SM1234567890abcdef")
            >>> print(f"Status: {status['status']}")
            Status: delivered
        """
        try:
            message = self.client.messages(message_sid).fetch()

            return {
                "sid": message.sid,
                "status": message.status,
                "to": message.to,
                "from_": message.from_,
                "date_sent": message.date_sent,
                "error_code": message.error_code,
                "error_message": message.error_message
            }

        except TwilioRestException as e:
            logger.error(
                f"Failed to fetch message status: {e}",
                extra={"message_sid": message_sid, "error_code": e.code}
            )
            raise
