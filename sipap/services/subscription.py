"""Subscription management service for SIPAP.

Handles subscription validation, date range checking, and cancellation.
Ensures users can only access predictions within their subscription period.

Key Features:
- Trial users: today's matches only
- Active subscribers: up to subscription_expires_at
- Rolling week model: 7 days from subscription start (not calendar week)
- Multi-week support: 2/3/4 weeks get full period access
- Cancellation: retains access until expires_at
"""

import os
from datetime import datetime, UTC
from typing import TypedDict

from sipap_common.database.manager import DatabaseManager
from sipap_common.exceptions import DatabaseError
from sipap_common.logging import get_logger


logger = get_logger(__name__)


# Guidance messages for different subscription states
TRIAL_DATE_GUIDANCE = """You're on the free trial, which allows predictions for today's matches only.

To access predictions for future matches, subscribe to our weekly plan:
- 1 Week: $2 (7 days of predictions)
- 2 Weeks: $3.50 (14 days)
- 3 Weeks: $5 (21 days)

Reply "subscribe" to get started!"""

SUBSCRIPTION_DATE_GUIDANCE = """Your subscription allows predictions up to {expires_date}.

You requested matches on {requested_date}, which is {days_over} day(s) beyond your subscription.

Options:
1. Request matches within your period (up to {expires_date})
2. Extend your subscription for continued access

Reply "extend" to add more weeks!"""

SUBSCRIPTION_EXPIRED_GUIDANCE = """Your subscription has expired.

To continue accessing predictions, please renew your subscription.

Reply "subscribe" to view plans!"""

CANCELLATION_SUCCESS_MESSAGE = """Your subscription has been cancelled.

You'll retain access until {expires_date}.

After that, you can:
- Continue with the free trial (today's matches only)
- Resubscribe anytime with "subscribe"

Thank you for using SIPAP!"""


class SubscriptionInfo(TypedDict):
    """Subscription information for a user."""

    user_id: str
    phone_number: str | None
    subscription_status: str  # 'trial', 'active', 'cancelled', 'expired'
    subscription_tier: str | None
    subscription_expires_at: datetime | None
    max_prediction_date: datetime | None  # Same as expires_at for clarity


