"""Error Classification - Determine retry behavior for exceptions.

Pattern adapted from Sentinel's error classification system.

Classifies errors as:
- Permanent: Delete message (bad input, invalid data, unrecoverable)
- Transient: Retry message (network issues, rate limits, temporary failures)

Permanent errors prevent infinite retries on bad data.
Transient errors allow recovery from temporary failures.

Example:
    >>> from sipap.core.errors import classify_error, ErrorType
    >>> try:
    ...     process_message(message)
    ... except Exception as e:
    ...     error_type = classify_error(e)
    ...     if error_type == ErrorType.PERMANENT:
    ...         delete_message()  # Don't retry
    ...     else:
    ...         return_to_queue()  # Retry later
"""

import json
import logging
from enum import Enum
from typing import Type

from botocore.exceptions import ClientError

try:
    from twilio.base.exceptions import TwilioRestException
except ImportError:
    # Twilio not installed (optional dependency)
    TwilioRestException = None  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """Error classification types.

    Attributes:
        PERMANENT: Unrecoverable error (delete message)
        TRANSIENT: Temporary error (retry message)
    """

    PERMANENT = "permanent"
    TRANSIENT = "transient"


# Permanent error types (don't retry)
PERMANENT_ERRORS: tuple[Type[Exception], ...] = (
    json.JSONDecodeError,  # Malformed JSON
    KeyError,  # Missing required field
    ValueError,  # Invalid value/format
    TypeError,  # Type mismatch
    UnicodeDecodeError,  # Encoding issues
)

# Transient error types (retry)
TRANSIENT_ERRORS: tuple[Type[Exception], ...] = (
    ConnectionError,  # Network connectivity
    TimeoutError,  # Request timeout
    OSError,  # System-level errors
    # ClientError handled specially (some permanent, some transient)
)


def classify_error(error: Exception) -> ErrorType:
    """Classify error as permanent or transient.

    Permanent errors (delete message):
    - JSON parsing errors
    - Missing required fields (KeyError)
    - Invalid data format (ValueError)
    - Type mismatches (TypeError)

    Transient errors (retry message):
    - Network errors (ConnectionError, TimeoutError)
    - AWS throttling (ClientError with throttling codes)
    - System errors (OSError)
    - Unknown errors (conservative: retry by default)

    Args:
        error: Exception to classify

    Returns:
        ErrorType.PERMANENT or ErrorType.TRANSIENT

    Example:
        >>> error_type = classify_error(json.JSONDecodeError("bad json", "", 0))
        >>> assert error_type == ErrorType.PERMANENT
        >>>
        >>> error_type = classify_error(ConnectionError("timeout"))
        >>> assert error_type == ErrorType.TRANSIENT
    """
    # Check permanent errors first
    if isinstance(error, PERMANENT_ERRORS):
        logger.info(
            f"Classified as PERMANENT: {type(error).__name__}: {error}",
            extra={"error_type": "permanent", "error_class": type(error).__name__}
        )
        return ErrorType.PERMANENT

    # Check transient errors
    if isinstance(error, TRANSIENT_ERRORS):
        logger.info(
            f"Classified as TRANSIENT: {type(error).__name__}: {error}",
            extra={"error_type": "transient", "error_class": type(error).__name__}
        )
        return ErrorType.TRANSIENT

    # Special handling for AWS ClientError
    if isinstance(error, ClientError):
        return _classify_client_error(error)

    # Special handling for Twilio errors
    if TwilioRestException and isinstance(error, TwilioRestException):
        return _classify_twilio_error(error)

    # Check error message content for known patterns
    error_message = str(error).lower()

    # Permanent: Invalid input, bad request
    if any(
        pattern in error_message
        for pattern in [
            "invalid",
            "malformed",
            "bad request",
            "not found",
            "does not exist",
        ]
    ):
        logger.info(
            f"Classified as PERMANENT (message pattern): {error}",
            extra={"error_type": "permanent", "error_class": type(error).__name__}
        )
        return ErrorType.PERMANENT

    # Transient: Rate limits, throttling, temporary failures
    if any(
        pattern in error_message
        for pattern in [
            "rate limit",
            "throttle",
            "too many requests",
            "temporarily unavailable",
            "timeout",
            "connection",
        ]
    ):
        logger.info(
            f"Classified as TRANSIENT (message pattern): {error}",
            extra={"error_type": "transient", "error_class": type(error).__name__}
        )
        return ErrorType.TRANSIENT

    # Default: Conservative approach (retry unknown errors)
    logger.warning(
        f"Unknown error type, defaulting to TRANSIENT: {type(error).__name__}: {error}",
        extra={"error_type": "transient", "error_class": type(error).__name__}
    )
    return ErrorType.TRANSIENT


