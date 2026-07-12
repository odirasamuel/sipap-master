"""Monitoring utilities for logging, metrics, and performance tracking.

Pattern adapted from Sentinel's telemetry and logging patterns.

Provides:
- Performance tracking decorators
- Structured logging context
- Metrics collection helpers
- CloudWatch integration patterns
"""

import functools
import logging
import time
from contextvars import ContextVar
from typing import Any, Callable
from uuid import uuid4

# Context variables for request tracking
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
match_id_ctx: ContextVar[str] = ContextVar("match_id", default="")
sport_ctx: ContextVar[str] = ContextVar("sport", default="")


def set_request_context(
    request_id: str | None = None,
    match_id: str | None = None,
    sport: str | None = None,
) -> None:
    """
    Set request context for structured logging.

    Args:
        request_id: Unique request identifier (auto-generated if None)
        match_id: Match identifier
        sport: Sport identifier
    """
    if request_id:
        request_id_ctx.set(request_id)
    else:
        request_id_ctx.set(str(uuid4()))

    if match_id:
        match_id_ctx.set(match_id)

    if sport:
        sport_ctx.set(sport)


def get_request_context() -> dict[str, str]:
    """
    Get current request context for logging.

    Returns:
        Context dictionary with request_id, match_id, sport
    """
    context = {}

    if request_id := request_id_ctx.get():
        context["request_id"] = request_id

    if match_id := match_id_ctx.get():
        context["match_id"] = match_id

    if sport := sport_ctx.get():
        context["sport"] = sport

    return context


def track_performance(
    operation_name: str | None = None,
    log_level: int = logging.INFO,
) -> Callable[[Any], Any]:
    """
    Decorator to track function performance and log metrics.

    Args:
        operation_name: Name of operation (defaults to function name)
        log_level: Logging level for performance metrics

    Returns:
        Decorated function

    Example:
        >>> @track_performance("aggregate_context")
        >>> async def aggregate_context(match_id: str):
        ...     # Implementation
        ...     pass
    """

    def decorator(func: Callable[[Any], Any]) -> Callable[[Any], Any]:
        op_name = operation_name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = logging.getLogger(func.__module__)
            start_time = time.time()

            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time

                # Log success
                logger.log(
                    log_level,
                    f"Operation completed: {op_name}",
                    extra={
                        **get_request_context(),
                        "operation": op_name,
                        "duration_seconds": round(duration, 3),
                        "status": "success",
                    },
                )

                return result

            except Exception as e:
                duration = time.time() - start_time

                # Log failure
                logger.error(
                    f"Operation failed: {op_name}",
                    extra={
                        **get_request_context(),
                        "operation": op_name,
                        "duration_seconds": round(duration, 3),
                        "status": "error",
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                    exc_info=True,
                )

                raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = logging.getLogger(func.__module__)
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                # Log success
                logger.log(
                    log_level,
                    f"Operation completed: {op_name}",
                    extra={
                        **get_request_context(),
                        "operation": op_name,
                        "duration_seconds": round(duration, 3),
                        "status": "success",
                    },
                )

                return result

            except Exception as e:
                duration = time.time() - start_time

                # Log failure
                logger.error(
                    f"Operation failed: {op_name}",
                    extra={
                        **get_request_context(),
                        "operation": op_name,
                        "duration_seconds": round(duration, 3),
                        "status": "error",
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                    exc_info=True,
                )

                raise

        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class PerformanceTimer:
    """
    Context manager for tracking code block performance.

    Example:
        >>> with PerformanceTimer("data_aggregation") as timer:
        ...     data = await fetch_data()
        >>> print(f"Duration: {timer.duration}s")
    """

    def __init__(self, operation_name: str, logger: logging.Logger | None = None):
        """
        Initialize performance timer.

        Args:
            operation_name: Name of operation being timed
            logger: Logger instance (defaults to root logger)
        """
        self.operation_name = operation_name
        self.logger = logger or logging.getLogger(__name__)
        self.start_time = 0.0
        self.duration = 0.0

    def __enter__(self) -> "PerformanceTimer":
        """Start timer."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop timer and log duration."""
        # Suppress unused parameter warnings (required by context manager protocol)
        _ = exc_type, exc_val, exc_tb

        self.duration = time.time() - self.start_time

        self.logger.info(
            f"Performance: {self.operation_name}",
            extra={
                **get_request_context(),
                "operation": self.operation_name,
                "duration_seconds": round(self.duration, 3),
            },
        )


def log_prediction_metrics(
    prediction: dict[str, Any],
    context: dict[str, Any],
    logger: logging.Logger | None = None,
) -> None:
    """
    Log prediction metrics for monitoring and analytics.

    Args:
        prediction: Prediction result
        context: Match context
        logger: Logger instance
    """
    logger = logger or logging.getLogger(__name__)

    metrics = {
        **get_request_context(),
        "metric_type": "prediction",
        "outcome": prediction.get("outcome"),
        "probability": prediction.get("probability"),
        "confidence": prediction.get("confidence"),
        "quality_gate": prediction.get("quality_gate"),
        "expected_value": prediction.get("expected_value", {}).get("expected_value"),
        "is_positive_ev": prediction.get("expected_value", {}).get("is_positive_ev"),
        "data_completeness": context.get("data_completeness", 0),
    }

    logger.info("Prediction metrics", extra=metrics)


def log_mcp_metrics(
    server_name: str,
    tool_name: str,
    duration: float,
    status: str,
    error: str | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """
    Log MCP call metrics for monitoring.

    Args:
        server_name: MCP server name
        tool_name: Tool name
        duration: Call duration in seconds
        status: Call status (success/error)
        error: Error message if failed
        logger: Logger instance
    """
    logger = logger or logging.getLogger(__name__)

    metrics = {
        **get_request_context(),
        "metric_type": "mcp_call",
        "mcp_server": server_name,
        "tool_name": tool_name,
        "duration_seconds": round(duration, 3),
        "status": status,
    }

    if error:
        metrics["error"] = error

    level = logging.INFO if status == "success" else logging.ERROR
    logger.log(level, f"MCP call: {server_name}.{tool_name}", extra=metrics)


# Import asyncio at the end to avoid circular import issues
import asyncio  # noqa: E402