class SubscriptionService:
    """Service for subscription-related operations.

    Validates date ranges against user subscriptions and handles cancellations.

    Example:
        >>> service = SubscriptionService()
        >>> info = await service.get_subscription_info("user_123")
        >>> is_valid, msg = await service.validate_date_range("user_123", requested_date)
        >>> if not is_valid:
        ...     return {"error": msg}
    """

    def __init__(self, db: DatabaseManager | None = None) -> None:
        """Initialize subscription service.

        Args:
            db: Optional DatabaseManager instance. If not provided,
                will attempt to create one from environment variables.
        """
        self.db = db
        self._db_initialized = False

        # Lazy initialization of database from environment
        if self.db is None:
            self._init_db_from_env()

    def _init_db_from_env(self) -> None:
        """Initialize database connection from environment variables."""
        database_url = os.environ.get("DATABASE_URL")
        db_host = (
            os.environ.get("DB_HOST")
            or os.environ.get("RDS_HOST")
            or os.environ.get("RDS_ENDPOINT")
            or os.environ.get("POSTGRES_HOST")
        )

        if database_url:
            self.db = DatabaseManager(database_url, use_pool=True)
            self._db_initialized = True
            logger.info("SubscriptionService: Database initialized with DATABASE_URL")
        elif db_host and db_host != "localhost":
            db_port = os.environ.get("DB_PORT", "5432")
            db_name = os.environ.get("DB_NAME") or os.environ.get("POSTGRES_DB", "sipap")
            db_user = os.environ.get("DB_USER", "sipap_admin")
            db_password = os.environ.get("DB_PASSWORD", "")

            # Try POSTGRES_CREDENTIALS JSON (from Secrets Manager)
            postgres_creds = os.environ.get("POSTGRES_CREDENTIALS")
            if postgres_creds:
                try:
                    import json
                    creds = json.loads(postgres_creds)
                    db_user = creds.get("username", db_user)
                    db_password = creds.get("password", db_password)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Failed to parse POSTGRES_CREDENTIALS JSON")

            database_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            self.db = DatabaseManager(database_url, use_pool=True)
            self._db_initialized = True
            logger.info("SubscriptionService: Database initialized from environment")
        else:
            logger.warning(
                "SubscriptionService: No database configuration found. "
                "Subscription validation will use mock data in development."
            )

    async def get_subscription_info(self, user_id: str) -> SubscriptionInfo:
        """Get user's subscription information.

        Args:
            user_id: The user's ID (phone number or UUID)

        Returns:
            SubscriptionInfo with user's subscription details

        Raises:
            DatabaseError: On database query failure
        """
        if not self.db:
            # Development mode: return mock trial user
            logger.debug(f"No database - returning mock trial for user {user_id}")
            return SubscriptionInfo(
                user_id=user_id,
                phone_number=user_id if user_id.startswith("+") else None,
                subscription_status="trial",
                subscription_tier=None,
                subscription_expires_at=None,
                max_prediction_date=datetime.now(UTC),  # Today only for trial
            )

        try:
            # Query users table
            sql = """
                SELECT
                    id,
                    phone_number,
                    subscription_status,
                    subscription_tier,
                    subscription_expires_at
                FROM users
                WHERE id = :user_id OR phone_number = :user_id
                LIMIT 1
            """
            results = self.db.execute_raw_sql(sql, {"user_id": user_id})

            if not results:
                # New user - treat as trial
                logger.info(f"User {user_id} not found in database - treating as trial")
                return SubscriptionInfo(
                    user_id=user_id,
                    phone_number=user_id if user_id.startswith("+") else None,
                    subscription_status="trial",
                    subscription_tier=None,
                    subscription_expires_at=None,
                    max_prediction_date=datetime.now(UTC),
                )

            row = results[0]
            user_db_id = row[0]
            phone_number = row[1]
            status = row[2] or "trial"
            tier = row[3]
            expires_at = row[4]

            # Check if subscription has expired
            if status == "active" and expires_at:
                if datetime.now(UTC) > expires_at:
                    status = "expired"
                    # Update status in database
                    try:
                        update_sql = """
                            UPDATE users
                            SET subscription_status = 'expired'
                            WHERE id = :user_id
                        """
                        self.db.execute_raw_sql(update_sql, {"user_id": user_db_id})
                        logger.info(f"Updated expired subscription for user {user_id}")
                    except DatabaseError:
                        logger.warning(f"Failed to update expired status for user {user_id}")

            # Determine max prediction date
            max_date: datetime | None = None
            if status == "trial":
                max_date = datetime.now(UTC)  # Today only
            elif status == "active" and expires_at:
                max_date = expires_at
            elif status in ("expired", "cancelled"):
                # Check if we're still within the subscription period (cancelled but not yet expired)
                if expires_at and datetime.now(UTC) <= expires_at:
                    max_date = expires_at
                else:
                    max_date = None  # No access

            return SubscriptionInfo(
                user_id=str(user_db_id),
                phone_number=phone_number,
                subscription_status=status,
                subscription_tier=tier,
                subscription_expires_at=expires_at,
                max_prediction_date=max_date,
            )

        except DatabaseError:
            raise
        except Exception as e:
            logger.error(f"Error getting subscription info for {user_id}: {e}")
            raise DatabaseError(f"Failed to get subscription info: {e}") from e

    async def validate_date_range(
        self,
        user_id: str,
        requested_end: datetime,
    ) -> tuple[bool, str | None]:
        """Validate if requested date range is within subscription period.

        Args:
            user_id: The user's ID
            requested_end: The end date of the requested prediction range

        Returns:
            Tuple of (is_valid, guidance_message)
            - (True, None) if valid
            - (False, "guidance message") if exceeds subscription

        Example:
            >>> is_valid, msg = await service.validate_date_range("user_123", end_date)
            >>> if not is_valid:
            ...     return {"message": msg, "intent": "subscription_date_exceeded"}
        """
        info = await self.get_subscription_info(user_id)
        now = datetime.now(UTC)

        # Normalize requested_end to date comparison
        requested_date = requested_end.date() if isinstance(requested_end, datetime) else requested_end

        # Trial users: today only
        if info["subscription_status"] == "trial":
            today = now.date()
            if requested_date > today:
                logger.info(f"Trial user {user_id} blocked: requested {requested_date}, limit is today")
                return (False, TRIAL_DATE_GUIDANCE)
            return (True, None)

        # Active subscription: up to expires_at
        if info["subscription_status"] == "active":
            expires_at = info["subscription_expires_at"]
            if expires_at:
                expires_date = expires_at.date() if isinstance(expires_at, datetime) else expires_at
                if requested_date > expires_date:
                    days_over = (requested_date - expires_date).days
                    guidance = SUBSCRIPTION_DATE_GUIDANCE.format(
                        expires_date=expires_date.strftime("%B %d, %Y"),
                        requested_date=requested_date.strftime("%B %d, %Y"),
                        days_over=days_over,
                    )
                    logger.info(
                        f"Active user {user_id} blocked: requested {requested_date}, "
                        f"expires {expires_date} ({days_over} days over)"
                    )
                    return (False, guidance)
            return (True, None)

        # Cancelled but not yet expired: can still access until expires_at
        if info["subscription_status"] == "cancelled":
            expires_at = info["subscription_expires_at"]
            if expires_at:
                expires_date = expires_at.date() if isinstance(expires_at, datetime) else expires_at
                if now.date() <= expires_date:
                    # Still within subscription period
                    if requested_date > expires_date:
                        days_over = (requested_date - expires_date).days
                        guidance = SUBSCRIPTION_DATE_GUIDANCE.format(
                            expires_date=expires_date.strftime("%B %d, %Y"),
                            requested_date=requested_date.strftime("%B %d, %Y"),
                            days_over=days_over,
                        )
                        return (False, guidance)
                    return (True, None)
            # Past expiration
            logger.info(f"Cancelled user {user_id} blocked: subscription fully expired")
            return (False, SUBSCRIPTION_EXPIRED_GUIDANCE)

        # Expired: block entirely
        if info["subscription_status"] == "expired":
            logger.info(f"Expired user {user_id} blocked")
            return (False, SUBSCRIPTION_EXPIRED_GUIDANCE)

        # Unknown status - allow but log warning
        logger.warning(f"Unknown subscription status for user {user_id}: {info['subscription_status']}")
        return (True, None)

    async def cancel_subscription(self, user_id: str) -> dict:
        """Cancel user's subscription.

        The user retains access until subscription_expires_at.
        This prevents auto-renewal for the next billing cycle.

        Args:
            user_id: The user's ID

        Returns:
            dict with success status and relevant info:
            - success: True if cancelled
            - expires_at: When access ends
            - message: User-facing message
            - error: Error message if failed
        """
        if not self.db:
            logger.warning("No database - cannot cancel subscription")
            return {
                "success": False,
                "error": "Subscription management unavailable in development mode",
            }

        try:
            info = await self.get_subscription_info(user_id)

            # Check if there's an active subscription to cancel
            if info["subscription_status"] not in ("active", "trial"):
                if info["subscription_status"] == "cancelled":
                    return {
                        "success": True,
                        "expires_at": info["subscription_expires_at"],
                        "message": "Your subscription is already cancelled.",
                        "already_cancelled": True,
                    }
                return {
                    "success": False,
                    "error": "No active subscription to cancel.",
                }

            # Trial users can't cancel (nothing to cancel)
            if info["subscription_status"] == "trial":
                return {
                    "success": False,
                    "error": "You're on the free trial. No subscription to cancel.",
                }

            # Cancel the subscription
            update_sql = """
                UPDATE users
                SET subscription_status = 'cancelled',
                    updated_at = :now
                WHERE id = :user_id OR phone_number = :user_id
            """
            self.db.execute_raw_sql(
                update_sql,
                {"user_id": user_id, "now": datetime.now(UTC)},
            )

            expires_at = info["subscription_expires_at"]
            expires_str = (
                expires_at.strftime("%B %d, %Y")
                if expires_at
                else "the end of your current period"
            )

            message = CANCELLATION_SUCCESS_MESSAGE.format(expires_date=expires_str)

            logger.info(f"Subscription cancelled for user {user_id}, access until {expires_at}")

            return {
                "success": True,
                "expires_at": expires_at,
                "message": message,
            }

        except DatabaseError as e:
            logger.error(f"Database error cancelling subscription for {user_id}: {e}")
            return {
                "success": False,
                "error": "Failed to cancel subscription. Please try again later.",
            }
        except Exception as e:
            logger.error(f"Error cancelling subscription for {user_id}: {e}")
            return {
                "success": False,
                "error": "An unexpected error occurred. Please contact support.",
            }