def _classify_client_error(error: ClientError) -> ErrorType:
    """Classify AWS ClientError as permanent or transient.

    Args:
        error: boto3 ClientError

    Returns:
        ErrorType.PERMANENT or ErrorType.TRANSIENT
    """
    error_code = error.response.get("Error", {}).get("Code", "")

    # Transient: Throttling, rate limits
    transient_codes = [
        "ThrottlingException",
        "ProvisionedThroughputExceededException",
        "RequestLimitExceeded",
        "ServiceUnavailable",
        "InternalServerError",
        "RequestTimeout",
    ]

    if error_code in transient_codes:
        logger.info(
            f"AWS ClientError classified as TRANSIENT: {error_code}",
            extra={"error_type": "transient", "error_code": error_code}
        )
        return ErrorType.TRANSIENT

    # Permanent: Invalid parameters, access denied
    permanent_codes = [
        "InvalidParameterValue",
        "InvalidParameterCombination",
        "ValidationError",
        "AccessDeniedException",
        "ResourceNotFoundException",
    ]

    if error_code in permanent_codes:
        logger.info(
            f"AWS ClientError classified as PERMANENT: {error_code}",
            extra={"error_type": "permanent", "error_code": error_code}
        )
        return ErrorType.PERMANENT

    # Default: Transient (retry unknown AWS errors)
    logger.warning(
        f"Unknown AWS error code, defaulting to TRANSIENT: {error_code}",
        extra={"error_type": "transient", "error_code": error_code}
    )
    return ErrorType.TRANSIENT


def _classify_twilio_error(error: "TwilioRestException") -> ErrorType:
    """Classify Twilio API error as permanent or transient.

    Args:
        error: TwilioRestException

    Returns:
        ErrorType.PERMANENT or ErrorType.TRANSIENT

    Twilio Error Codes:
        - 4xx (400-499): Client errors (permanent - bad input, invalid phone, etc.)
        - 5xx (500-599): Server errors (transient - retry)
        - 429: Rate limit (transient - retry)

    Example:
        >>> # Error 21211: Invalid phone number (400) → PERMANENT
        >>> # Error 20429: Rate limit (429) → TRANSIENT
        >>> # Error 20500: Internal error (500) → TRANSIENT
    """
    status = error.status

    # Client errors (4xx): Permanent - bad request, invalid input
    if status and 400 <= status < 500:
        # Exception: 429 is rate limiting (transient)
        if status == 429:
            logger.info(
                f"Twilio rate limit error, classified as TRANSIENT",
                extra={
                    "error_type": "transient",
                    "error_code": error.code,
                    "status": status
                }
            )
            return ErrorType.TRANSIENT

        # All other 4xx errors are permanent (invalid phone, bad params, etc.)
        logger.info(
            f"Twilio client error (4xx), classified as PERMANENT: {error.code} - {error.msg}",
            extra={
                "error_type": "permanent",
                "error_code": error.code,
                "status": status
            }
        )
        return ErrorType.PERMANENT

    # Server errors (5xx): Transient - retry
    if status and status >= 500:
        logger.info(
            f"Twilio server error (5xx), classified as TRANSIENT: {error.code}",
            extra={
                "error_type": "transient",
                "error_code": error.code,
                "status": status
            }
        )
        return ErrorType.TRANSIENT

    # Default: Transient (retry unknown Twilio errors)
    logger.warning(
        f"Unknown Twilio error status, defaulting to TRANSIENT: {error.code}",
        extra={
            "error_type": "transient",
            "error_code": error.code,
            "status": status
        }
    )
    return ErrorType.TRANSIENT
