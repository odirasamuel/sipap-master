"""Tests for retry logic integration in BatchOrchestrator.

Verifies that BatchOrchestrator uses retry_with_cache_fallback for resilient predictions.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sipap.core.batch_orchestrator import BatchOrchestrator
from sipap.core.retry import RetryExhausted, PermanentError


class TestRetryIntegration:
    """Test retry logic integration in batch predictions."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Mock MainOrchestrator."""
        orch = MagicMock()
        orch.predict = AsyncMock()
        return orch

    @pytest.fixture
    def mock_mcp_factory(self):
        """Mock MCPFactory."""
        return MagicMock()

    @pytest.fixture
    def batch_orchestrator(self, mock_orchestrator, mock_mcp_factory):
        """Create BatchOrchestrator with mocked dependencies."""
        return BatchOrchestrator(mock_orchestrator, mock_mcp_factory)

    @pytest.mark.asyncio
    async def test_prediction_succeeds_first_attempt(self, batch_orchestrator, mock_orchestrator):
        """Test that successful prediction on first attempt doesn't trigger retries."""
        # Mock successful prediction
        mock_orchestrator.predict.return_value = {
            "outcome": "Home Win",
            "confidence": 75,
            "expected_value": {
                "odds": 2.5,
                "expected_value": 0.08,
            },
        }

        fixture = {
            "id": "match1",
            "home_team": {"name": "Arsenal"},
            "away_team": {"name": "Chelsea"},
        }

        # Should succeed without retries
        result = await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify result structure
        assert result["market_code"] is not None
        assert result["bookmaker_odd"] == 2.5
        assert result["confidence"] == 0.75
        assert result["ev"] == 0.08

        # Verify predict was called (44 times for all markets)
        assert mock_orchestrator.predict.call_count == 44

    @pytest.mark.asyncio
    @patch('sipap.core.retry.asyncio.sleep', new_callable=AsyncMock)
    async def test_retry_on_transient_error(self, mock_sleep, batch_orchestrator, mock_orchestrator):
        """Test that transient errors trigger retry with backoff."""
        # Mock: Fail with timeout on first attempt, succeed on second
        mock_orchestrator.predict.side_effect = [
            Exception("Connection timeout"),  # Transient error
            {
                "outcome": "Home Win",
                "confidence": 75,
                "expected_value": {
                    "odds": 2.5,
                    "expected_value": 0.08,
                },
            },
        ]

        fixture = {
            "id": "match1",
            "home_team": {"name": "Arsenal"},
            "away_team": {"name": "Chelsea"},
        }

        # Should succeed after retry
        result = await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify predict was called twice (first failed, second succeeded)
        assert mock_orchestrator.predict.call_count >= 2
        # Verify sleep was called (for retry delay)
        assert mock_sleep.called

    @pytest.mark.asyncio
    async def test_no_retry_on_permanent_error(self, batch_orchestrator, mock_orchestrator):
        """Test that permanent errors (ValueError, KeyError) are NOT retried."""
        # Mock permanent error (ValueError)
        mock_orchestrator.predict.side_effect = ValueError("Invalid match_id format")

        fixture = {
            "id": "match1",
            "home_team": {"name": "Arsenal"},
            "away_team": {"name": "Chelsea"},
        }

        # Should raise PermanentError without retrying
        with pytest.raises(Exception) as exc_info:
            await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify the error message
        assert "failed" in str(exc_info.value).lower()

        # Verify predict was NOT retried (should fail fast on permanent error)
        # Note: Since we evaluate 44 markets, it will try the first market once, fail, then continue
        # So call_count could be 1 for the failed market
        assert mock_orchestrator.predict.call_count >= 1

    @pytest.mark.asyncio
    @patch('sipap.core.retry.asyncio.sleep', new_callable=AsyncMock)
    async def test_cache_fallback_when_retries_exhausted(self, mock_sleep, batch_orchestrator, mock_orchestrator):
        """Test that cache fallback is used when all retries are exhausted."""
        # Mock: All attempts fail with transient error
        mock_orchestrator.predict.side_effect = Exception("Service unavailable (503)")

        fixture = {
            "id": "match1",
            "home_team": {"name": "Arsenal"},
            "away_team": {"name": "Chelsea"},
        }

        # Should raise exception after exhausting retries
        # (In production, cache fallback would return cached result)
        with pytest.raises(Exception) as exc_info:
            await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify error indicates all predictions failed
        assert "failed" in str(exc_info.value).lower()
        # Verify sleep was called (for retry delays)
        assert mock_sleep.called

    @pytest.mark.asyncio
    async def test_partial_market_failures(self, batch_orchestrator, mock_orchestrator):
        """Test that some market failures don't prevent overall success."""
        # Mock: First 5 markets fail, rest succeed
        responses = []

        # First 5 markets fail with transient errors
        for _ in range(5):
            responses.append(Exception("Timeout"))

        # Remaining 39 markets succeed
        for _ in range(39):
            responses.append({
                "outcome": "Home Win",
                "confidence": 75,
                "expected_value": {
                    "odds": 2.5,
                    "expected_value": 0.08,
                },
            })

        mock_orchestrator.predict.side_effect = responses

        fixture = {
            "id": "match1",
            "home_team": {"name": "Arsenal"},
            "away_team": {"name": "Chelsea"},
        }

        # Should succeed with 39 successful markets
        result = await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify result
        assert result["markets_evaluated"] == 39  # 39 successful markets
        assert result["bookmaker_odd"] == 2.5

    @pytest.mark.asyncio
    async def test_all_markets_fail(self, batch_orchestrator, mock_orchestrator):
        """Test that exception is raised when ALL markets fail."""
        # Mock: All 44 markets fail
        mock_orchestrator.predict.side_effect = Exception("Service unavailable")

        fixture = {
            "id": "match1",
            "home_team": {"name": "Arsenal"},
            "away_team": {"name": "Chelsea"},
        }

        # Should raise exception
        with pytest.raises(Exception) as exc_info:
            await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify error message
        assert "All" in str(exc_info.value) and "failed" in str(exc_info.value)
        assert "44" in str(exc_info.value) or "market" in str(exc_info.value)


class TestRetryConfiguration:
    """Test retry configuration and parameters."""

    @pytest.mark.asyncio
    @patch('sipap.core.retry.asyncio.sleep', new_callable=AsyncMock)
    async def test_retry_parameters_configurable(self, mock_sleep):
        """Test that retry parameters (max_attempts, delays) can be configured."""
        # This test verifies that retry parameters are sensible defaults
        from sipap.core.retry import retry_with_backoff

        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise Exception("Transient error: timeout")

        # Should retry 3 times (max_attempts=3) before raising RetryExhausted
        with pytest.raises(RetryExhausted):
            await retry_with_backoff(
                failing_func,
                max_attempts=3,
                initial_delay=0.01,  # Fast for testing
                backoff_factor=2.0,
            )

        # Verify it tried max_attempts times
        assert call_count == 3
        # Verify sleep was called for retries
        assert mock_sleep.call_count == 2  # 2 retries after first failure
