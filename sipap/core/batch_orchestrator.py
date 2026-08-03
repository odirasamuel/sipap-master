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

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sipap.conversation import RequestIntent
from sipap.core.retry import PermanentError, RetryExhausted, retry_with_backoff
from sipap.sports.soccer.markets import get_all_markets
from sipap_common.logging import get_logger


class BatchOrchestrator:
    """
    Orchestrates batch prediction requests with accumulated odds logic.

    Responsibilities:
    - Query fixtures with filters (leagues, dates, status)
    - Predict iteratively (not all at once for efficiency)
    - Accumulate bookmaker odds until target reached
    - Apply quality gates (confidence + EV thresholds)
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

        # Quality threshold mappings
        # These map user quality terms to confidence + EV thresholds
        self.quality_thresholds = {
            "highest": {"min_confidence": 0.70, "min_ev": 0.10},  # Sure odds
            "high": {"min_confidence": 0.60, "min_ev": 0.05},  # Best possible
            "medium": {"min_confidence": 0.55, "min_ev": 0.00},  # Decent
        }

        self.logger.info("BatchOrchestrator initialized")

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
            },
        )

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
            result = await self._process_with_incremental_expansion(
                user_id=user_id,
                target=target,
                quality_threshold=quality_threshold,
                thresholds=thresholds,
                leagues=intent.leagues,
                max_days=7,  # Maximum 7 days expansion
            )
            return result

        # Step 2 (fallback): Query fixtures with explicit date range
        try:
            fixtures = await self._get_filtered_matches(
                leagues=intent.leagues,
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

        # Step 3: Predict iteratively and accumulate until target reached
        # NOTE: Market selection happens INSIDE _predict_fixture now
        # The system evaluates ALL markets and picks the best one per fixture
        accumulated_sum = 0.0
        selections = []
        failed_predictions = 0

        for fixture in fixtures:
            # Stop if target reached
            if accumulated_sum >= target:
                break

            # Predict fixture - evaluates ALL markets, picks best EV
            try:
                analysis = await self._predict_fixture(fixture, user_id)

                # Apply quality gates
                if (
                    analysis["confidence"] >= thresholds["min_confidence"]
                    and analysis["ev"] >= thresholds["min_ev"]
                ):
                    # Add to selections
                    selections.append(analysis)
                    accumulated_sum += analysis["bookmaker_odd"]

                    self.logger.debug(
                        f"Added fixture: {fixture.get('id')} "
                        f"(odd: {analysis['bookmaker_odd']}, "
                        f"accumulated: {accumulated_sum:.1f})"
                    )
                else:
                    self.logger.debug(
                        f"Fixture {fixture.get('id')} failed quality gates: "
                        f"conf={analysis['confidence']:.2f} "
                        f"(need {thresholds['min_confidence']}), "
                        f"ev={analysis['ev']:.2f} "
                        f"(need {thresholds['min_ev']})"
                    )

            except Exception as e:
                self.logger.error(
                    f"Prediction failed for fixture {fixture.get('id')}: {e}",
                    exc_info=True,
                )
                failed_predictions += 1
                continue

        # Step 5: Build result
        warning = None
        if accumulated_sum < target:
            warning = (
                f"Only accumulated {accumulated_sum:.1f} odds (target: {target}). "
                f"Not enough fixtures met your quality criteria "
                f"(confidence >= {thresholds['min_confidence']:.0%}, "
                f"EV >= {thresholds['min_ev']:.0%})."
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

            # Process each fixture for this day
            for fixture in fixtures:
                fixture_id = fixture.get("id")

                # Skip if already processed (shouldn't happen but safety check)
                if fixture_id in all_fixtures_processed:
                    continue
                all_fixtures_processed.add(fixture_id)

                # Stop if target reached
                if accumulated_sum >= target:
                    self.logger.info(
                        f"Target reached! {accumulated_sum:.1f} >= {target} "
                        f"after {day_offset + 1} days"
                    )
                    break

                # Predict fixture
                try:
                    analysis = await self._predict_fixture(fixture, user_id)

                    # Apply quality gates
                    if (
                        analysis["confidence"] >= thresholds["min_confidence"]
                        and analysis["ev"] >= thresholds["min_ev"]
                    ):
                        selections.append(analysis)
                        accumulated_sum += analysis["bookmaker_odd"]

                        self.logger.info(
                            f"✅ Added {fixture.get('home_team')} vs {fixture.get('away_team')} "
                            f"(date: {current_date.isoformat()}, "
                            f"odd: {analysis['bookmaker_odd']}, "
                            f"accumulated: {accumulated_sum:.1f}/{target})"
                        )
                    else:
                        self.logger.debug(
                            f"❌ Rejected {fixture.get('home_team')} vs {fixture.get('away_team')} "
                            f"(conf: {analysis['confidence']:.2f} < {thresholds['min_confidence']}, "
                            f"ev: {analysis['ev']:.2f} < {thresholds['min_ev']})"
                        )

                except Exception as e:
                    self.logger.error(
                        f"Prediction failed for fixture {fixture_id}: {e}",
                        exc_info=True,
                    )
                    failed_predictions += 1
                    continue

            # Check if target reached after processing this day
            if accumulated_sum >= target:
                self.logger.info(
                    f"🎯 Target achieved! {accumulated_sum:.1f} odds from {len(selections)} fixtures "
                    f"across {day_offset + 1} day(s)"
                )
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
                f"(confidence >= {thresholds['min_confidence']:.0%}, "
                f"EV >= {thresholds['min_ev']:.0%})."
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
        # CRITICAL: Fetch ALL scheduled fixtures, don't filter by has_odds
        # Let the orchestrator evaluate all fixtures through 5 AI agents
        # Quality gates (confidence + EV) are applied AFTER AI evaluation
        params = {
            "limit": limit,
            "status": "scheduled",
            "has_odds": True,  # Need odds for EV calculation
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

        CRITICAL: This method evaluates ALL 44 betting markets for the fixture
        and selects the market with the HIGHEST expected value (EV).

        Flow:
        1. Get all 44 markets from registry
        2. Call MainOrchestrator.predict() for EACH market (with retry logic)
        3. Compare EV values across all markets
        4. Select market with highest EV
        5. Return that market's prediction with market explanation

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
                "market_code": "BTTS",  # Selected market code
                "market_name": "Both Teams To Score",  # Human-readable market name
                "best_outcome": "Yes",  # Best outcome for selected market
                "bookmaker_odd": 2.5,  # Bookmaker odd for that outcome
                "confidence": 0.75,  # Confidence (0-1.0)
                "ev": 0.08,  # Expected value
                "markets_evaluated": 44,  # Number of markets evaluated
            }

        Raises:
            Exception: If all market predictions fail
        """
        # Step 1: Get all markets
        all_markets = get_all_markets()

        self.logger.debug(
            f"Evaluating {len(all_markets)} markets for fixture {fixture['id']}"
        )

        # Step 2: Evaluate each market
        market_predictions = []
        failed_markets = 0

        for market in all_markets:
            try:
                # Wrap prediction call with retry logic for resilience
                # Retries transient errors (timeouts, rate limits, 503s)
                # Fast-fails on permanent errors (ValueError, KeyError)
                prediction = await retry_with_backoff(
                    self.orchestrator.predict,
                    sport="soccer",
                    match_id=fixture["id"],
                    market=market.code,
                    user_id=user_id,
                    user_message=None,  # No user message for batch predictions
                    max_attempts=3,
                    initial_delay=1.0,
                    backoff_factor=2.0,
                    logger=self.logger,
                )

                # Extract data
                best_outcome = prediction.get("outcome", "Unknown")
                ev_analysis = prediction.get("expected_value", {})
                bookmaker_odd = ev_analysis.get("odds", 0.0)
                ev_value = ev_analysis.get("expected_value", 0.0)

                # Extract confidence (convert from 0-100 to 0-1.0)
                confidence_raw = prediction.get("confidence", 0)
                confidence = confidence_raw / 100.0 if confidence_raw > 1 else confidence_raw

                market_predictions.append({
                    "market_code": market.code,
                    "market_name": market.name,
                    "best_outcome": best_outcome,
                    "bookmaker_odd": bookmaker_odd,
                    "confidence": confidence,
                    "ev": ev_value,
                })

                self.logger.debug(
                    f"  {market.code}: {best_outcome} @ {bookmaker_odd} "
                    f"(conf: {confidence:.2f}, ev: {ev_value:+.4f})"
                )

            except (RetryExhausted, PermanentError) as e:
                # Retry exhausted or permanent error - log and skip this market
                self.logger.warning(
                    f"Prediction failed for market {market.code} on fixture {fixture['id']}: {e}"
                )
                failed_markets += 1
                continue
            except Exception as e:
                # Unexpected error - log and skip this market
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

        # Step 4: Select market with highest EV
        best_market = max(market_predictions, key=lambda m: m["ev"])

        self.logger.info(
            f"Selected {best_market['market_code']} for fixture {fixture['id']}: "
            f"{best_market['best_outcome']} @ {best_market['bookmaker_odd']} "
            f"(conf: {best_market['confidence']:.2f}, ev: {best_market['ev']:+.4f}) "
            f"[evaluated {len(market_predictions)}/{len(all_markets)} markets]"
        )

        # Step 5: Return best market with fixture data
        return {
            "fixture": fixture,
            "market_code": best_market["market_code"],
            "market_name": best_market["market_name"],
            "best_outcome": best_market["best_outcome"],
            "bookmaker_odd": best_market["bookmaker_odd"],
            "confidence": best_market["confidence"],
            "ev": best_market["ev"],
            "markets_evaluated": len(market_predictions),
        }
