"""Unit tests for SubscriptionService.

Tests subscription validation, access control, trial usage, and cancellation.
"""

from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from sipap.services.subscription import (
    SubscriptionInfo,
    SubscriptionService,
    SUBSCRIPTION_DATE_GUIDANCE,
    SUBSCRIPTION_EXPIRED_GUIDANCE,
    TRIAL_DATE_GUIDANCE,
    TRIAL_USED_GUIDANCE,
    NO_SUBSCRIPTION_GUIDANCE,
)


class TestPhoneNumberDetection:
    """Tests for phone number vs UUID detection helpers."""

    def test_is_phone_number_with_plus_prefix(self):
        """Phone numbers starting with + should be detected."""
        assert SubscriptionService._is_phone_number("+2347025761599") is True
        assert SubscriptionService._is_phone_number("+14155551234") is True
        assert SubscriptionService._is_phone_number("+447911123456") is True

    def test_is_phone_number_without_plus_prefix(self):
        """UUIDs and other IDs should not be detected as phone numbers."""
        assert SubscriptionService._is_phone_number("550e8400-e29b-41d4-a716-446655440000") is False
        assert SubscriptionService._is_phone_number("user_123") is False
        assert SubscriptionService._is_phone_number("abc123") is False

    def test_build_where_clause_for_phone_number(self):
        """Phone numbers should generate phone_number WHERE clause."""
        clause, params = SubscriptionService._build_user_where_clause("+2347025761599")
        assert clause == "phone_number = :user_id"
        assert params == {"user_id": "+2347025761599"}

    def test_build_where_clause_for_uuid(self):
        """UUIDs should generate id WHERE clause."""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        clause, params = SubscriptionService._build_user_where_clause(uuid)
        assert clause == "id = :user_id"
        assert params == {"user_id": uuid}


class TestSubscriptionService:
    """Test suite for SubscriptionService."""

    @pytest.fixture
    def service(self):
        """Create a SubscriptionService without database."""
        # Mock environment to not have database
        with patch.dict("os.environ", {}, clear=True):
            return SubscriptionService(db=None)

    @pytest.fixture
    def service_with_mock_db(self):
        """Create a SubscriptionService with mocked database."""
        mock_db = MagicMock()
        return SubscriptionService(db=mock_db)


