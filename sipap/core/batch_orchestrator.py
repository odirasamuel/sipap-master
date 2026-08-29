"""Batch Orchestrator for accumulated odds predictions.

Handles batch prediction requests where users want accumulated bookmaker odds
(e.g., "I need 20 odds") by analyzing fixtures iteratively until target is reached.

CRITICAL BUSINESS LOGIC:
In sports betting, "X odds" means ACCUMULATED ODDS (sum of bookmaker odds per fixture).
NOT number of matches!

Example: "20 odds" means accumulate fixtures until sum(bookmaker_odds) >= 20.0
- Arsenal vs Chelsea - Home Win - 2.5 odds
- Barcelona vs Madrid - BTTS Yes - 3.0 odds
- Bayern vs Dortmund - Over 2.5 - 14.5 odds
- Total: 2.5 + 3.0 + 14.5 = 20.0 ✅

Pattern adapted from Sentinel's batch processing patterns.
"""

import asyncio
import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sipap_common.cache.redis_adapter import RedisCache
from sipap_common.logging import get_logger

from sipap.conversation import RequestIntent
from sipap.core.retry import PermanentError, RetryExhausted, retry_with_backoff
from sipap.sports.soccer.markets import get_all_markets


class BatchOrchestrator:
    """
    Orchestrates batch prediction requests with accumulated odds logic.

    BATCH PROCESSING (NEW):
    - Processes fixtures in batches of 20 at a time for efficiency
    - Evaluates all 44 markets per fixture
    - Returns TOP 3 markets per fixture, with #1 highlighted as best option
    - Caches results for 24 hours to avoid redundant predictions

    Responsibilities:
    - Query fixtures with filters (leagues, dates, status)
    - Process in batches of 20 matches for optimal throughput
    - Evaluate all 44 markets and select top 3 by probability
    - Apply quality gates (confidence + EV thresholds)
    - Cache results for 24 hours
    - Return selections with accumulated_sum >= target

    Example:
        >>> orchestrator = BatchOrchestrator(main_orch, mcp_factory, logger)
        >>> intent = RequestIntent(
        ...     intent_type="batch_prediction",
        ...     target_odds=20.0,
        ...     accumulation_mode=True,
        ...     quality_threshold="highest"
        ... )
        >>> result = await orchestrator.process_batch_request(intent, "user_id")
        >>> print(result["accumulated_odds"])
        20.3  # >= 20.0
        >>> print(len(result["selections"]))
        7  # 7 fixtures accumulated to 20.3 odds
    """

    def __init__(
        self,
        main_orchestrator: Any,
        mcp_factory: Any,
        logger: logging.Logger | None = None,
    ):
        """
        Initialize batch orchestrator.

        Args:
            main_orchestrator: MainOrchestrator instance for predictions
            mcp_factory: MCPFactory for data queries
            logger: Optional logger instance
        """
        self.orchestrator = main_orchestrator
        self.mcp_factory = mcp_factory
        self.logger = logger or get_logger(__name__)

        # Batch processing configuration
        self.BATCH_SIZE = 20  # Process 20 matches at a time
        self.TOP_MARKETS = 3  # Return top 3 markets per fixture
        self.CACHE_TTL_HOURS = 24  # Cache predictions for 24 hours

        # Sequential processing with delay between fixtures
        # This prevents Lambda rate limiting (429 errors) by processing one fixture at a time
        self.INTER_REQUEST_DELAY = 0.5  # 500ms delay between fixtures to prevent bursts

        # Quality threshold mappings
        # These map user quality terms to confidence + EV thresholds
        self.quality_thresholds = {
            "highest": {"min_confidence": 0.70, "min_ev": 0.10},  # Sure odds
            "high": {"min_confidence": 0.60, "min_ev": 0.05},  # Best possible
            "medium": {"min_confidence": 0.55, "min_ev": 0.00},  # Decent
        }

        # Initialize Redis cache for fixture evaluations
        # Cache expires at end of day (predictions stay valid for current day only)
        redis_host = os.environ.get("REDIS_HOST", "localhost")
        redis_port = int(os.environ.get("REDIS_PORT", "6379"))
        redis_password = os.environ.get("REDIS_PASSWORD", None)

        try:
            self.cache = RedisCache(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                default_ttl=3600,  # 1 hour default (actual TTL calculated per-day)
            )
            self.cache_enabled = True
            self.logger.info(
                f"Redis cache initialized for fixture evaluations (host: {redis_host}:{redis_port})"
            )
        except Exception as e:
            self.logger.warning(
                f"Failed to initialize Redis cache - predictions will not be cached: {e}"
            )
            self.cache = None
            self.cache_enabled = False

        # Check if DEBUG logging is enabled
        self.debug_enabled = self.logger.isEnabledFor(logging.DEBUG)

        log_mode = "DEBUG mode enabled" if self.debug_enabled else "INFO mode (summary only)"
        self.logger.info(f"BatchOrchestrator initialized - {log_mode}")

    def _calculate_ttl_24_hours(self) -> int:
        """
        Calculate TTL for 24-hour caching of prediction results.

        This ensures predictions are cached for exactly 24 hours, allowing
        subsequent requests within that window to reuse cached results.

        Returns:
            86400 seconds (24 hours)

        Examples:
            >>> ttl = self._calculate_ttl_24_hours()
            >>> # Returns 86400 (24 hours in seconds)
        """
        # 24 hours = 24 * 60 * 60 = 86400 seconds
        return self.CACHE_TTL_HOURS * 60 * 60

    def _calculate_ttl_until_end_of_day(self) -> int:
        """
        Calculate TTL in seconds until end of current day (midnight UTC).

        DEPRECATED: Use _calculate_ttl_24_hours() instead for 24-hour caching.

        Returns:
            Number of seconds until 23:59:59 UTC today

        Examples:
            >>> # At 2026-08-13 14:30:00 UTC
            >>> ttl = self._calculate_ttl_until_end_of_day()
            >>> # Returns ~34,200 seconds (9.5 hours remaining in day)
        """
        now = datetime.now(UTC)
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        ttl_seconds = int((end_of_day - now).total_seconds())

        # Ensure TTL is at least 60 seconds (avoid 0 or negative TTL)
        return max(ttl_seconds, 60)

    def clear_prediction_cache(self, target_date: str | None = None) -> int:
        """
        Clear all prediction cache entries for a specific date (or today).

        This is useful for clearing invalid cached predictions that have
        Unknown outcomes or 0.0 probability values.

        Args:
            target_date: Date to clear in YYYY-MM-DD format (default: today)

        Returns:
            Number of cache entries deleted

        Example:
            >>> orchestrator.clear_prediction_cache()  # Clear today's cache
            >>> orchestrator.clear_prediction_cache("2026-08-18")  # Clear specific date
        """
        if not self.cache_enabled or self.cache is None:
            self.logger.warning("Cache is not enabled - nothing to clear")
            return 0

        if target_date is None:
            target_date = date.today().isoformat()

        # Redis SCAN to find all prediction keys for this date
        # Pattern: prediction:*:*:{date}
        pattern = f"prediction:*:*:{target_date}"

        try:
            # Get Redis client from cache adapter
            redis_client = self.cache._client
            deleted_count = 0

            # Use SCAN to find matching keys (safe for production)
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted_count += redis_client.delete(*keys)
                    self.logger.info(f"Deleted {len(keys)} cache entries matching {pattern}")
                if cursor == 0:
                    break

            self.logger.info(
                f"🗑️ Cleared {deleted_count} prediction cache entries for {target_date}"
            )
            return deleted_count

        except Exception as e:
            self.logger.error(f"Failed to clear prediction cache: {e}", exc_info=True)
            return 0

    async def _process_fixture_batch(
        self,
        fixtures: list[dict[str, Any]],
        user_id: str,
        thresholds: dict[str, float],
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Process a batch of fixtures SEQUENTIALLY (one at a time).

        CHANGED: Now processes fixtures one at a time to prevent Lambda rate limiting.
        Each fixture gets fully evaluated (all 44 markets) before moving to the next.
        This is slower but more reliable and prevents 429 errors.

        Args:
            fixtures: List of fixture dictionaries to process
            user_id: User identifier
            thresholds: Quality thresholds for confidence and EV

        Returns:
            Tuple of (accepted_selections, failed_count)
            - accepted_selections: Fixtures that passed quality gates with top 3 markets
            - failed_count: Number of fixtures that failed prediction

        Example:
            >>> selections, failures = await self._process_fixture_batch(
            ...     fixtures[:20], user_id, thresholds
            ... )
            >>> print(f"Accepted: {len(selections)}, Failed: {failures}")
        """
        if not fixtures:
            return [], 0

        self.logger.info(
            f"🔄 Processing batch of {len(fixtures)} fixtures SEQUENTIALLY "
            f"({self.INTER_REQUEST_DELAY}s delay between fixtures)"
        )

        # Process each fixture SEQUENTIALLY and collect results
        accepted: list[dict[str, Any]] = []
        failed_count = 0

        for i, fixture in enumerate(fixtures):
            fixture_num = i + 1
            home_team = fixture.get("home_team", "Unknown")
            away_team = fixture.get("away_team", "Unknown")

            self.logger.info(
                f"📊 [{fixture_num}/{len(fixtures)}] Evaluating: {home_team} vs {away_team}"
            )

            # NOTE: We no longer skip fixtures without database odds
            # Odds are fetched from API-Football during context aggregation
            # This allows us to evaluate ALL fixtures regardless of database odds status

            try:
                # Add delay between fixtures to prevent rate limiting
                if i > 0:
                    await asyncio.sleep(self.INTER_REQUEST_DELAY)

                # Evaluate this fixture (all 44 markets)
                analysis = await self._predict_fixture(fixture, user_id)

                # Apply quality gates using the BEST market
                # CRITICAL: Selection is based on PROBABILITY, not EV
                # Markets are selected if confidence meets threshold - odds are optional
                best_market = analysis.get("best_market", {})
                confidence = best_market.get("confidence", analysis.get("confidence", 0))
                probability = best_market.get("probability", analysis.get("probability", 0))
                market_code = best_market.get("market_code", "?")
                outcome = best_market.get("best_outcome", "?")
                bookmaker_odd = best_market.get("bookmaker_odd", 0)

                # Quality gate: ONLY check confidence (probability-based)
                # EV is informational only - NOT used for selection criteria
                if confidence >= thresholds["min_confidence"]:
                    accepted.append(analysis)
                    odds_info = f"@ {bookmaker_odd}" if bookmaker_odd > 0 else "(no odds)"
                    self.logger.info(
                        f"   ✅ ACCEPTED: {market_code} → {outcome} {odds_info} "
                        f"(prob={probability:.2f}, conf={confidence:.2f})"
                    )
                else:
                    self.logger.info(
                        f"   ❌ REJECTED: {market_code} → {outcome} "
                        f"(conf={confidence:.2f} < {thresholds['min_confidence']})"
                    )

            except Exception as e:
                self.logger.error(
                    f"   ❌ FAILED: {e}",
                    exc_info=False,  # Don't log full traceback for each fixture
                )
                failed_count += 1

        self.logger.info(
            f"✅ Batch complete: {len(accepted)} accepted, "
            f"{len(fixtures) - len(accepted) - failed_count} rejected, "
            f"{failed_count} failed"
        )

        return accepted, failed_count

    async def process_batch_request(
        self,
        intent: RequestIntent,
        user_id: str,
    ) -> dict[str, Any]:
        """
        Process batch prediction request with accumulated odds logic.

        Flow:
        1. Query fixtures with filters (leagues, dates)
        2. Predict iteratively until accumulated >= target
        3. Apply quality gates (confidence, EV)
        4. Return selections with accumulated total

        Args:
            intent: Parsed user intent with target_odds and filters
            user_id: User identifier

        Returns:
            {
                "accumulated_odds": 20.3,  # Total accumulated
                "target_odds": 20.0,       # User's target
                "selections": [
                    {
                        "fixture": {...},
                        "market_code": "BTTS",  # Selected market code
                        "market_name": "Both Teams To Score",  # Human-readable name
                        "best_outcome": "Yes",  # Best outcome for selected market
                        "bookmaker_odd": 2.5,
                        "confidence": 0.75,
                        "ev": 0.08,
                        "markets_evaluated": 44,  # Number of markets evaluated
                    },
                    ...
                ],
                "filters_applied": {...},
                "warning": None,  # Or warning message if target not reached
                "error": None,    # Or error message if failed
            }

        Example:
            >>> intent = RequestIntent(
            ...     intent_type="batch_prediction",
            ...     target_odds=20.0,
            ...     quality_threshold="highest"
            ... )
            >>> result = await orchestrator.process_batch_request(intent, "user_id")
            >>> print(f"Accumulated {result['accumulated_odds']} odds from {len(result['selections'])} fixtures")
            "Accumulated 20.3 odds from 7 fixtures"
        """
        self.logger.info(
            "Processing batch prediction request",
            extra={
                "user_id": user_id,
                "target_odds": intent.target_odds,
                "quality_threshold": intent.quality_threshold,
                "leagues": intent.leagues,
                "date_range": intent.date_range,
                "markets": intent.markets,  # NEW: Log market filter if present
            },
        )

        # NEW: Check for market-filtered request
        # If user specified specific markets (e.g., "BTTS picks", "1X2 selections"),
        # route to get_filtered_fixtures() for targeted market evaluation
        if intent.markets:
            self.logger.info(
                f"Market-filtered request detected: {intent.markets}. "
                "Routing to get_filtered_fixtures for targeted evaluation."
            )
            return await self._process_market_filtered_request(intent, user_id)

        # Step 0: Warm up MCP servers (trigger Lambda cold starts)
        # This prevents circuit breaker trips from cold start timeouts
        try:
            warmup_status = await self.mcp_factory.warmup(
                server_names=["data", "intelligence"],
                timeout=15.0,  # 15 seconds for cold start
            )
            if not all(warmup_status.values()):
                failed = [k for k, v in warmup_status.items() if not v]
                self.logger.warning(f"Some MCPs failed warmup: {failed}")
        except Exception as e:
            self.logger.warning(f"MCP warmup failed (continuing anyway): {e}")

        # Step 1: Validate and set defaults
        target = intent.target_odds or 20.0  # Default to 20 odds
        quality_threshold = intent.quality_threshold or "high"
        thresholds = self.quality_thresholds.get(
            quality_threshold, self.quality_thresholds["high"]
        )

        # Step 2: Incremental date expansion if no date range specified
        # Start with today, expand day-by-day until target odds reached
        if intent.date_range is None:
            self.logger.info(
                "No date range specified - using incremental expansion starting from today"
            )
            # Convert LeagueEntity objects to league names (strings)
            league_names_for_expansion = [league.name for league in intent.leagues] if intent.leagues else None
            result = await self._process_with_incremental_expansion(
                user_id=user_id,
                target=target,
                quality_threshold=quality_threshold,
                thresholds=thresholds,
                leagues=league_names_for_expansion,
                max_days=7,  # Maximum 7 days expansion
            )
            return result

        # Step 2 (fallback): Query fixtures with explicit date range
        # Convert LeagueEntity objects to league names (strings)
        league_names = [league.name for league in intent.leagues] if intent.leagues else None
        try:
            fixtures = await self._get_filtered_matches(
                leagues=league_names,
                date_range=intent.date_range,
                limit=100,  # Over-fetch for filtering
            )
        except Exception as e:
            self.logger.error(f"Failed to query fixtures: {e}", exc_info=True)
            return {
                "accumulated_odds": 0.0,
                "target_odds": target,
                "selections": [],
                "filters_applied": {
                    "leagues": intent.leagues,
                    "date_range": intent.date_range,
                    "quality_threshold": quality_threshold,
                },
                "warning": None,
                "error": f"Failed to query fixtures: {str(e)}",
            }

        if not fixtures:
            return {
                "accumulated_odds": 0.0,
                "target_odds": target,
                "selections": [],
                "filters_applied": {
                    "leagues": intent.leagues,
                    "date_range": intent.date_range,
                    "quality_threshold": quality_threshold,
                },
                "warning": None,
                "error": "No fixtures found matching your criteria",
            }

        self.logger.info(f"Found {len(fixtures)} fixtures matching filters")

        # Step 3: Process fixtures in BATCHES OF 20 for efficiency
        # NOTE: Market selection happens INSIDE _predict_fixture now
        # The system evaluates ALL markets and picks top 3 per fixture
        accumulated_sum = 0.0
        selections = []
        failed_predictions = 0
        batch_number = 0

        # Process in batches of BATCH_SIZE (20 by default)
        for i in range(0, len(fixtures), self.BATCH_SIZE):
            batch_number += 1
            batch = fixtures[i:i + self.BATCH_SIZE]

            self.logger.info(
                f"📦 Processing batch {batch_number} ({len(batch)} fixtures, "
                f"accumulated: {accumulated_sum:.1f}/{target})"
            )

            # Process this batch concurrently
            batch_selections, batch_failures = await self._process_fixture_batch(
                batch, user_id, thresholds
            )

            failed_predictions += batch_failures

            # Add accepted selections and accumulate odds
            for analysis in batch_selections:
                # Use the best market's bookmaker odd for accumulation
                best_market = analysis.get("best_market", {})
                bookmaker_odd = best_market.get("bookmaker_odd", analysis.get("bookmaker_odd", 0))

                selections.append(analysis)
                accumulated_sum += bookmaker_odd

                self.logger.info(
                    f"✅ Added: {analysis['fixture'].get('home_team')} vs {analysis['fixture'].get('away_team')} - "
                    f"{best_market.get('market_code', analysis.get('market_code'))} @ {bookmaker_odd} "
                    f"(accumulated: {accumulated_sum:.1f}/{target})"
                )

                # Stop if target reached
                if accumulated_sum >= target:
                    self.logger.info(
                        f"🎯 Target reached! {accumulated_sum:.1f} >= {target} "
                        f"after {batch_number} batch(es)"
                    )
                    break

            # Stop processing more batches if target reached
            if accumulated_sum >= target:
                break

        # Step 5: Build result
        warning = None
        if accumulated_sum < target:
            warning = (
                f"Only accumulated {accumulated_sum:.1f} odds (target: {target}). "
                f"Not enough fixtures met your quality criteria "
                f"(confidence >= {thresholds['min_confidence']:.0%})."
            )

        if failed_predictions > 0:
            failures_msg = f"{failed_predictions} prediction(s) failed."
            warning = f"{warning} {failures_msg}" if warning else failures_msg

        result = {
            "accumulated_odds": accumulated_sum,
            "target_odds": target,
            "selections": selections,
            "filters_applied": {
                "leagues": intent.leagues,
                "date_range": intent.date_range,
                "quality_threshold": quality_threshold,
                "thresholds": thresholds,
            },
            "warning": warning,
            "error": None,
        }

        self.logger.info(
            "Batch prediction complete",
            extra={
                "user_id": user_id,
                "accumulated_odds": accumulated_sum,
                "target_odds": target,
                "num_selections": len(selections),
                "fixtures_evaluated": len(fixtures),
                "failed_predictions": failed_predictions,
            },
        )

        return result

    async def _process_market_filtered_request(
        self,
        intent: RequestIntent,
        user_id: str,
    ) -> dict[str, Any]:
        """
        Process market-filtered prediction request.

        When user specifies specific markets (e.g., "BTTS picks", "1X2 and DC selections"),
        route to SoccerOrchestrator.get_filtered_fixtures() for targeted market evaluation.

        Args:
            intent: Parsed user intent with markets specified
            user_id: User identifier

        Returns:
            Dictionary with market-filtered selections:
            {
                "market_codes": ["BTTS"],
                "total_fixtures": 45,
                "selection_count": 10,
                "selections": [...],
                "filters_applied": {...},
                "warning": None,
                "error": None,
            }

        Example:
            >>> intent = RequestIntent(
            ...     intent_type="batch_prediction",
            ...     markets=["BTTS", "OU2.5"],
            ...     quality_threshold="highest"
            ... )
            >>> result = await orchestrator._process_market_filtered_request(intent, "user_id")
            >>> print(result["selections"][0]["market_code"])
            "BTTS"  # Only BTTS or OU2.5 markets in selections
        """
        # Get soccer orchestrator from main orchestrator
        soccer_orchestrator = self.orchestrator._orchestrators.get("soccer")
        if not soccer_orchestrator:
            self.logger.error("SoccerOrchestrator not available")
            return {
                "market_codes": intent.markets,
                "total_fixtures": 0,
                "selection_count": 0,
                "selections": [],
                "filters_applied": {
                    "markets": intent.markets,
                    "leagues": intent.leagues,
                    "date_range": intent.date_range,
                },
                "warning": None,
                "error": "Soccer orchestrator not available",
            }

        # Determine parameters
        quality_threshold = intent.quality_threshold or "high"
        thresholds = self.quality_thresholds.get(
            quality_threshold, self.quality_thresholds["high"]
        )
        min_probability = thresholds["min_confidence"]

        # Determine top_n from intent
        top_n = intent.num_matches or 10  # Default to 10 selections

        # Get league IDs if leagues specified
        league_ids = None
        if intent.leagues:
            league_ids = [league.id for league in intent.leagues]

        # Determine date
        date_str = None
        if intent.date_range:
            date_str = intent.date_range.get("start")

        self.logger.info(
            f"Calling get_filtered_fixtures with markets={intent.markets}, "
            f"top_n={top_n}, min_probability={min_probability}, league_ids={league_ids}"
        )

        try:
            result = await soccer_orchestrator.get_filtered_fixtures(
                market_codes=intent.markets,
                top_n=top_n,
                date=date_str,
                min_probability=min_probability,
                league_ids=league_ids,
            )

            # Add quality metadata
            result["filters_applied"]["quality_threshold"] = quality_threshold
            result["filters_applied"]["thresholds"] = thresholds
            result["warning"] = None
            result["error"] = None

            # Calculate accumulated_odds from selections (required by _handle_batch_prediction)
            accumulated_odds = 1.0
            for selection in result.get("selections", []):
                odds = selection.get("odds", 1.0)
                if odds and odds > 1.0:
                    accumulated_odds *= odds
            result["accumulated_odds"] = round(accumulated_odds, 2)
            result["target_odds"] = intent.target_odds or 20.0

            self.logger.info(
                f"Market-filtered request complete: {result['selection_count']} "
                f"selections from {result['total_fixtures']} fixtures "
                f"(accumulated_odds: {result['accumulated_odds']:.2f})",
                extra={
                    "user_id": user_id,
                    "market_codes": intent.markets,
                    "selection_count": result["selection_count"],
                    "accumulated_odds": result["accumulated_odds"],
                },
            )

            return result

        except Exception as e:
            self.logger.error(f"Market-filtered request failed: {e}", exc_info=True)
            return {
                "market_codes": intent.markets,
                "total_fixtures": 0,
                "selection_count": 0,
                "selections": [],
                "accumulated_odds": 0.0,
                "target_odds": intent.target_odds or 20.0,
                "filters_applied": {
                    "markets": intent.markets,
                    "leagues": intent.leagues,
                    "date_range": intent.date_range,
                    "quality_threshold": quality_threshold,
                },
                "warning": None,
                "error": str(e),
            }

    async def _process_with_incremental_expansion(
        self,
        user_id: str,
        target: float,
        quality_threshold: str,
        thresholds: dict[str, float],
        leagues: list[str] | None,
        max_days: int = 7,
    ) -> dict[str, Any]:
        """
        Process batch prediction with incremental date range expansion.

        Starts with today only, then expands day-by-day until target odds reached
        or max_days limit hit.

        Strategy:
        1. Start with today (day 0)
        2. Query fixtures, predict, accumulate
        3. If target not reached, expand to today + 1 day
        4. Query NEW day's fixtures only, predict, accumulate
        5. Repeat until target reached or max_days hit

        Args:
            user_id: User identifier
            target: Target accumulated odds
            quality_threshold: Quality level ("highest", "high", "medium")
            thresholds: Quality gate thresholds
            leagues: Optional league filters
            max_days: Maximum days to expand (default: 7)

        Returns:
            Batch prediction result with accumulated odds and selections
        """
        today = date.today()
        accumulated_sum = 0.0
        selections = []
        failed_predictions = 0
        days_expanded = 0
        all_fixtures_processed = set()  # Track fixture IDs to avoid duplicates

        self.logger.info(
            f"Starting incremental expansion from today ({today.isoformat()}) "
            f"until {target} odds accumulated (max {max_days} days)"
        )

        # Expand day by day until target reached or max_days hit
        for day_offset in range(max_days):
            current_date = today + timedelta(days=day_offset)
            date_range = {
                "start": current_date.isoformat(),
                "end": current_date.isoformat(),
            }

            self.logger.info(
                f"Day {day_offset + 1}/{max_days}: Querying fixtures for {current_date.isoformat()} "
                f"(current accumulated: {accumulated_sum:.1f}/{target})"
            )

            # Query fixtures for current day
            try:
                fixtures = await self._get_filtered_matches(
                    leagues=leagues,
                    date_range=date_range,
                    limit=100,
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to query fixtures for {current_date.isoformat()}: {e}",
                    exc_info=True,
                )
                failed_predictions += 1
                continue

            if not fixtures:
                self.logger.info(
                    f"No fixtures found for {current_date.isoformat()}, expanding to next day"
                )
                days_expanded += 1
                continue

            self.logger.info(
                f"Found {len(fixtures)} fixtures for {current_date.isoformat()}"
            )

            # Filter out already processed fixtures
            new_fixtures = [
                f for f in fixtures
                if f.get("id") not in all_fixtures_processed
            ]

            # Track all fixture IDs from this day
            for f in new_fixtures:
                all_fixtures_processed.add(f.get("id"))

            if not new_fixtures:
                self.logger.info(
                    f"All fixtures for {current_date.isoformat()} already processed, expanding to next day"
                )
                days_expanded += 1
                continue

            # Process fixtures in BATCHES OF 20 for this day
            batch_number = 0
            for batch_start in range(0, len(new_fixtures), self.BATCH_SIZE):
                batch_number += 1
                batch = new_fixtures[batch_start:batch_start + self.BATCH_SIZE]

                self.logger.info(
                    f"📦 Day {day_offset + 1}: Processing batch {batch_number} ({len(batch)} fixtures, "
                    f"accumulated: {accumulated_sum:.1f}/{target})"
                )

                # Process this batch concurrently
                batch_selections, batch_failures = await self._process_fixture_batch(
                    batch, user_id, thresholds
                )

                failed_predictions += batch_failures

                # Add accepted selections and accumulate odds
                for analysis in batch_selections:
                    best_market = analysis.get("best_market", {})
                    bookmaker_odd = best_market.get("bookmaker_odd", analysis.get("bookmaker_odd", 0))

                    selections.append(analysis)
                    accumulated_sum += bookmaker_odd

                    self.logger.info(
                        f"✅ Added {analysis['fixture'].get('home_team')} vs {analysis['fixture'].get('away_team')} "
                        f"(date: {current_date.isoformat()}, "
                        f"odd: {bookmaker_odd}, "
                        f"accumulated: {accumulated_sum:.1f}/{target})"
                    )

                    # Stop if target reached
                    if accumulated_sum >= target:
                        break

                # Check if target reached after processing this batch
                if accumulated_sum >= target:
                    self.logger.info(
                        f"🎯 Target achieved! {accumulated_sum:.1f} odds from {len(selections)} fixtures "
                        f"across {day_offset + 1} day(s)"
                    )
                    break

            # Check if target reached after processing this day
            if accumulated_sum >= target:
                break

            days_expanded += 1

        # Build final date range for reporting
        final_date_range = {
            "start": today.isoformat(),
            "end": (today + timedelta(days=days_expanded)).isoformat(),
        }

        # Build result
        warning = None
        if accumulated_sum < target:
            warning = (
                f"Only accumulated {accumulated_sum:.1f} odds (target: {target}) "
                f"after expanding to {days_expanded + 1} day(s). "
                f"Not enough fixtures met your quality criteria "
                f"(confidence >= {thresholds['min_confidence']:.0%})."
            )

        if failed_predictions > 0:
            failures_msg = f"{failed_predictions} prediction(s) failed."
            warning = f"{warning} {failures_msg}" if warning else failures_msg

        result = {
            "accumulated_odds": accumulated_sum,
            "target_odds": target,
            "selections": selections,
            "filters_applied": {
                "leagues": leagues,
                "date_range": final_date_range,
                "quality_threshold": quality_threshold,
                "thresholds": thresholds,
                "days_expanded": days_expanded + 1,
            },
            "warning": warning,
            "error": None,
        }

        self.logger.info(
            "Incremental expansion complete",
            extra={
                "user_id": user_id,
                "accumulated_odds": accumulated_sum,
                "target_odds": target,
                "num_selections": len(selections),
                "days_expanded": days_expanded + 1,
                "failed_predictions": failed_predictions,
            },
        )

        return result

    async def _get_filtered_matches(
        self,
        leagues: list[str] | None,
        date_range: dict[str, str] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Query ALL scheduled fixtures from MCP for AI evaluation.

        CRITICAL: Fetches ALL scheduled fixtures without odds filtering.
        The 5 AI agents will evaluate each fixture through 44 markets.
        Quality gates (confidence + EV) are applied AFTER AI evaluation,
        not at the database level.

        Flow:
        1. Get ALL scheduled fixtures for date range
        2. Orchestrator evaluates each through 5 AI agents
        3. Calculate confidence + EV for each market
        4. Apply quality gates AFTER evaluation
        5. Select fixtures that pass quality criteria

        Args:
            leagues: League names to filter by (e.g., ["Premier League", "LaLiga"])
            date_range: {"start": "2026-08-03", "end": "2026-08-10"}
            limit: Max fixtures to return

        Returns:
            List of ALL scheduled fixtures (no pre-filtering by odds)

        Raises:
            Exception: If MCP call fails
        """
        # Get data MCP client
        data_mcp = self.mcp_factory.create("data")

        # Build search_fixtures parameters
        # CRITICAL: Fetch ALL scheduled fixtures WITHOUT filtering by has_odds
        # Odds are fetched from API-Football during context aggregation
        # Quality gates (confidence + EV) are applied AFTER AI evaluation
        params = {
            "limit": limit,
            "status": "scheduled",
            # NOTE: has_odds removed - we fetch odds from API-Football directly
            # during context aggregation, not from database
        }

        # Add league filter if specified
        if leagues:
            params["league_names"] = leagues

        # Add date range if specified
        if date_range:
            params["date_from"] = date_range.get("start")
            params["date_to"] = date_range.get("end")

        # Call search_fixtures tool
        try:
            self.logger.info(
                f"Calling MCP search_fixtures with params: {params}"
            )
            result = await data_mcp.call_tool("search_fixtures", params)

            # MCP returns result in format: {"content": [{"type": "text", "text": "{...}"}]}
            # We need to extract and parse the text content
            if "content" in result and isinstance(result["content"], list) and len(result["content"]) > 0:
                content_item = result["content"][0]
                if "text" in content_item:
                    # Parse the JSON string inside text field
                    tool_result = json.loads(content_item["text"])
                    fixtures = tool_result.get("fixtures", [])
                else:
                    fixtures = []
            else:
                # Fallback: Try direct access (for backward compatibility)
                fixtures = result.get("fixtures", [])

            self.logger.info(
                f"MCP returned {len(fixtures)} fixtures, result keys: {list(result.keys())}"
            )

            self.logger.info(
                f"Retrieved {len(fixtures)} fixtures from MCP",
                extra={
                    "leagues": leagues,
                    "date_range": date_range,
                    "limit": limit,
                    "fixtures_found": len(fixtures),
                }
            )

            return fixtures

        except Exception as e:
            self.logger.error(f"MCP search_fixtures failed: {e}", exc_info=True)
            # Return empty list instead of failing the entire request
            return []

    async def _predict_fixture(
        self,
        fixture: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        """
        Predict fixture by evaluating ALL markets and selecting the best one.

        OPTIMIZED: This method aggregates context ONCE, then evaluates all 44 markets
        using the SAME context. This reduces MCP calls by 44x compared to the old approach.

        Flow:
        1. Aggregate and validate context ONCE (7 MCP calls)
        2. Get all 44 markets from registry
        3. Evaluate each market using pre-aggregated context (no MCP calls)
        4. Compare EV values across all markets
        5. Select market with highest EV
        6. Return that market's prediction with market explanation

        Retry Logic:
        - Transient errors (timeouts, rate limits, 503s) trigger exponential backoff retry
        - Permanent errors (ValueError, KeyError) fail fast without retry
        - Up to 3 attempts with 1s, 2s, 4s delays
        - If a market fails after retries, it's skipped (other markets continue)

        Args:
            fixture: Fixture data from MCP with keys:
                - id: Match identifier
                - home_team: {id, name}
                - away_team: {id, name}
            user_id: User identifier

        Returns:
            {
                "fixture": fixture,
                "best_market": {  # TOP 1 - Highlighted as the BEST option
                    "market_code": "BTTS",
                    "market_name": "Both Teams To Score",
                    "best_outcome": "Yes",
                    "probability": 0.72,
                    "bookmaker_odd": 2.5,
                    "confidence": 0.75,
                    "ev": 0.08,
                },
                "top_markets": [  # TOP 3 markets by probability
                    {...},  # Best (same as best_market)
                    {...},  # Second best
                    {...},  # Third best
                ],
                "markets_evaluated": 44,
                # Legacy fields for backward compatibility:
                "market_code": "BTTS",
                "market_name": "Both Teams To Score",
                "best_outcome": "Yes",
                "probability": 0.72,
                "bookmaker_odd": 2.5,
                "confidence": 0.75,
                "ev": 0.08,
            }

        Raises:
            Exception: If context validation fails or all market predictions fail
        """
        # Step 1: Aggregate and validate context ONCE (7 MCP calls total)
        self.logger.info(
            f"Aggregating context for fixture {fixture['id']}: "
            f"{fixture.get('home_team')} vs {fixture.get('away_team')}"
        )

        context, validation = await retry_with_backoff(
            self.orchestrator.aggregate_and_validate_context,
            sport="soccer",
            match_id=fixture["id"],
            max_attempts=3,
            initial_delay=1.0,
            backoff_factor=2.0,
            logger=self.logger,
        )

        # If context validation failed, skip this fixture
        if context is None:
            self.logger.info(
                f"Skipping fixture {fixture['id']} - context validation failed: {validation.get('reason')}"
            )
            raise Exception(f"Context validation failed: {validation.get('reason')}")

        self.logger.info(
            f"Context aggregated successfully for fixture {fixture['id']}"
        )

        # Step 2: Get all markets
        all_markets = get_all_markets()

        self.logger.info(
            f"Evaluating {len(all_markets)} markets for fixture {fixture['id']} "
            f"using pre-aggregated context (no additional MCP calls)"
        )

        # Step 3: Evaluate each market using pre-aggregated context
        # WITH CACHING: Check cache first, only call MCP tools on cache miss
        market_predictions = []
        failed_markets = 0
        cache_hits = 0
        cache_misses = 0

        # Get current date for cache key
        current_date = date.today().isoformat()  # Format: YYYY-MM-DD

        for market in all_markets:
            # Try cache first (if enabled)
            cache_key = f"prediction:{fixture['id']}:{market.code}:{current_date}"
            cached_result = None

            if self.cache_enabled:
                try:
                    cached_result = self.cache.get(cache_key)
                    if cached_result:
                        # Validate cached result - skip invalid predictions
                        cached_outcome = cached_result.get('best_outcome', 'Unknown')
                        cached_prob = cached_result.get('probability', 0.0)

                        if cached_outcome == 'Unknown' or cached_prob == 0.0:
                            # Invalid cached result - DELETE it and re-evaluate
                            # Always log this (important for debugging cache issues)
                            self.logger.warning(
                                f"  🗑️ {market.code}: CACHE INVALID (outcome={cached_outcome}, prob={cached_prob}) - DELETING and re-evaluating"
                            )
                            try:
                                self.cache.delete(cache_key)
                                self.logger.info(f"  ✅ Deleted invalid cache entry: {cache_key}")
                            except Exception as e:
                                self.logger.warning(f"  ⚠️ Failed to delete cache entry {cache_key}: {e}")
                            # Fall through to re-evaluate
                        else:
                            cache_hits += 1
                            market_predictions.append(cached_result)
                            # Only log cache hits if DEBUG enabled (reduces 44 logs per fixture)
                            if self.debug_enabled:
                                self.logger.debug(
                                    f"  {market.code}: CACHE HIT - {cached_result['best_outcome']} @ {cached_result['bookmaker_odd']} "
                                    f"(prob: {cached_result['probability']:.2f}, conf: {cached_result['confidence']:.2f}, ev: {cached_result['ev']:+.4f})"
                                )
                            continue  # Skip to next market
                except Exception as e:
                    # Cache read failed - log only if DEBUG (reduces noise)
                    if self.debug_enabled:
                        self.logger.debug(f"Cache read failed for {cache_key}: {e}")

            # Cache miss - call MCP tools
            cache_misses += 1

            try:
                # Use predict_with_context to avoid re-aggregating context
                # This skips 7 MCP calls per market (44 markets × 7 = 308 calls saved per fixture)
                prediction = await retry_with_backoff(
                    self.orchestrator.predict_with_context,
                    sport="soccer",
                    match_id=fixture["id"],
                    market=market.code,
                    context=context,  # Pre-aggregated context (shared across all markets)
                    user_id=user_id,
                    max_attempts=3,
                    initial_delay=1.0,
                    backoff_factor=2.0,
                    logger=self.logger,
                )

                # Extract data
                best_outcome = prediction.get("outcome", "Unknown")
                probability = prediction.get("probability", 0.0)  # Ensemble probability (0-1)
                ev_analysis = prediction.get("expected_value", {})
                bookmaker_odd = ev_analysis.get("odds", 0.0)
                ev_value = ev_analysis.get("expected_value", 0.0)

                # Extract confidence (convert from 0-100 to 0-1.0)
                confidence_raw = prediction.get("confidence", 0)
                confidence = confidence_raw / 100.0 if confidence_raw > 1 else confidence_raw

                market_result = {
                    "market_code": market.code,
                    "market_name": market.name,
                    "best_outcome": best_outcome,
                    "probability": probability,  # Likelihood of outcome occurring
                    "bookmaker_odd": bookmaker_odd,
                    "confidence": confidence,  # How certain we are about the probability
                    "ev": ev_value,
                }

                market_predictions.append(market_result)

                # Cache the result (expires at end of day - predictions stay valid for current day)
                # CRITICAL: Never cache invalid predictions (Unknown outcome or 0.0 probability)
                is_valid_prediction = best_outcome != "Unknown" and probability > 0.0

                if self.cache_enabled and is_valid_prediction:
                    try:
                        ttl = self._calculate_ttl_until_end_of_day()
                        self.cache.set(cache_key, market_result, ttl=ttl)
                        # Only log cache operations if DEBUG enabled
                        if self.debug_enabled:
                            self.logger.debug(
                                f"  {market.code}: {best_outcome} @ {bookmaker_odd} "
                                f"(prob: {probability:.2f}, conf: {confidence:.2f}, ev: {ev_value:+.4f}) [CACHED, TTL={ttl}s]"
                            )
                    except Exception as e:
                        # Cache write failed - log only in debug
                        if self.debug_enabled:
                            self.logger.debug(f"Cache write failed for {cache_key}: {e}")
                elif not is_valid_prediction:
                    # Invalid prediction - log warning
                    self.logger.warning(
                        f"  {market.code}: Invalid prediction (outcome={best_outcome}, prob={probability}) - NOT CACHED"
                    )
                elif self.debug_enabled:
                    # Only log if DEBUG enabled
                    self.logger.debug(
                        f"  {market.code}: {best_outcome} @ {bookmaker_odd} "
                        f"(prob: {probability:.2f}, conf: {confidence:.2f}, ev: {ev_value:+.4f})"
                    )

            except (RetryExhausted, PermanentError) as e:
                # Retry exhausted or permanent error - log only if DEBUG enabled
                if self.debug_enabled:
                    self.logger.debug(
                        f"Prediction failed for market {market.code} on fixture {fixture['id']}: {e}"
                    )
                failed_markets += 1
                continue
            except Exception as e:
                # Unexpected error - always log (could be important)
                self.logger.warning(
                    f"Unexpected error for market {market.code} on fixture {fixture['id']}: {e}"
                )
                failed_markets += 1
                continue

        # Step 3: Check if we have any successful predictions
        if not market_predictions:
            raise Exception(
                f"All {len(all_markets)} market predictions failed for fixture {fixture['id']}"
            )

        # Step 4: Select TOP 3 markets by probability
        # Strategy: Pick the most likely outcomes per fixture, not the highest value bets
        # This prioritizes accuracy (what will happen) over expected value (what's profitable)
        sorted_markets = sorted(market_predictions, key=lambda m: m["probability"], reverse=True)
        top_markets = sorted_markets[:self.TOP_MARKETS]  # Top 3 by default
        best_market = top_markets[0]  # #1 is the BEST option (highlighted)

        # Log summary (INFO level - always visible)
        cache_stats = ""
        if self.cache_enabled and (cache_hits + cache_misses) > 0:
            cache_stats = f", cache: {cache_hits}H/{cache_misses}M ({cache_hits/(cache_hits+cache_misses)*100:.0f}%)"

        # Log top 3 markets
        top_markets_summary = " | ".join([
            f"#{i+1} {m['market_code']}: {m['best_outcome']} @ {m['bookmaker_odd']} (prob={m['probability']:.2f})"
            for i, m in enumerate(top_markets)
        ])
        self.logger.info(
            f"📊 {fixture.get('home_team')} vs {fixture.get('away_team')} → "
            f"TOP {len(top_markets)}: {top_markets_summary}{cache_stats}"
        )

        # Step 5: Return top 3 markets with best highlighted
        return {
            "fixture": fixture,
            # NEW: Top 3 markets structure
            "best_market": {
                "market_code": best_market["market_code"],
                "market_name": best_market["market_name"],
                "best_outcome": best_market["best_outcome"],
                "probability": best_market["probability"],
                "bookmaker_odd": best_market["bookmaker_odd"],
                "confidence": best_market["confidence"],
                "ev": best_market["ev"],
                "rank": 1,
                "is_best": True,
            },
            "top_markets": [
                {
                    "market_code": m["market_code"],
                    "market_name": m["market_name"],
                    "best_outcome": m["best_outcome"],
                    "probability": m["probability"],
                    "bookmaker_odd": m["bookmaker_odd"],
                    "confidence": m["confidence"],
                    "ev": m["ev"],
                    "rank": i + 1,
                    "is_best": i == 0,
                }
                for i, m in enumerate(top_markets)
            ],
            "markets_evaluated": len(market_predictions),
            # Legacy fields for backward compatibility
            "market_code": best_market["market_code"],
            "market_name": best_market["market_name"],
            "best_outcome": best_market["best_outcome"],
            "probability": best_market["probability"],
            "bookmaker_odd": best_market["bookmaker_odd"],
            "confidence": best_market["confidence"],
            "ev": best_market["ev"],
        }
