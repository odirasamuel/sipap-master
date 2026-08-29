"""Subscription management service for SIPAP.

Handles subscription validation, access control, and cancellation.
Ensures users can only access predictions with valid subscription.

Key Features:
- Trial users: ONE free prediction request only (not unlimited)
- Active subscribers: up to subscription_expires_at
- Rolling week model: 7 days from subscription start (not calendar week)
- Multi-week support: 2/3/4 weeks get full period access
- Cancellation: retains access until expires_at
- Date validation: blocks explicit future dates past subscription
"""

import os
from datetime import datetime, UTC
from typing import TypedDict

from sipap_common.database.manager import DatabaseManager
from sipap_common.exceptions import DatabaseError
from sipap_common.logging import get_logger


logger = get_logger(__name__)


# Guidance messages for different subscription states
TRIAL_DATE_GUIDANCE = """You're on the free trial, which allows ONE free prediction request.

You've already used your free trial. To continue accessing predictions, subscribe to our weekly plan:
- 1 Week: $2 (7 days of predictions)
- 2 Weeks: $3.50 (14 days)
- 3 Weeks: $5 (21 days)

Reply "subscribe" to get started!"""

TRIAL_USED_GUIDANCE = """You've already used your free trial prediction.

To continue accessing predictions, subscribe to our weekly plan:
- 1 Week: $2 (7 days of unlimited predictions)
- 2 Weeks: $3.50 (14 days)
- 3 Weeks: $5 (21 days)

Reply "subscribe" to get started!"""

NO_SUBSCRIPTION_GUIDANCE = """You need an active subscription to access predictions.

Subscribe to our weekly plan:
- 1 Week: $2 (7 days of unlimited predictions)
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
- Resubscribe anytime with "subscribe"

Thank you for using Valo!"""


