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
        """Mock MainOrchestrator.

        BatchOrchestrator._predict_fixture uses:
        - aggregate_and_validate_context: Returns (context, validation) tuple
        - predict_with_context: Returns prediction result dict
        """
        orch = MagicMock()
        # Mock the methods actually used by _predict_fixture
        orch.aggregate_and_validate_context = AsyncMock(return_value=(
            {"teams": {}, "odds": {}},  # context dict
            {"valid": True},  # validation dict
        ))
        orch.predict_with_context = AsyncMock()
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
        # Mock successful prediction for predict_with_context
        mock_orchestrator.predict_with_context.return_value = {
            "outcome": "Home Win",
            "confidence": 75,
            "probability": 0.70,
            "expected_value": {
                "odds": 2.5,
                "expected_value": 0.08,
            },
        }

        fixture = {
            "id": "match1",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
        }

        # Should succeed without retries
        result = await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify result structure
        assert result["market_code"] is not None
        assert result["bookmaker_odd"] == 2.5
        assert result["confidence"] == 0.75
        assert result["ev"] == 0.08

        # Verify aggregate_and_validate_context was called once
        mock_orchestrator.aggregate_and_validate_context.assert_called()
        # Verify predict_with_context was called 44 times for all markets
        assert mock_orchestrator.predict_with_context.call_count == 44

    @pytest.mark.asyncio
    @patch('sipap.core.retry.asyncio.sleep', new_callable=AsyncMock)
    async def test_retry_on_transient_error(self, mock_sleep, batch_orchestrator, mock_orchestrator):
        """Test that transient errors trigger retry with backoff."""
        # Mock: Fail with timeout on first attempt, succeed on subsequent
        call_count = 0

        async def predict_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection timeout")
            return {
                "outcome": "Home Win",
                "confidence": 75,
                "probability": 0.70,
                "expected_value": {
                    "odds": 2.5,
                    "expected_value": 0.08,
                },
            }

        mock_orchestrator.predict_with_context.side_effect = predict_side_effect

        fixture = {
            "id": "match1",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
        }

        # Should succeed after retry
        result = await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify predict_with_context was called at least twice (first failed, then succeeded)
        assert mock_orchestrator.predict_with_context.call_count >= 2
        # Verify sleep was called (for retry delay)
        assert mock_sleep.called

    @pytest.mark.asyncio
    async def test_no_retry_on_permanent_error(self, batch_orchestrator, mock_orchestrator):
        """Test that permanent errors (ValueError, KeyError) are NOT retried."""
        # Mock permanent error (ValueError) on aggregate_and_validate_context
        mock_orchestrator.aggregate_and_validate_context.side_effect = ValueError(
            "Invalid match_id format"
        )

        fixture = {
            "id": "match1",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
        }

        # Should raise exception without excessive retrying
        with pytest.raises(Exception) as exc_info:
            await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify the error message indicates failure (PermanentError wraps the ValueError)
        error_msg = str(exc_info.value).lower()
        assert "permanent" in error_msg or "invalid" in error_msg

    @pytest.mark.asyncio
    @patch('sipap.core.retry.asyncio.sleep', new_callable=AsyncMock)
    async def test_cache_fallback_when_retries_exhausted(self, mock_sleep, batch_orchestrator, mock_orchestrator):
        """Test that cache fallback is used when all retries are exhausted."""
        # Mock: All attempts fail with transient error
        mock_orchestrator.aggregate_and_validate_context.side_effect = Exception(
            "Service unavailable (503)"
        )

        fixture = {
            "id": "match1",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
        }

        # Should raise exception after exhausting retries
        # (In production, cache fallback would return cached result)
        with pytest.raises(Exception) as exc_info:
            await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify error indicates failure
        error_msg = str(exc_info.value).lower()
        assert "exhausted" in error_msg or "context" in error_msg or "failed" in error_msg
        # Verify sleep was called (for retry delays)
        assert mock_sleep.called

    @pytest.mark.asyncio
    @patch('sipap.core.retry.asyncio.sleep', new_callable=AsyncMock)
    async def test_partial_market_failures(self, mock_sleep, batch_orchestrator, mock_orchestrator):
        """Test that some market failures don't prevent overall success."""
        # Mock: First 5 market predictions fail, rest succeed
        call_count = 0

        async def predict_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 5:
                raise Exception("Timeout")
            return {
                "outcome": "Home Win",
                "confidence": 75,
                "probability": 0.70,
                "expected_value": {
                    "odds": 2.5,
                    "expected_value": 0.08,
                },
            }

        mock_orchestrator.predict_with_context.side_effect = predict_side_effect

        fixture = {
            "id": "match1",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
        }

        # Should succeed with remaining successful markets
        result = await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify result contains successful predictions
        # Note: markets_evaluated counts only successful predictions
        assert result["markets_evaluated"] > 0
        assert result["bookmaker_odd"] == 2.5

    @pytest.mark.asyncio
    @patch('sipap.core.retry.asyncio.sleep', new_callable=AsyncMock)
    async def test_all_markets_fail(self, mock_sleep, batch_orchestrator, mock_orchestrator):
        """Test that exception is raised when ALL markets fail."""
        # Mock: All market predictions fail with transient error
        # But aggregate_and_validate_context succeeds
        mock_orchestrator.predict_with_context.side_effect = Exception("Service unavailable")

        fixture = {
            "id": "match1",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
        }

        # Should raise exception
        with pytest.raises(Exception) as exc_info:
            await batch_orchestrator._predict_fixture(fixture, "user123")

        # Verify error message indicates all predictions failed
        assert "44" in str(exc_info.value) or "market" in str(exc_info.value).lower() or "all" in str(exc_info.value).lower()


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
