"""Retry logic with exponential backoff for prediction failures.

Implements resilient prediction calls with:
- Exponential backoff between retries
- Configurable max attempts
- Transient vs permanent error classification
- Cache fallback when all retries exhausted

Pattern adapted from Sentinel's resilience patterns.
"""

import asyncio
import logging
from typing import Any, Callable, TypeVar

from sipap_common.logging import get_logger

T = TypeVar("T")


class RetryExhausted(Exception):
    """All retry attempts exhausted."""

    def __init__(self, attempts: int, last_error: Exception):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"All {attempts} retry attempts exhausted. Last error: {last_error}"
        )


class PermanentError(Exception):
    """Permanent error that should not be retried."""

    pass


def is_transient_error(error: Exception) -> bool:
    """Determine if error is transient (retryable) or permanent.

    Transient errors (should retry):
    - Network timeouts
    - Connection errors
    - Temporary service unavailability
    - Rate limit errors

    Permanent errors (should not retry):
    - Invalid input (ValueError, TypeError)
    - Missing data (KeyError, AttributeError)
    - Authentication failures

    Args:
        error: Exception to classify

    Returns:
        True if error is transient and should be retried
    """
    # Permanent errors - don't retry
    permanent_types = (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        PermanentError,
    )

    if isinstance(error, permanent_types):
        return False

    # Check error message for transient indicators
    error_msg = str(error).lower()
    transient_indicators = [
        "timeout",
        "connection",
        "unavailable",
        "rate limit",
        "too many requests",
        "429",
        "503",
        "504",
    ]

    return any(indicator in error_msg for indicator in transient_indicators)


async def retry_with_backoff(
    func: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    logger: logging.Logger | None = None,
    **kwargs: Any,
) -> Any:
    """Retry async function with exponential backoff.

    Args:
        func: Async function to retry
        *args: Positional arguments for func
        max_attempts: Maximum retry attempts (default: 3)
        initial_delay: Initial delay in seconds (default: 1.0)
        backoff_factor: Multiplier for delay between attempts (default: 2.0)
        logger: Optional logger instance
        **kwargs: Keyword arguments for func

    Returns:
        Result from successful function call

    Raises:
        RetryExhausted: If all retry attempts fail
        PermanentError: If permanent error encountered

    Example:
        ```python
        result = await retry_with_backoff(
            predict_fixture,
            fixture_id="match1",
            max_attempts=3,
            initial_delay=1.0,
        )
        ```
    """
    if logger is None:
        logger = get_logger(__name__)

    last_error: Exception | None = None
    delay = initial_delay

    for attempt in range(1, max_attempts + 1):
        try:
            result = await func(*args, **kwargs)
            if attempt > 1:
                logger.info(f"Retry succeeded on attempt {attempt}/{max_attempts}")
            return result

        except Exception as e:
            last_error = e

            # Check if error is permanent
            if not is_transient_error(e):
                logger.error(
                    f"Permanent error encountered on attempt {attempt}/{max_attempts}: {e}"
                )
                raise PermanentError(f"Permanent error: {e}") from e

            # Last attempt - raise RetryExhausted
            if attempt == max_attempts:
                logger.error(
                    f"All {max_attempts} retry attempts exhausted. Last error: {e}",
                    exc_info=True,
                )
                raise RetryExhausted(attempts=max_attempts, last_error=e) from e

            # Transient error - retry with backoff
            logger.warning(
                f"Transient error on attempt {attempt}/{max_attempts}: {e}. "
                f"Retrying in {delay:.1f}s..."
            )
            await asyncio.sleep(delay)
            delay *= backoff_factor

    # Should never reach here, but satisfy type checker
    assert last_error is not None
    raise RetryExhausted(attempts=max_attempts, last_error=last_error)


async def retry_with_cache_fallback(
    func: Callable[..., Any],
    cache_key: str,
    cache_get: Callable[[str], Any | None],
    cache_set: Callable[[str, Any, int], None],
    *args: Any,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    cache_ttl: int = 3600,
    logger: logging.Logger | None = None,
    **kwargs: Any,
) -> tuple[Any, bool]:
    """Retry async function with cache fallback on exhaustion.

    Flow:
    1. Try function with retry logic
    2. If all retries exhausted, try cache
    3. If cache hit, return cached value with flag
    4. If cache miss, raise original error

    Args:
        func: Async function to retry
        cache_key: Cache key for storing/retrieving result
        cache_get: Function to retrieve from cache (returns None on miss)
        cache_set: Function to store in cache
        *args: Positional arguments for func
        max_attempts: Maximum retry attempts
        initial_delay: Initial delay in seconds
        cache_ttl: Cache TTL in seconds (default: 3600 = 1 hour)
        logger: Optional logger instance
        **kwargs: Keyword arguments for func

    Returns:
        Tuple of (result, from_cache: bool)
        - from_cache=False: Fresh result from successful call
        - from_cache=True: Result from cache fallback

    Raises:
        RetryExhausted: If all retries exhausted AND cache miss
        PermanentError: If permanent error encountered

    Example:
        ```python
        result, from_cache = await retry_with_cache_fallback(
            predict_fixture,
            cache_key="fixture:match1",
            cache_get=redis.get,
            cache_set=redis.setex,
            fixture_id="match1",
            max_attempts=3,
        )

        if from_cache:
            logger.warning("Using cached prediction (retries exhausted)")
        ```
    """
    if logger is None:
        logger = get_logger(__name__)

    try:
        # Try function with retry logic
        result = await retry_with_backoff(
            func,
            *args,
            max_attempts=max_attempts,
            initial_delay=initial_delay,
            logger=logger,
            **kwargs,
        )

        # Success - cache result for future fallback
        try:
            cache_set(cache_key, result, cache_ttl)
            logger.debug(f"Cached result for key: {cache_key} (TTL: {cache_ttl}s)")
        except Exception as e:
            logger.warning(f"Failed to cache result for {cache_key}: {e}")

        return (result, False)

    except RetryExhausted as e:
        # All retries exhausted - try cache fallback
        logger.warning(
            f"Retries exhausted for {cache_key}. Attempting cache fallback..."
        )

        try:
            cached_result = cache_get(cache_key)

            if cached_result is not None:
                logger.info(f"Cache hit for {cache_key}. Using cached result.")
                return (cached_result, True)

            # Cache miss - no fallback available
            logger.error(f"Cache miss for {cache_key}. No fallback available.")
            raise e

        except Exception as cache_error:
            logger.error(
                f"Cache retrieval failed for {cache_key}: {cache_error}",
                exc_info=True,
            )
            # Re-raise original retry error
            raise e

    except PermanentError:
        # Permanent error - don't try cache, re-raise
        raise
