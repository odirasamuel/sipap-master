"""API module for SIPAP HTTP endpoints.

Provides FastAPI-based REST API for:
- Predictions
- Subscription management
- Health checks
"""

from sipap.api.handlers import app
from sipap.api.subscription import (
    generate_cancellation_link,
    generate_cancellation_token,
    router as subscription_router,
    verify_cancellation_token,
)

__all__ = [
    "app",
    "subscription_router",
    "generate_cancellation_link",
    "generate_cancellation_token",
    "verify_cancellation_token",
]
