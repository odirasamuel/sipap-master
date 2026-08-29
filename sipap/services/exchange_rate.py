"""Exchange rate service using ExchangeRate-API.

Provides realtime currency conversion for subscription pricing.
Uses ExchangeRate-API free tier (1500 requests/month) with 1-hour caching
to minimize API calls.

Example:
    >>> rate = await get_exchange_rate("NGN")
    >>> price_ngn = 2.00 * rate  # Convert $2 to NGN
"""

import os
from datetime import datetime, UTC

import httpx

from sipap_common.logging import get_logger


logger = get_logger(__name__)


# ExchangeRate-API free tier: 1500 requests/month
# https://www.exchangerate-api.com/
EXCHANGE_RATE_API_URL = "https://v6.exchangerate-api.com/v6/{api_key}/latest/USD"

# Cache exchange rates for 1 hour to reduce API calls
_rate_cache: dict[str, tuple[float, datetime]] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


# Fallback rates if API unavailable (approximate, updated periodically)
FALLBACK_RATES: dict[str, float] = {
    "NGN": 1600.0,   # ~1600 NGN per USD
    "GBP": 0.79,     # ~0.79 GBP per USD
    "EUR": 0.92,     # ~0.92 EUR per USD
    "ZAR": 18.0,     # ~18 ZAR per USD
    "KES": 130.0,    # ~130 KES per USD
    "GHS": 15.0,     # ~15 GHS per USD
    "USD": 1.0,      # Base currency
}


def _get_fallback_rate(currency: str) -> float:
    """Get fallback rate if API unavailable.

    Args:
        currency: Target currency code (e.g., "NGN")

    Returns:
        Approximate exchange rate (1 USD = X currency)
    """
    return FALLBACK_RATES.get(currency, 1.0)


async def get_exchange_rate(target_currency: str) -> float:
    """Get exchange rate from USD to target currency.

    Uses ExchangeRate-API with caching to minimize API calls.
    Falls back to approximate rates if API fails.

    Args:
        target_currency: Target currency code (e.g., "NGN", "GBP")

    Returns:
        Exchange rate (1 USD = X target_currency)

    Example:
        >>> rate = await get_exchange_rate("NGN")
        >>> print(f"1 USD = {rate} NGN")
    """
    if target_currency == "USD":
        return 1.0

    # Check cache first
    now = datetime.now(UTC)
    if target_currency in _rate_cache:
        rate, cached_at = _rate_cache[target_currency]
        age_seconds = (now - cached_at).total_seconds()
        if age_seconds < CACHE_TTL_SECONDS:
            logger.debug(f"Cache hit for {target_currency}: {rate} (age: {age_seconds:.0f}s)")
            return rate

    # Get API key
    api_key = os.environ.get("EXCHANGE_RATE_API_KEY", "")
    if not api_key:
        logger.warning("EXCHANGE_RATE_API_KEY not set - using fallback rates")
        return _get_fallback_rate(target_currency)

    # Fetch from API
    try:
        async with httpx.AsyncClient() as client:
            url = EXCHANGE_RATE_API_URL.format(api_key=api_key)
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            data = response.json()

            if data.get("result") == "success":
                rates = data.get("conversion_rates", {})
                rate = rates.get(target_currency)

                if rate is not None:
                    # Cache the rate
                    _rate_cache[target_currency] = (rate, now)
                    logger.info(f"Fetched exchange rate: 1 USD = {rate} {target_currency}")
                    return rate
                else:
                    logger.warning(f"Currency {target_currency} not found in API response")
            else:
                error_type = data.get("error-type", "unknown")
                logger.error(f"ExchangeRate-API error: {error_type}")

    except httpx.TimeoutException:
        logger.warning(f"ExchangeRate-API timeout - using fallback for {target_currency}")
    except httpx.HTTPStatusError as e:
        logger.error(f"ExchangeRate-API HTTP error: {e.response.status_code}")
    except Exception as e:
        logger.error(f"ExchangeRate-API error: {e}")

    # Fall back to approximate rates
    fallback = _get_fallback_rate(target_currency)
    logger.info(f"Using fallback rate for {target_currency}: {fallback}")
    return fallback


def clear_cache() -> None:
    """Clear the exchange rate cache.

    Useful for testing or forcing a refresh.
    """
    _rate_cache.clear()
    logger.info("Exchange rate cache cleared")