class TestGetSubscriptionInfo:
    """Tests for get_subscription_info()."""

    @pytest.fixture
    def service(self):
        """Create service without database."""
        return SubscriptionService(db=None)

    @pytest.mark.asyncio
    async def test_returns_trial_for_new_user_without_db(self, service):
        """Without database, all users are treated as trial (not used)."""
        info = await service.get_subscription_info("user_123")

        assert info["user_id"] == "user_123"
        assert info["subscription_status"] == "trial"
        assert info["subscription_tier"] is None
        assert info["subscription_expires_at"] is None
        assert info["trial_used_at"] is None  # Trial not used yet
        # Trial users can only access today
        assert info["max_prediction_date"].date() == datetime.now(UTC).date()

    @pytest.mark.asyncio
    async def test_returns_active_for_subscribed_user(self):
        """Active subscription returns correct info."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=7)

        # Mock database result (with trial_used_at column)
        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "active", "basic", expires_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        info = await service.get_subscription_info("+2348012345678")

        assert info["subscription_status"] == "active"
        assert info["subscription_tier"] == "basic"
        assert info["subscription_expires_at"] == expires_at
        assert info["max_prediction_date"] == expires_at

    @pytest.mark.asyncio
    async def test_updates_expired_subscription(self):
        """Expired subscription is detected and status updated."""
        mock_db = MagicMock()
        expired_at = datetime.now(UTC) - timedelta(days=1)  # Expired yesterday

        # Mock database result
        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "active", "basic", expired_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        info = await service.get_subscription_info("+2348012345678")

        assert info["subscription_status"] == "expired"
        # Verify update was called
        assert mock_db.execute_raw_sql.call_count == 2  # Query + Update

    @pytest.mark.asyncio
    async def test_returns_trial_used_at(self):
        """Trial user with used trial returns trial_used_at."""
        mock_db = MagicMock()
        trial_used_time = datetime.now(UTC) - timedelta(hours=2)

        # Mock database result with trial_used_at set
        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "trial", None, None, trial_used_time)
        ]

        service = SubscriptionService(db=mock_db)
        info = await service.get_subscription_info("+2348012345678")

        assert info["subscription_status"] == "trial"
        assert info["trial_used_at"] == trial_used_time


class TestValidateAccess:
    """Tests for validate_access() - the PRIMARY validation method."""

    @pytest.fixture
    def service(self):
        """Create service without database (trial mode)."""
        return SubscriptionService(db=None)

    @pytest.mark.asyncio
    async def test_trial_user_first_request_allowed(self, service):
        """Trial users can make ONE free request."""
        # Without DB, user is treated as trial (not used)
        is_valid, guidance = await service.validate_access("user_123")

        assert is_valid is True
        assert guidance is None

    @pytest.mark.asyncio
    async def test_trial_user_second_request_blocked(self):
        """Trial users are blocked after using their free request."""
        mock_db = MagicMock()
        trial_used_time = datetime.now(UTC) - timedelta(hours=1)

        # Mock: trial user who already used their free request
        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "trial", None, None, trial_used_time)
        ]

        service = SubscriptionService(db=mock_db)
        is_valid, guidance = await service.validate_access("+2348012345678")

        assert is_valid is False
        assert guidance == TRIAL_USED_GUIDANCE

    @pytest.mark.asyncio
    async def test_active_user_allowed(self):
        """Active users can access predictions."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=7)

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "active", "basic", expires_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        is_valid, guidance = await service.validate_access("+2348012345678")

        assert is_valid is True
        assert guidance is None

    @pytest.mark.asyncio
    async def test_active_user_explicit_future_date_blocked(self):
        """Active users blocked when explicitly requesting dates past subscription."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=7)

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "active", "basic", expires_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        # Request date 10 days from now (3 days past subscription)
        requested_date = datetime.now(UTC) + timedelta(days=10)

        is_valid, guidance = await service.validate_access("+2348012345678", requested_date)

        assert is_valid is False
        assert "Your subscription allows predictions up to" in guidance

    @pytest.mark.asyncio
    async def test_active_user_within_period_allowed(self):
        """Active users can request within subscription period."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=7)

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "active", "basic", expires_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        # Request date 3 days from now (within subscription)
        requested_date = datetime.now(UTC) + timedelta(days=3)

        is_valid, guidance = await service.validate_access("+2348012345678", requested_date)

        assert is_valid is True
        assert guidance is None

    @pytest.mark.asyncio
    async def test_expired_user_blocked(self):
        """Expired users are blocked."""
        mock_db = MagicMock()
        expired_at = datetime.now(UTC) - timedelta(days=1)

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "expired", "basic", expired_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        is_valid, guidance = await service.validate_access("+2348012345678")

        assert is_valid is False
        assert guidance == SUBSCRIPTION_EXPIRED_GUIDANCE

    @pytest.mark.asyncio
    async def test_cancelled_within_period_allowed(self):
        """Cancelled users can access until expires_at."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=3)  # Still active

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "cancelled", "basic", expires_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        is_valid, guidance = await service.validate_access("+2348012345678")

        assert is_valid is True
        assert guidance is None

    @pytest.mark.asyncio
    async def test_cancelled_past_period_blocked(self):
        """Cancelled users are blocked after expiry."""
        mock_db = MagicMock()
        expired_at = datetime.now(UTC) - timedelta(days=1)  # Already expired

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "cancelled", "basic", expired_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        is_valid, guidance = await service.validate_access("+2348012345678")

        assert is_valid is False
        assert guidance == SUBSCRIPTION_EXPIRED_GUIDANCE


class TestMarkTrialUsed:
    """Tests for mark_trial_used()."""

    @pytest.mark.asyncio
    async def test_mark_trial_without_db_fails(self):
        """Marking trial fails without database."""
        service = SubscriptionService(db=None)

        result = await service.mark_trial_used("user_123")

        assert result is False

    @pytest.mark.asyncio
    async def test_mark_trial_success(self):
        """Marking trial as used succeeds with database."""
        mock_db = MagicMock()
        mock_db.execute_raw_sql.return_value = []  # Update returns no rows

        service = SubscriptionService(db=mock_db)
        result = await service.mark_trial_used("+2348012345678")

        assert result is True
        # Verify update was called
        assert mock_db.execute_raw_sql.called
        call_args = mock_db.execute_raw_sql.call_args
        assert "trial_used_at" in call_args[0][0]


class TestValidateDateRange:
    """Tests for validate_date_range() - legacy date-only validation."""

    @pytest.fixture
    def service(self):
        """Create service without database (trial mode)."""
        return SubscriptionService(db=None)

    @pytest.mark.asyncio
    async def test_trial_user_today_allowed(self, service):
        """Trial users can request today's matches."""
        today = datetime.now(UTC)

        is_valid, guidance = await service.validate_date_range("user_123", today)

        assert is_valid is True
        assert guidance is None

    @pytest.mark.asyncio
    async def test_trial_user_tomorrow_blocked(self, service):
        """Trial users cannot request tomorrow's matches."""
        tomorrow = datetime.now(UTC) + timedelta(days=1)

        is_valid, guidance = await service.validate_date_range("user_123", tomorrow)

        assert is_valid is False
        assert guidance == TRIAL_DATE_GUIDANCE

    @pytest.mark.asyncio
    async def test_active_user_within_period_allowed(self):
        """Active users can request within subscription period."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=7)

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "active", "basic", expires_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        requested_date = datetime.now(UTC) + timedelta(days=3)  # Within period

        is_valid, guidance = await service.validate_date_range("+2348012345678", requested_date)

        assert is_valid is True
        assert guidance is None

    @pytest.mark.asyncio
    async def test_active_user_beyond_period_blocked(self):
        """Active users cannot request beyond subscription period."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=7)

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "active", "basic", expires_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        requested_date = datetime.now(UTC) + timedelta(days=10)  # Beyond period

        is_valid, guidance = await service.validate_date_range("+2348012345678", requested_date)

        assert is_valid is False
        assert "Your subscription allows predictions up to" in guidance

    @pytest.mark.asyncio
    async def test_expired_user_blocked(self):
        """Expired users are blocked."""
        mock_db = MagicMock()
        expired_at = datetime.now(UTC) - timedelta(days=1)

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "expired", "basic", expired_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        today = datetime.now(UTC)

        is_valid, guidance = await service.validate_date_range("+2348012345678", today)

        assert is_valid is False
        assert guidance == SUBSCRIPTION_EXPIRED_GUIDANCE

    @pytest.mark.asyncio
    async def test_cancelled_within_period_allowed(self):
        """Cancelled users can access until expires_at."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=3)  # Still active

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "cancelled", "basic", expires_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        today = datetime.now(UTC)

        is_valid, guidance = await service.validate_date_range("+2348012345678", today)

        assert is_valid is True
        assert guidance is None

    @pytest.mark.asyncio
    async def test_cancelled_past_period_blocked(self):
        """Cancelled users are blocked after expiry."""
        mock_db = MagicMock()
        expired_at = datetime.now(UTC) - timedelta(days=1)  # Already expired

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "cancelled", "basic", expired_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        today = datetime.now(UTC)

        is_valid, guidance = await service.validate_date_range("+2348012345678", today)

        assert is_valid is False
        assert guidance == SUBSCRIPTION_EXPIRED_GUIDANCE


class TestCancelSubscription:
    """Tests for cancel_subscription()."""

    @pytest.mark.asyncio
    async def test_cancel_without_db_fails(self):
        """Cancellation fails without database."""
        service = SubscriptionService(db=None)

        result = await service.cancel_subscription("user_123")

        assert result["success"] is False
        assert "unavailable" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_active_subscription(self):
        """Active subscription can be cancelled."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=5)

        # First call: get subscription info
        mock_db.execute_raw_sql.side_effect = [
            [("uuid-123", "+2348012345678", "active", "basic", expires_at, None)],  # Get info
            [],  # Update
        ]

        service = SubscriptionService(db=mock_db)
        result = await service.cancel_subscription("+2348012345678")

        assert result["success"] is True
        assert result["expires_at"] == expires_at
        assert "cancelled" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_cancel_trial_user_fails(self):
        """Trial users have nothing to cancel."""
        mock_db = MagicMock()

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "trial", None, None, None)
        ]

        service = SubscriptionService(db=mock_db)
        result = await service.cancel_subscription("+2348012345678")

        assert result["success"] is False
        assert "trial" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled(self):
        """Already cancelled subscription returns success."""
        mock_db = MagicMock()
        expires_at = datetime.now(UTC) + timedelta(days=3)

        mock_db.execute_raw_sql.return_value = [
            ("uuid-123", "+2348012345678", "cancelled", "basic", expires_at, None)
        ]

        service = SubscriptionService(db=mock_db)
        result = await service.cancel_subscription("+2348012345678")

        assert result["success"] is True
        assert result.get("already_cancelled") is True


