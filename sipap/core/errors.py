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