class SubscriptionInfo(TypedDict):
    """Subscription information for a user."""

    user_id: str
    phone_number: str | None
    subscription_status: str  # 'trial', 'active', 'cancelled', 'expired'
    subscription_tier: str | None
    subscription_expires_at: datetime | None
    max_prediction_date: datetime | None  # Same as expires_at for clarity
    trial_used_at: datetime | None  # When trial was used (None = not used yet)


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

    @staticmethod
    def _is_phone_number(user_id: str) -> bool:
        """Check if user_id is a phone number (starts with +)."""
        return user_id.startswith("+")

    @staticmethod
    def _build_user_where_clause(user_id: str) -> tuple[str, dict]:
        """Build WHERE clause based on user_id format.

        Phone numbers (starting with +) should only compare to phone_number column.
        UUIDs should only compare to id column.
        This prevents PostgreSQL type comparison errors.

        Args:
            user_id: User ID (phone number or UUID)

        Returns:
            Tuple of (where_clause, params_dict)
        """
        if SubscriptionService._is_phone_number(user_id):
            return ("phone_number = :user_id", {"user_id": user_id})
        else:
            return ("id = :user_id", {"user_id": user_id})

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
            # Development mode: return mock active user for local testing
            # In production, users must be registered via payment
            logger.debug(f"No database - returning mock active subscription for user {user_id}")
            return SubscriptionInfo(
                user_id=user_id,
                phone_number=user_id if user_id.startswith("+") else None,
                subscription_status="active",  # Allow testing in dev mode
                subscription_tier="weekly",
                subscription_expires_at=datetime.now(UTC).replace(hour=23, minute=59, second=59),
                max_prediction_date=datetime.now(UTC).replace(hour=23, minute=59, second=59),
                trial_used_at=None,
            )

        try:
            # Query users table (trial_used_at tracks when the one free request was used)
            # Use appropriate WHERE clause based on user_id format (phone vs UUID)
            where_clause, params = self._build_user_where_clause(user_id)
            sql = f"""
                SELECT
                    id,
                    phone_number,
                    subscription_status,
                    subscription_tier,
                    subscription_expires_at,
                    trial_used_at
                FROM users
                WHERE {where_clause}
                LIMIT 1
            """
            results = self.db.execute_raw_sql(sql, params)

            if not results:
                # User not found - no subscription (must register via payment)
                logger.info(f"User {user_id} not found in database - no subscription")
                return SubscriptionInfo(
                    user_id=user_id,
                    phone_number=user_id if user_id.startswith("+") else None,
                    subscription_status="none",  # Not registered
                    subscription_tier=None,
                    subscription_expires_at=None,
                    max_prediction_date=None,  # No access
                    trial_used_at=None,
                )

            row = results[0]
            user_db_id = row[0]
            phone_number = row[1]
            status = row[2] or "trial"
            tier = row[3]
            expires_at = row[4]
            trial_used_at = row[5] if len(row) > 5 else None

            # Check if subscription has expired
            if status == "active" and expires_at:
                if datetime.now(UTC) > expires_at:
                    status = "expired"
                    # Update status in database
                    # Use RETURNING to make execute_raw_sql work (it expects rows)
                    try:
                        update_sql = """
                            UPDATE users
                            SET subscription_status = 'expired'
                            WHERE id = :user_id
                            RETURNING id
                        """
                        self.db.execute_raw_sql(update_sql, {"user_id": user_db_id})
                        logger.info(f"Updated expired subscription for user {user_id}")
                    except DatabaseError:
                        logger.warning(f"Failed to update expired status for user {user_id}")

            # Determine max prediction date
            max_date: datetime | None = None
            if status == "trial":
                max_date = datetime.now(UTC)  # Today only (but trial is limited to ONE request)
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
                trial_used_at=trial_used_at,
            )

        except DatabaseError:
            raise
        except Exception as e:
            logger.error(f"Error getting subscription info for {user_id}: {e}")
            raise DatabaseError(f"Failed to get subscription info: {e}") from e

    async def validate_access(
        self,
        user_id: str,
        requested_end: datetime | None = None,
    ) -> tuple[bool, str | None]:
        """Validate if user can access predictions.

        This is the PRIMARY validation method for ALL prediction requests.
        It checks:
        1. Subscription status (active, trial, expired, cancelled)
        2. Trial usage (trial users get ONE free request only)
        3. Date range (if explicitly requesting future dates)

        Args:
            user_id: The user's ID
            requested_end: Optional end date (for explicit future date validation)

        Returns:
            Tuple of (is_valid, guidance_message)
            - (True, None) if user can access predictions
            - (False, "guidance message") if access denied

        Example:
            >>> is_valid, msg = await service.validate_access("user_123")
            >>> if not is_valid:
            ...     return {"message": msg, "intent": "subscription_required"}
        """
        info = await self.get_subscription_info(user_id)
        now = datetime.now(UTC)

        # Unregistered users: must subscribe first
        if info["subscription_status"] == "none":
            logger.info(f"Unregistered user {user_id} blocked: no subscription")
            return (False, NO_SUBSCRIPTION_GUIDANCE)

        # Trial users: ONE free request only
        if info["subscription_status"] == "trial":
            if info["trial_used_at"] is not None:
                # Trial already used
                logger.info(f"Trial user {user_id} blocked: trial already used at {info['trial_used_at']}")
                return (False, TRIAL_USED_GUIDANCE)
            # Trial not used yet - allow (will be marked as used after prediction)
            logger.info(f"Trial user {user_id} allowed: first free prediction")
            return (True, None)

        # Active subscription: check expiry and optional date range
        if info["subscription_status"] == "active":
            expires_at = info["subscription_expires_at"]
            if expires_at and now > expires_at:
                # Subscription expired (shouldn't reach here if get_subscription_info updates status)
                logger.info(f"Active user {user_id} blocked: subscription expired at {expires_at}")
                return (False, SUBSCRIPTION_EXPIRED_GUIDANCE)

            # Check date range if explicitly requested
            if requested_end:
                is_valid, guidance = await self._validate_explicit_date(info, requested_end)
                if not is_valid:
                    return (False, guidance)

            return (True, None)

        # Cancelled but not yet expired: can still access until expires_at
        if info["subscription_status"] == "cancelled":
            expires_at = info["subscription_expires_at"]
            if expires_at and now <= expires_at:
                # Still within subscription period
                if requested_end:
                    is_valid, guidance = await self._validate_explicit_date(info, requested_end)
                    if not is_valid:
                        return (False, guidance)
                return (True, None)
            # Past expiration
            logger.info(f"Cancelled user {user_id} blocked: subscription fully expired")
            return (False, SUBSCRIPTION_EXPIRED_GUIDANCE)

        # Expired: block entirely
        if info["subscription_status"] == "expired":
            logger.info(f"Expired user {user_id} blocked")
            return (False, SUBSCRIPTION_EXPIRED_GUIDANCE)

        # Unknown status - block with guidance
        logger.warning(f"Unknown subscription status for user {user_id}: {info['subscription_status']}")
        return (False, NO_SUBSCRIPTION_GUIDANCE)

    async def _validate_explicit_date(
        self,
        info: SubscriptionInfo,
        requested_end: datetime,
    ) -> tuple[bool, str | None]:
        """Validate explicitly requested date against subscription period.

        Only called when user explicitly requests a future date.

        Args:
            info: User's subscription info
            requested_end: The explicitly requested end date

        Returns:
            Tuple of (is_valid, guidance_message)
        """
        expires_at = info["subscription_expires_at"]
        if not expires_at:
            return (True, None)

        requested_date = requested_end.date() if isinstance(requested_end, datetime) else requested_end
        expires_date = expires_at.date() if isinstance(expires_at, datetime) else expires_at

        if requested_date > expires_date:
            days_over = (requested_date - expires_date).days
            guidance = SUBSCRIPTION_DATE_GUIDANCE.format(
                expires_date=expires_date.strftime("%B %d, %Y"),
                requested_date=requested_date.strftime("%B %d, %Y"),
                days_over=days_over,
            )
            logger.info(
                f"User blocked: requested {requested_date}, expires {expires_date} ({days_over} days over)"
            )
            return (False, guidance)

        return (True, None)

    async def mark_trial_used(self, user_id: str) -> bool:
        """Mark trial as used for a user.

        Called after a trial user successfully receives their first prediction.
        User must already exist in database (created via payment).

        Args:
            user_id: The user's ID (phone number or UUID)

        Returns:
            True if successfully marked, False otherwise
        """
        if not self.db:
            logger.warning("No database - cannot mark trial as used")
            return False

        try:
            now = datetime.now(UTC)

            # Update trial_used_at in database
            # Use COALESCE to only set if not already set (idempotent)
            # Use appropriate WHERE clause based on user_id format (phone vs UUID)
            # Use RETURNING to make execute_raw_sql work (it expects rows)
            where_clause, params = self._build_user_where_clause(user_id)
            params["now"] = now
            update_sql = f"""
                UPDATE users
                SET trial_used_at = COALESCE(trial_used_at, :now),
                    updated_at = :now
                WHERE {where_clause}
                RETURNING id
            """
            results = self.db.execute_raw_sql(update_sql, params)
            if results:
                logger.info(f"Marked trial as used for user {user_id}")
                return True
            else:
                logger.warning(f"No user found to mark trial as used: {user_id}")
                return False

        except Exception as e:
            logger.error(f"Error marking trial as used for {user_id}: {e}")
            return False

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
            # Use appropriate WHERE clause based on user_id format (phone vs UUID)
            # Use RETURNING to make execute_raw_sql work (it expects rows)
            where_clause, params = self._build_user_where_clause(user_id)
            params["now"] = datetime.now(UTC)
            update_sql = f"""
                UPDATE users
                SET subscription_status = 'cancelled',
                    updated_at = :now
                WHERE {where_clause}
                RETURNING id
            """
            self.db.execute_raw_sql(update_sql, params)

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
