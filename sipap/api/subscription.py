"""Subscription API endpoints for SIPAP.

Provides HTTP endpoints for subscription management:
- POST /subscription/cancel - Cancel subscription via web link
- GET /subscription/status - Check subscription status (optional)

These endpoints are designed to be used with secure cancellation links
sent to users via WhatsApp.
"""

import hashlib
import hmac
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from sipap.services.subscription import SubscriptionService

# Initialize router
router = APIRouter(prefix="/subscription", tags=["Subscription"])

# Initialize logger
logger = logging.getLogger(__name__)

# Secret for signing cancellation tokens (from environment)
CANCELLATION_SECRET = os.environ.get("CANCELLATION_TOKEN_SECRET", "sipap-cancellation-secret-dev")

# Token expiry time (24 hours)
TOKEN_EXPIRY_SECONDS = 24 * 60 * 60


# Request/Response Models


class CancellationRequest(BaseModel):
    """Request model for subscription cancellation."""

    user_id: str = Field(
        ...,
        description="User identifier (phone number or UUID)",
        examples=["+2348012345678"],
    )
    token: str = Field(
        ...,
        description="Cancellation verification token",
        examples=["a1b2c3d4e5f6..."],
    )


class CancellationResponse(BaseModel):
    """Response model for successful cancellation."""

    status: str = Field(..., description="Cancellation status", examples=["cancelled"])
    message: str = Field(
        ...,
        description="User-friendly message",
        examples=["Your subscription has been cancelled."],
    )
    expires_at: str | None = Field(
        None,
        description="When access ends (ISO format)",
        examples=["2026-09-05T23:59:59Z"],
    )


class SubscriptionStatusResponse(BaseModel):
    """Response model for subscription status check."""

    status: str = Field(..., description="Subscription status", examples=["active"])
    tier: str | None = Field(None, description="Subscription tier", examples=["basic"])
    expires_at: str | None = Field(
        None,
        description="When subscription expires (ISO format)",
        examples=["2026-09-05T23:59:59Z"],
    )
    max_prediction_date: str | None = Field(
        None,
        description="Last date user can request predictions for",
        examples=["2026-09-05"],
    )


class ErrorResponse(BaseModel):
    """Response model for errors."""

    status: str = Field(..., description="Error status", examples=["error"])
    error: str = Field(..., description="Error type", examples=["InvalidToken"])
    message: str = Field(
        ...,
        description="Error message",
        examples=["Invalid or expired cancellation token"],
    )


# Token generation and verification