class TestCancellationTokens:
    """Tests for token generation and verification in the API."""

    def test_generate_cancellation_token(self):
        """Token generation produces valid format."""
        from sipap.api.subscription import generate_cancellation_token

        token = generate_cancellation_token("+2348012345678")

        assert "." in token
        parts = token.split(".")
        assert len(parts) == 2
        # First part should be numeric timestamp
        assert parts[0].isdigit()
        # Second part should be hex signature
        assert all(c in "0123456789abcdef" for c in parts[1])

    def test_verify_valid_token(self):
        """Valid token passes verification."""
        from sipap.api.subscription import (
            generate_cancellation_token,
            verify_cancellation_token,
        )

        user_id = "+2348012345678"
        token = generate_cancellation_token(user_id)

        assert verify_cancellation_token(user_id, token) is True

    def test_verify_wrong_user_fails(self):
        """Token for different user fails verification."""
        from sipap.api.subscription import (
            generate_cancellation_token,
            verify_cancellation_token,
        )

        token = generate_cancellation_token("+2348012345678")

        # Try to use with different user
        assert verify_cancellation_token("+2349999999999", token) is False

    def test_verify_tampered_token_fails(self):
        """Tampered token fails verification."""
        from sipap.api.subscription import (
            generate_cancellation_token,
            verify_cancellation_token,
        )

        user_id = "+2348012345678"
        token = generate_cancellation_token(user_id)

        # Tamper with token
        tampered = token[:-4] + "0000"

        assert verify_cancellation_token(user_id, tampered) is False

    def test_verify_expired_token_fails(self):
        """Expired token fails verification."""
        from sipap.api.subscription import (
            generate_cancellation_token,
            verify_cancellation_token,
            TOKEN_EXPIRY_SECONDS,
        )
        import time

        user_id = "+2348012345678"
        # Generate token with old timestamp
        old_timestamp = int(time.time()) - TOKEN_EXPIRY_SECONDS - 1
        token = generate_cancellation_token(user_id, timestamp=old_timestamp)

        assert verify_cancellation_token(user_id, token) is False

    def test_generate_cancellation_link(self):
        """Cancellation link is properly formatted."""
        from sipap.api.subscription import generate_cancellation_link

        user_id = "+2348012345678"
        link = generate_cancellation_link(user_id)

        assert "sipap.io" in link
        assert f"user_id={user_id}" in link
        assert "token=" in link
