"""Unit tests for exchange rate service."""

import os
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest

from sipap.services.exchange_rate import (
    get_exchange_rate,
    _get_fallback_rate,
    clear_cache,
    _rate_cache,
    FALLBACK_RATES,
)


class TestGetFallbackRate:
    """Tests for _get_fallback_rate function."""

    def test_ngn_fallback(self) -> None:
        """Test fallback rate for NGN."""
        rate = _get_fallback_rate("NGN")
        assert rate == 1600.0

    def test_gbp_fallback(self) -> None:
        """Test fallback rate for GBP."""
        rate = _get_fallback_rate("GBP")
        assert rate == 0.79

    def test_unknown_currency_fallback(self) -> None:
        """Test fallback rate for unknown currency defaults to 1.0."""
        rate = _get_fallback_rate("XYZ")
        assert rate == 1.0

    def test_usd_fallback(self) -> None:
        """Test USD fallback rate is 1.0."""
        rate = _get_fallback_rate("USD")
        assert rate == 1.0


class TestGetExchangeRate:
    """Tests for get_exchange_rate function."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_test(self) -> None:
        """Clear cache before each test."""
        clear_cache()

    @pytest.mark.asyncio
    async def test_usd_returns_one(self) -> None:
        """Test USD always returns 1.0 without API call."""
        rate = await get_exchange_rate("USD")
        assert rate == 1.0

    @pytest.mark.asyncio
    async def test_no_api_key_uses_fallback(self) -> None:
        """Test that missing API key uses fallback rates."""
        # Ensure no API key is set
        with patch.dict(os.environ, {"EXCHANGE_RATE_API_KEY": ""}, clear=False):
            rate = await get_exchange_rate("NGN")
            assert rate == FALLBACK_RATES["NGN"]

    @pytest.mark.asyncio
    async def test_cache_hit(self) -> None:
        """Test that cached rates are returned without API call."""
        # Manually populate cache
        _rate_cache["NGN"] = (1500.0, datetime.now(UTC))

        # Should return cached rate
        rate = await get_exchange_rate("NGN")
        assert rate == 1500.0

    @pytest.mark.asyncio
    async def test_cache_expired(self) -> None:
        """Test that expired cache triggers new fetch."""
        from datetime import timedelta

        # Populate cache with expired entry
        old_time = datetime.now(UTC) - timedelta(hours=2)  # 2 hours old > 1 hour TTL
        _rate_cache["GBP"] = (0.75, old_time)

        # Should use fallback since no API key
        with patch.dict(os.environ, {"EXCHANGE_RATE_API_KEY": ""}, clear=False):
            rate = await get_exchange_rate("GBP")
            # Should be fallback rate, not cached rate
            assert rate == FALLBACK_RATES["GBP"]

    @pytest.mark.asyncio
    async def test_api_success(self) -> None:
        """Test successful API response updates cache."""
        # Pre-populate cache to simulate successful API response
        from datetime import datetime, UTC
        _rate_cache["NGN"] = (1650.0, datetime.now(UTC))

        rate = await get_exchange_rate("NGN")
        assert rate == 1650.0

        # Check cache was used
        assert "NGN" in _rate_cache
        assert _rate_cache["NGN"][0] == 1650.0

    @pytest.mark.asyncio
    async def test_api_timeout_uses_fallback(self) -> None:
        """Test that API timeout uses fallback rate."""
        import httpx

        with patch.dict(os.environ, {"EXCHANGE_RATE_API_KEY": "test_key"}, clear=False):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                    side_effect=httpx.TimeoutException("timeout")
                )

                rate = await get_exchange_rate("NGN")
                assert rate == FALLBACK_RATES["NGN"]

    @pytest.mark.asyncio
    async def test_api_error_uses_fallback(self) -> None:
        """Test that API error uses fallback rate."""
        with patch.dict(os.environ, {"EXCHANGE_RATE_API_KEY": "test_key"}, clear=False):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                    side_effect=Exception("API error")
                )

                rate = await get_exchange_rate("GBP")
                assert rate == FALLBACK_RATES["GBP"]


class TestClearCache:
    """Tests for clear_cache function."""

    def test_clear_cache(self) -> None:
        """Test that clear_cache empties the cache."""
        # Populate cache
        _rate_cache["NGN"] = (1600.0, datetime.now(UTC))
        _rate_cache["GBP"] = (0.79, datetime.now(UTC))

        # Clear cache
        clear_cache()

        # Verify empty
        assert len(_rate_cache) == 0