def generate_cancellation_token(user_id: str, timestamp: int | None = None) -> str:
    """Generate a secure cancellation token for a user.

    The token includes:
    - User ID
    - Timestamp (for expiry)
    - HMAC signature

    Args:
        user_id: User identifier
        timestamp: Optional timestamp (defaults to current time)

    Returns:
        Secure token string (hex encoded)

    Example:
        >>> token = generate_cancellation_token("+2348012345678")
        >>> # Token format: {timestamp}.{signature}
    """
    if timestamp is None:
        timestamp = int(time.time())

    # Create message to sign
    message = f"{user_id}:{timestamp}"

    # Generate HMAC signature
    signature = hmac.new(
        CANCELLATION_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Return token as timestamp.signature
    return f"{timestamp}.{signature}"


def verify_cancellation_token(user_id: str, token: str) -> bool:
    """Verify a cancellation token is valid and not expired.

    Args:
        user_id: User identifier
        token: Token to verify (format: timestamp.signature)

    Returns:
        True if token is valid and not expired, False otherwise
    """
    try:
        # Parse token
        parts = token.split(".")
        if len(parts) != 2:
            logger.warning(f"Invalid token format for user {user_id}")
            return False

        timestamp_str, provided_signature = parts
        timestamp = int(timestamp_str)

        # Check expiry
        current_time = int(time.time())
        if current_time - timestamp > TOKEN_EXPIRY_SECONDS:
            logger.info(f"Expired token for user {user_id}")
            return False

        # Verify signature
        message = f"{user_id}:{timestamp}"
        expected_signature = hmac.new(
            CANCELLATION_SECRET.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(provided_signature, expected_signature):
            logger.warning(f"Invalid signature for user {user_id}")
            return False

        return True

    except (ValueError, TypeError) as e:
        logger.error(f"Token verification error for user {user_id}: {e}")
        return False


def generate_cancellation_link(user_id: str, base_url: str = "https://sipap.io") -> str:
    """Generate a complete cancellation link for a user.

    This link can be sent via WhatsApp for users to cancel their subscription
    through a web browser.

    Args:
        user_id: User identifier
        base_url: Base URL for the cancellation endpoint

    Returns:
        Complete cancellation URL

    Example:
        >>> link = generate_cancellation_link("+2348012345678")
        >>> # Returns: https://sipap.io/subscription/cancel?user_id=...&token=...
    """
    token = generate_cancellation_token(user_id)
    return f"{base_url}/api/subscription/cancel?user_id={user_id}&token={token}"


# API Endpoints


@router.post(
    "/cancel",
    response_model=CancellationResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Invalid or expired token"},
        400: {"model": ErrorResponse, "description": "Cancellation failed"},
    },
)
async def cancel_subscription(
    user_id: str = Query(..., description="User identifier"),
    token: str = Query(..., description="Verification token"),
) -> CancellationResponse:
    """Cancel a user's subscription via web link.

    This endpoint is designed to be accessed via secure cancellation links
    sent to users via WhatsApp.

    The token is verified to:
    1. Ensure it was generated for this specific user
    2. Ensure it hasn't expired (24 hours)
    3. Ensure it hasn't been tampered with

    Args:
        user_id: User identifier (from query params)
        token: Verification token (from query params)

    Returns:
        Cancellation confirmation with remaining access period

    Raises:
        HTTPException 403: If token is invalid or expired
        HTTPException 400: If cancellation fails
    """
    logger.info(f"Web cancellation request for user {user_id}")

    # Verify token
    if not verify_cancellation_token(user_id, token):
        logger.warning(f"Invalid cancellation token for user {user_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorResponse(
                status="error",
                error="InvalidToken",
                message="Invalid or expired cancellation token. Please request a new cancellation link.",
            ).model_dump(),
        )

    # Process cancellation
    try:
        service = SubscriptionService()
        result = await service.cancel_subscription(user_id)

        if result.get("success"):
            expires_at = result.get("expires_at")
            return CancellationResponse(
                status="cancelled",
                message=result.get("message", "Your subscription has been cancelled."),
                expires_at=str(expires_at) if expires_at else None,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorResponse(
                    status="error",
                    error="CancellationFailed",
                    message=result.get("error", "Unable to cancel subscription."),
                ).model_dump(),
            )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Error cancelling subscription for {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorResponse(
                status="error",
                error="InternalError",
                message="An error occurred while processing your cancellation. Please try again later.",
            ).model_dump(),
        ) from e


@router.get(
    "/status",
    response_model=SubscriptionStatusResponse,
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def get_subscription_status(
    user_id: str = Query(..., description="User identifier"),
) -> SubscriptionStatusResponse:
    """Get a user's subscription status.

    This endpoint can be used to check the current subscription state.

    Args:
        user_id: User identifier (from query params)

    Returns:
        Subscription status information

    Raises:
        HTTPException 404: If user not found
    """
    logger.info(f"Subscription status check for user {user_id}")

    try:
        service = SubscriptionService()
        info = await service.get_subscription_info(user_id)

        return SubscriptionStatusResponse(
            status=info["subscription_status"],
            tier=info["subscription_tier"],
            expires_at=str(info["subscription_expires_at"]) if info["subscription_expires_at"] else None,
            max_prediction_date=(
                info["max_prediction_date"].strftime("%Y-%m-%d")
                if info["max_prediction_date"]
                else None
            ),
        )

    except Exception as e:
        logger.error(f"Error getting subscription status for {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorResponse(
                status="error",
                error="InternalError",
                message="An error occurred while checking subscription status.",
            ).model_dump(),
        ) from e
