"""Market Evaluator for SIPAP Soccer Predictions.

Evaluates all 44 betting markets using Data MCP tool responses and
returns the top N markets ranked by probability of success.

This module provides:
- MarketOutcome: Single outcome within a market
- MarketEvaluation: Complete evaluation result for a market
- MarketEvaluator: Main class to evaluate all markets for a fixture
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from sipap.sports.soccer.markets import REGISTRY, get_market

logger = logging.getLogger(__name__)

# DC 12 outcome penalty factor: Reduces 12 (Home/Away) probability to prioritize
# 1X (Home/Draw) and X2 (Draw/Away) which include draws and are safer bets.
# Values: 1.0 = no penalty, 0.85 = 15% penalty (recommended), 0.0 = never select 12
DC_12_PENALTY_FACTOR = float(os.environ.get("DC_12_PENALTY_FACTOR", "0.85"))


@dataclass
class MarketOutcome:
    """Single outcome within a market.

    Attributes:
        outcome_code: Unique identifier for the outcome (e.g., "Home Win", "Over 2.5")
        probability: Raw historical probability (0.0 - 1.0)
        weighted_probability: Recency-weighted probability (50/30/20 weighting)
        confidence: Data quality indicator ("high", "medium", "low")
        odds: Bookmaker odds for this outcome (None if not fetched)
        bookmaker: Name of bookmaker offering best odds (None if not fetched)
    """

    outcome_code: str
    probability: float
    weighted_probability: float
    confidence: str = "medium"
    odds: float | None = None
    bookmaker: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "outcome": self.outcome_code,
            "probability": round(self.probability, 4),
            "weighted_probability": round(self.weighted_probability, 4),
            "confidence": self.confidence,
        }
        # Include odds if available
        if self.odds is not None:
            result["odds"] = round(self.odds, 2)
        if self.bookmaker is not None:
            result["bookmaker"] = self.bookmaker
        return result


@dataclass
class MarketEvaluation:
    """Evaluation result for a single betting market.

    Attributes:
        market_code: Unique market identifier (e.g., "1X2", "BTTS", "OU2.5")
        market_name: Human-readable market name
        outcomes: List of possible outcomes with probabilities
        best_outcome: The outcome with highest weighted probability
        data_quality: Overall data quality for this market
        seasons_analyzed: Number of seasons included in analysis
        matches_analyzed: Total matches used for probability calculation
        best_odds: Best bookmaker odds for the top outcome (None if not fetched)
        best_odds_bookmaker: Bookmaker offering best odds (None if not fetched)
    """

    market_code: str
    market_name: str
    outcomes: list[MarketOutcome]
    best_outcome: MarketOutcome
    data_quality: str = "medium"
    seasons_analyzed: int = 0
    matches_analyzed: int = 0
    best_odds: float | None = None
    best_odds_bookmaker: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "market_code": self.market_code,
            "market_name": self.market_name,
            "best_outcome": self.best_outcome.outcome_code,
            "probability": round(self.best_outcome.weighted_probability, 4),
            "confidence": self.best_outcome.confidence,
            "data_quality": self.data_quality,
            "matches_analyzed": self.matches_analyzed,
            "seasons_analyzed": self.seasons_analyzed,
            "all_outcomes": [o.to_dict() for o in self.outcomes],
        }
        # Include odds if available (from best_outcome or direct fields)
        odds = self.best_odds if self.best_odds is not None else self.best_outcome.odds
        bookmaker = self.best_odds_bookmaker if self.best_odds_bookmaker is not None else self.best_outcome.bookmaker
        if odds is not None:
            result["best_odds"] = round(odds, 2)
        if bookmaker is not None:
            result["best_odds_bookmaker"] = bookmaker
        return result


@dataclass
class ToolData:
    """Container for tool response data."""

    data: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        """Check if tool returned valid data."""
        return self.error is None and bool(self.data)


class MarketEvaluator:
    """Evaluates all 44 betting markets using Data MCP tool responses.

    The MarketEvaluator:
    1. Fetches all required data from Data MCP tools (17 parallel calls)
    2. Evaluates each of the 44 markets using the tool responses
    3. Ranks markets by weighted probability
    4. Returns top N markets with best outcome probabilities

    Example:
        >>> evaluator = MarketEvaluator(data_mcp_client)
        >>> evaluations = await evaluator.evaluate_all_markets(
        ...     home_team_id=728,
        ...     away_team_id=542,
        ...     league_id=140
        ... )
        >>> top_3 = evaluator.get_top_markets(evaluations, top_n=3)
    """

    def __init__(self, data_mcp_client: Any):
        """Initialize MarketEvaluator.

        Args:
            data_mcp_client: MCP client for calling Data MCP tools
        """
        self.data_mcp = data_mcp_client
        self._tool_cache: dict[str, ToolData] = {}
        self._home_id: int = 0
        self._away_id: int = 0
        self._league_id: int = 0

    def _validate_market_codes(
        self,
        market_codes: list[str] | None,
    ) -> list[str] | None:
        """Validate and normalize market codes.

        Args:
            market_codes: List of market codes to validate (e.g., ["BTTS", "1X2"])
                         None means evaluate all markets.

        Returns:
            Validated list of market codes (uppercase, deduplicated) or None

        Raises:
            ValueError: If any market code is invalid/not found in registry
        """
        if market_codes is None:
            return None

        if not market_codes:
            # Empty list means no filtering (evaluate all)
            return None

        validated: list[str] = []
        invalid_codes: list[str] = []

        for code in market_codes:
            # Normalize to uppercase
            normalized = code.upper().strip()

            # Check if market exists in registry
            market = get_market(normalized)
            if market is None:
                invalid_codes.append(code)
            elif normalized not in validated:
                validated.append(normalized)

        if invalid_codes:
            valid_codes = [m.code for m in REGISTRY.get_all()]
            raise ValueError(
                f"Invalid market codes: {invalid_codes}. "
                f"Valid codes include: {', '.join(sorted(valid_codes)[:10])}..."
            )

        return validated if validated else None

    async def evaluate_all_markets(
        self,
        home_team_id: int,
        away_team_id: int,
        league_id: int,
        market_codes: list[str] | None = None,
    ) -> list[MarketEvaluation]:
        """Evaluate markets for a fixture.

        Args:
            home_team_id: API-Football team ID for home team
            away_team_id: API-Football team ID for away team
            league_id: API-Football league ID
            market_codes: Optional list of market codes to evaluate.
                         If None, evaluates all 44 markets.
                         If provided, only evaluates specified markets.

        Returns:
            List of MarketEvaluation objects for requested markets

        Raises:
            ValueError: If any market code is invalid

        Examples:
            # Evaluate all 44 markets (original behavior)
            results = await evaluator.evaluate_all_markets(1, 2, 39)

            # Evaluate only BTTS market
            results = await evaluator.evaluate_all_markets(1, 2, 39, market_codes=["BTTS"])

            # Evaluate multiple specific markets
            results = await evaluator.evaluate_all_markets(
                1, 2, 39, market_codes=["1X2", "BTTS", "DC", "DNB"]
            )
        """
        self._home_id = home_team_id
        self._away_id = away_team_id
        self._league_id = league_id

        # Validate and normalize market codes
        validated_codes = self._validate_market_codes(market_codes)
        filter_markets = validated_codes is not None

        if filter_markets:
            logger.info(
                f"Evaluating {len(validated_codes)} markets for fixture: "
                f"{home_team_id} vs {away_team_id} (league: {league_id}). "
                f"Markets: {validated_codes}"
            )
        else:
            logger.info(
                f"Evaluating all 44 markets for fixture: {home_team_id} vs {away_team_id} "
                f"(league: {league_id})"
            )

        # Phase 1: Fetch all required tool data (parallel calls)
        tool_data = await self._fetch_all_tool_data()

        # Phase 2: Evaluate each market category
        evaluations: list[MarketEvaluation] = []

        # Main markets (9): 1X2, DNB, BTTS, DC, OU0.5-4.5
        evaluations.extend(self._evaluate_main_markets(tool_data))

        # Halftime markets (5): HT_1X2, HT_DC, HT_OU0.5-2.5
        evaluations.extend(self._evaluate_halftime_markets(tool_data))

        # 2nd half markets (4): 2H_DC, 2H_OU0.5-2.5
        evaluations.extend(self._evaluate_2nd_half_markets(tool_data))

        # Team-specific markets (6): HOME_SCORE, AWAY_SCORE, WIN_HALF
        evaluations.extend(self._evaluate_team_specific_markets(tool_data))

        # HT/FT market (1): 9 combinations
        evaluations.extend(self._evaluate_htft_market(tool_data))

        # Combination markets - AND logic (11): 1X2+OU, 1X2+BTTS, DC+OU, DC+BTTS, BTTS+OU
        evaluations.extend(await self._evaluate_combination_and_markets(tool_data))

        # Chance mix markets - OR logic (7): CHANCEMIX variations
        evaluations.extend(await self._evaluate_chance_mix_markets(tool_data))

        # Advanced markets (1): MULTI_GOAL
        evaluations.extend(self._evaluate_advanced_markets(tool_data))

        # Phase 3: Filter to requested markets if specified
        if filter_markets and validated_codes:
            evaluations = [
                e for e in evaluations
                if e.market_code in validated_codes
            ]
            logger.info(
                f"Filtered to {len(evaluations)} markets matching: {validated_codes}"
            )
        else:
            logger.info(f"Evaluated {len(evaluations)} markets successfully")

        return evaluations

    def get_top_markets(
        self,
        evaluations: list[MarketEvaluation],
        top_n: int = 3,
        min_probability: float = 0.5,
        min_data_quality: str = "low",
    ) -> list[dict]:
        """Select top N markets ranked by probability of success.

        Ranking criteria (in order of priority):
        1. Weighted probability of best outcome (primary)
        2. Data quality: high > medium > low (secondary)
        3. Number of matches analyzed (tertiary)

        Args:
            evaluations: List of MarketEvaluation objects
            top_n: Number of top markets to return (default: 3)
            min_probability: Minimum probability threshold (default: 0.5)
            min_data_quality: Minimum data quality level (default: "low")

        Returns:
            List of dictionaries with top market details
        """
        quality_order = {"high": 3, "medium": 2, "low": 1}

        # Filter by minimum thresholds
        filtered = [
            e
            for e in evaluations
            if e.best_outcome.weighted_probability >= min_probability
            and quality_order.get(e.data_quality, 0)
            >= quality_order.get(min_data_quality, 0)
        ]

        # Sort by composite score
        def ranking_score(e: MarketEvaluation) -> tuple:
            return (
                e.best_outcome.weighted_probability,  # Primary: probability
                quality_order.get(e.data_quality, 0),  # Secondary: data quality
                e.matches_analyzed,  # Tertiary: sample size
            )

        sorted_evals = sorted(filtered, key=ranking_score, reverse=True)

        # Format top N for response
        return [
            {
                "rank": i + 1,
                **e.to_dict(),
            }
            for i, e in enumerate(sorted_evals[:top_n])
        ]

    async def evaluate_all_markets_with_odds(
        self,
        home_team_id: int,
        away_team_id: int,
        league_id: int,
        fixture_id: int,
        api_client: Any,
        top_n: int = 3,
        min_probability: float = 0.5,
        market_codes: list[str] | None = None,
    ) -> list[MarketEvaluation]:
        """Evaluate markets AND fetch odds for top outcomes.

        This is the primary method for accumulator building. It:
        1. Evaluates probabilities for requested markets (or all 44)
        2. Ranks markets by probability
        3. Fetches bookmaker odds for top N markets
        4. Returns evaluations with odds attached

        Args:
            home_team_id: API-Football team ID for home team
            away_team_id: API-Football team ID for away team
            league_id: API-Football league ID
            fixture_id: API-Football fixture ID (for odds lookup)
            api_client: API-Football client instance for odds fetching
            top_n: Number of top markets to fetch odds for (default: 3)
            min_probability: Minimum probability threshold (default: 0.5)
            market_codes: Optional list of market codes to evaluate.
                         If None, evaluates all 44 markets.
                         If provided, only evaluates specified markets.

        Returns:
            List of MarketEvaluation objects with odds attached to top markets

        Raises:
            ValueError: If any market code is invalid

        Example:
            >>> # Evaluate all markets with odds
            >>> evaluations = await evaluator.evaluate_all_markets_with_odds(
            ...     home_team_id=728,
            ...     away_team_id=542,
            ...     league_id=140,
            ...     fixture_id=1234567,
            ...     api_client=api_client,
            ...     top_n=3
            ... )

            >>> # Evaluate only BTTS and OU2.5 markets with odds
            >>> evaluations = await evaluator.evaluate_all_markets_with_odds(
            ...     home_team_id=728,
            ...     away_team_id=542,
            ...     league_id=140,
            ...     fixture_id=1234567,
            ...     api_client=api_client,
            ...     market_codes=["BTTS", "OU2.5"]
            ... )
        """
        # Step 1: Evaluate markets for probabilities (filtered if specified)
        evaluations = await self.evaluate_all_markets(
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            league_id=league_id,
            market_codes=market_codes,
        )

        # Step 2: Get top markets that meet threshold
        quality_order = {"high": 3, "medium": 2, "low": 1}
        filtered = [
            e
            for e in evaluations
            if e.best_outcome.weighted_probability >= min_probability
        ]

        # Sort by probability
        sorted_evals = sorted(
            filtered,
            key=lambda e: (
                e.best_outcome.weighted_probability,
                quality_order.get(e.data_quality, 0),
                e.matches_analyzed,
            ),
            reverse=True,
        )

        top_markets = sorted_evals[:top_n]

        # Step 3: Fetch odds for top markets in parallel
        await self._attach_odds_to_evaluations(
            evaluations=top_markets,
            fixture_id=fixture_id,
            api_client=api_client,
        )

        logger.info(
            f"Evaluated {len(evaluations)} markets with odds for top {len(top_markets)}"
        )
        return evaluations

    async def _attach_odds_to_evaluations(
        self,
        evaluations: list[MarketEvaluation],
        fixture_id: int,
        api_client: Any,
    ) -> None:
        """Fetch and attach odds to market evaluations.

        Args:
            evaluations: List of MarketEvaluation to update with odds
            fixture_id: API-Football fixture ID
            api_client: API-Football client instance
        """
        from sipap.sports.soccer.bet_mappings import get_bet_mapping, has_direct_odds

        async def fetch_odds(evaluation: MarketEvaluation) -> None:
            """Fetch odds for a single evaluation."""
            market_code = evaluation.market_code
            outcome = evaluation.best_outcome.outcome_code

            # Skip markets without direct odds support
            if not has_direct_odds(market_code):
                logger.debug(f"No direct odds for {market_code}, skipping")
                return

            mapping = get_bet_mapping(market_code)
            if mapping is None:
                return

            # Map outcome to API format
            api_outcome = mapping.get_api_outcome(outcome)
            if api_outcome is None:
                # Try using outcome directly
                api_outcome = outcome

            try:
                # Call API-Football for odds
                response = await api_client.get_odds(
                    fixture_id=fixture_id,
                    bet=mapping.bet_id,
                )

                # Import transformer
                from sipap_data_mcp.api.transformers import transform_odds_for_market

                odds_data = transform_odds_for_market(
                    api_response=response,
                    fixture_id=fixture_id,
                    bet_id=mapping.bet_id,
                    target_outcome=api_outcome,
                    line=mapping.line,
                )

                if odds_data["best_odds"] > 0:
                    evaluation.best_odds = odds_data["best_odds"]
                    evaluation.best_odds_bookmaker = odds_data["best_bookmaker"]
                    evaluation.best_outcome.odds = odds_data["best_odds"]
                    evaluation.best_outcome.bookmaker = odds_data["best_bookmaker"]
                    logger.info(
                        f"Odds for {market_code}/{outcome}: "
                        f"{odds_data['best_odds']} @ {odds_data['best_bookmaker']}"
                    )

            except ImportError:
                logger.warning("sipap_data_mcp not available, odds fetching disabled")
            except Exception as e:
                logger.warning(f"Failed to fetch odds for {market_code}: {e}")

        # Fetch odds SEQUENTIALLY with rate limiting delay
        RATE_LIMIT_DELAY = 0.15  # 150ms between calls
        for idx, evaluation in enumerate(evaluations):
            await fetch_odds(evaluation)
            # Add delay between calls (except after the last one)
            if idx < len(evaluations) - 1:
                await asyncio.sleep(RATE_LIMIT_DELAY)

    # =========================================================================
    # Phase 1: Data Fetching
    # =========================================================================

    async def _fetch_all_tool_data(self) -> dict[str, ToolData]:
        """Fetch all required tool data with sequential calls.

        Makes 17 sequential MCP calls with rate limiting to avoid API throttling.
        Results are cached for reuse across market evaluations.

        Rate limiting: 150ms delay between calls to stay under API-Football limits.

        Returns:
            Dictionary mapping tool keys to ToolData objects
        """
        tool_calls = {
            # Core Statistical (5 tools)
            "h2h_ftr": (
                "get_h2h_full_time_result",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "h2h_goals": (
                "get_h2h_goals",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "bts": (
                "get_bts",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "home_goals": (
                "get_home_total_goals",
                {
                    "team": self._home_id,
                    "league": self._league_id,
                },
            ),
            "away_goals": (
                "get_away_total_goals",
                {
                    "team": self._away_id,
                    "league": self._league_id,
                },
            ),
            # Halftime Analysis (5 tools)
            "ht_result": (
                "get_h2h_half_time_result",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "ht_goals": (
                "get_half_time_goals",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "2h_result": (
                "get_h2h_2nd_half_result",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "2h_goals": (
                "get_2nd_half_goals",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "ht_ft": (
                "get_ht_ft_outcome",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            # Specialized (5 tools)
            "double_chance_home": (
                "get_double_chance",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                    "perspective": "home",
                },
            ),
            "double_chance_away": (
                "get_double_chance",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                    "perspective": "away",
                },
            ),
            "home_to_score": (
                "get_home_to_score",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "away_to_score": (
                "get_away_to_score",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "total_goals_range": (
                "get_total_goals_range",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            # Either Half Outcomes (2 tools)
            "home_either_half": (
                "get_home_either_half_outcome",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
            "away_either_half": (
                "get_away_either_half_outcome",
                {
                    "home_team": self._home_id,
                    "away_team": self._away_id,
                    "league": self._league_id,
                },
            ),
        }

        async def call_tool(key: str, tool_name: str, params: dict) -> tuple[str, ToolData]:
            """Call a single MCP tool and return parsed result."""
            try:
                result = await self.data_mcp.call_tool(tool_name, params)
                # Parse the JSON-RPC response
                if isinstance(result, dict):
                    # Handle nested content structure from MCP
                    if "content" in result:
                        content = result["content"]
                        if isinstance(content, list) and content:
                            text = content[0].get("text", "{}")
                            parsed = json.loads(text) if isinstance(text, str) else text
                            return key, ToolData(
                                data=parsed.get("data", parsed),
                                metadata=parsed.get("metadata", {}),
                            )
                    # Direct response
                    return key, ToolData(
                        data=result.get("data", result),
                        metadata=result.get("metadata", {}),
                    )
                return key, ToolData(error=f"Unexpected result type: {type(result)}")
            except Exception as e:
                logger.warning(f"Tool {tool_name} failed: {e}")
                return key, ToolData(error=str(e))

        # Execute calls SEQUENTIALLY with rate limiting delay
        # This prevents API-Football 429 rate limiting errors
        RATE_LIMIT_DELAY = 0.15  # 150ms between calls

        results: dict[str, ToolData] = {}
        tool_items = list(tool_calls.items())
        total_tools = len(tool_items)

        for idx, (key, (tool_name, params)) in enumerate(tool_items):
            try:
                result_key, tool_data = await call_tool(key, tool_name, params)
                results[result_key] = tool_data
                self._tool_cache[result_key] = tool_data

                # Add delay between calls (except after the last one)
                if idx < total_tools - 1:
                    await asyncio.sleep(RATE_LIMIT_DELAY)

            except Exception as e:
                logger.error(f"Tool {tool_name} failed with exception: {e}")
                results[key] = ToolData(error=str(e))

        logger.info(f"Fetched data from {len(results)} tools (sequential)")
        return results

    # =========================================================================
    # Phase 2: Market Evaluation Functions
    # =========================================================================

    def _get_quality(self, data: dict) -> str:
        """Determine data quality based on matches analyzed."""
        matches = data.get("total_matches", 0)
        if matches >= 15:
            return "high"
        elif matches >= 8:
            return "medium"
        return "low"

    def _get_best_outcome(self, outcomes: list[MarketOutcome]) -> MarketOutcome:
        """Find outcome with highest weighted probability."""
        return max(outcomes, key=lambda o: o.weighted_probability)

    def _evaluate_main_markets(self, tool_data: dict[str, ToolData]) -> list[MarketEvaluation]:
        """Evaluate markets 1-9: 1X2, DNB, BTTS, DC, OU0.5-4.5."""
        evaluations: list[MarketEvaluation] = []

        # Market 1: 1X2 (Match Result)
        ftr_data = tool_data.get("h2h_ftr", ToolData())
        if ftr_data.is_valid:
            data = ftr_data.data
            wp = data.get("weighted_probabilities", {})
            quality = self._get_quality(data)

            outcomes = [
                MarketOutcome(
                    "Home Win",
                    data.get("home_win_probability", 0),
                    wp.get("home_win", data.get("home_win_probability", 0)),
                    quality,
                ),
                MarketOutcome(
                    "Draw",
                    data.get("draw_probability", 0),
                    wp.get("draw", data.get("draw_probability", 0)),
                    quality,
                ),
                MarketOutcome(
                    "Away Win",
                    data.get("away_win_probability", 0),
                    wp.get("away_win", data.get("away_win_probability", 0)),
                    quality,
                ),
            ]

            evaluations.append(
                MarketEvaluation(
                    market_code="1X2",
                    market_name="Match Result",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=ftr_data.metadata.get("seasons_analyzed", 0),
                    matches_analyzed=data.get("total_matches", 0),
                )
            )

            # Market 2: DNB (Draw No Bet) - Derived from 1X2
            home_prob = wp.get("home_win", 0)
            away_prob = wp.get("away_win", 0)
            dnb_total = home_prob + away_prob
            if dnb_total > 0:
                dnb_outcomes = [
                    MarketOutcome(
                        "Home Win",
                        home_prob / dnb_total,
                        home_prob / dnb_total,
                        quality,
                    ),
                    MarketOutcome(
                        "Away Win",
                        away_prob / dnb_total,
                        away_prob / dnb_total,
                        quality,
                    ),
                ]
                evaluations.append(
                    MarketEvaluation(
                        market_code="DNB",
                        market_name="Draw No Bet",
                        outcomes=dnb_outcomes,
                        best_outcome=self._get_best_outcome(dnb_outcomes),
                        data_quality=quality,
                        seasons_analyzed=ftr_data.metadata.get("seasons_analyzed", 0),
                        matches_analyzed=data.get("total_matches", 0),
                    )
                )

        # Market 3: BTTS (Both Teams To Score)
        bts_data = tool_data.get("bts", ToolData())
        if bts_data.is_valid:
            data = bts_data.data
            quality = self._get_quality(data)
            bts_prob = data.get("bts_probability", 0)
            weighted_bts = data.get("weighted_bts_probability", bts_prob)

            outcomes = [
                MarketOutcome("Yes", bts_prob, weighted_bts, quality),
                MarketOutcome("No", 1 - bts_prob, 1 - weighted_bts, quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="BTTS",
                    market_name="Both Teams To Score",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=bts_data.metadata.get("seasons_analyzed", 0),
                    matches_analyzed=data.get("total_matches", 0),
                )
            )

        # Market 4: Double Chance (1X, 12, X2)
        dc_home = tool_data.get("double_chance_home", ToolData())
        dc_away = tool_data.get("double_chance_away", ToolData())
        if dc_home.is_valid and dc_away.is_valid and ftr_data.is_valid:
            ftr = ftr_data.data
            wp = ftr.get("weighted_probabilities", {})
            quality = self._get_quality(ftr)

            # 1X = P(Home) + P(Draw)
            p_1x = wp.get("home_win", 0) + wp.get("draw", 0)
            # X2 = P(Draw) + P(Away)
            p_x2 = wp.get("draw", 0) + wp.get("away_win", 0)
            # 12 = P(Home) + P(Away) = 1 - P(Draw)
            p_12 = 1 - wp.get("draw", 0)

            # Apply penalty to 12 outcome - it excludes draws which makes it riskier
            # 1X and X2 include draws, making them safer bets
            p_12_adjusted = p_12 * DC_12_PENALTY_FACTOR

            outcomes = [
                MarketOutcome("1X", p_1x, dc_home.data.get("weighted_probability", p_1x), quality),
                MarketOutcome("12", p_12, p_12_adjusted, quality),  # Use adjusted prob for selection
                MarketOutcome("X2", p_x2, dc_away.data.get("weighted_probability", p_x2), quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="DC",
                    market_name="Double Chance",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=ftr_data.metadata.get("seasons_analyzed", 0),
                    matches_analyzed=ftr.get("total_matches", 0),
                )
            )

        # Markets 5-9: Over/Under Goals (0.5, 1.5, 2.5, 3.5, 4.5)
        goals_data = tool_data.get("h2h_goals", ToolData())
        if goals_data.is_valid:
            data = goals_data.data
            quality = self._get_quality(data)
            over_thresholds = data.get("over_thresholds", {})
            weighted_probs = data.get("weighted_probabilities", {})

            for threshold in [0.5, 1.5, 2.5, 3.5, 4.5]:
                threshold_key = f"over_{threshold}"
                over_data = over_thresholds.get(threshold_key, {})
                over_prob = over_data.get("probability", 0)
                weighted_over = weighted_probs.get(f"over_{threshold}", over_prob)

                outcomes = [
                    MarketOutcome(f"Over {threshold}", over_prob, weighted_over, quality),
                    MarketOutcome(f"Under {threshold}", 1 - over_prob, 1 - weighted_over, quality),
                ]
                evaluations.append(
                    MarketEvaluation(
                        market_code=f"OU{threshold}",
                        market_name=f"Total Goals Over/Under {threshold}",
                        outcomes=outcomes,
                        best_outcome=self._get_best_outcome(outcomes),
                        data_quality=quality,
                        seasons_analyzed=goals_data.metadata.get("seasons_analyzed", 0),
                        matches_analyzed=data.get("total_matches", 0),
                    )
                )

        return evaluations

    def _evaluate_halftime_markets(self, tool_data: dict[str, ToolData]) -> list[MarketEvaluation]:
        """Evaluate markets 10-14: HT_1X2, HT_DC, HT_OU0.5-2.5."""
        evaluations: list[MarketEvaluation] = []

        # Market 10: HT_1X2 (Half-Time Result)
        ht_result = tool_data.get("ht_result", ToolData())
        if ht_result.is_valid:
            data = ht_result.data
            wp = data.get("weighted_probabilities", {})
            quality = self._get_quality(data)

            home_ht = data.get("home_leading_ht_probability", 0)
            draw_ht = data.get("draw_ht_probability", 0)
            away_ht = data.get("away_leading_ht_probability", 0)

            outcomes = [
                MarketOutcome("1HT", home_ht, wp.get("home_leading_ht", home_ht), quality),
                MarketOutcome("XHT", draw_ht, wp.get("draw_ht", draw_ht), quality),
                MarketOutcome("2HT", away_ht, wp.get("away_leading_ht", away_ht), quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="HT_1X2",
                    market_name="Half-Time Result",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=ht_result.metadata.get("seasons_analyzed", 0),
                    matches_analyzed=data.get("total_matches", 0),
                )
            )

            # Market 11: HT_DC (Half-Time Double Chance)
            w_home = wp.get("home_leading_ht", home_ht)
            w_draw = wp.get("draw_ht", draw_ht)
            w_away = wp.get("away_leading_ht", away_ht)

            dc_outcomes = [
                MarketOutcome("1X", home_ht + draw_ht, w_home + w_draw, quality),
                MarketOutcome("12", home_ht + away_ht, w_home + w_away, quality),
                MarketOutcome("X2", draw_ht + away_ht, w_draw + w_away, quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="HT_DC",
                    market_name="Half-Time Double Chance",
                    outcomes=dc_outcomes,
                    best_outcome=self._get_best_outcome(dc_outcomes),
                    data_quality=quality,
                    seasons_analyzed=ht_result.metadata.get("seasons_analyzed", 0),
                    matches_analyzed=data.get("total_matches", 0),
                )
            )

        # Markets 12-14: HT_OU (0.5, 1.5, 2.5)
        ht_goals = tool_data.get("ht_goals", ToolData())
        if ht_goals.is_valid:
            data = ht_goals.data
            quality = self._get_quality(data)
            total_ht = data.get("total_ht_goals", {})

            for threshold in [0.5, 1.5, 2.5]:
                over_key = f"over_{threshold}"
                over_prob = total_ht.get(over_key, 0)

                outcomes = [
                    MarketOutcome(f"Over {threshold}", over_prob, over_prob, quality),
                    MarketOutcome(f"Under {threshold}", 1 - over_prob, 1 - over_prob, quality),
                ]
                evaluations.append(
                    MarketEvaluation(
                        market_code=f"HT_OU{threshold}",
                        market_name=f"Half-Time Total Goals Over/Under {threshold}",
                        outcomes=outcomes,
                        best_outcome=self._get_best_outcome(outcomes),
                        data_quality=quality,
                        seasons_analyzed=ht_goals.metadata.get("seasons_analyzed", 0),
                        matches_analyzed=data.get("total_matches", 0),
                    )
                )

        return evaluations

    def _evaluate_2nd_half_markets(self, tool_data: dict[str, ToolData]) -> list[MarketEvaluation]:
        """Evaluate markets 15-18: 2H_DC, 2H_OU0.5-2.5."""
        evaluations: list[MarketEvaluation] = []

        # Market 15: 2H_DC (2nd Half Double Chance)
        result_2h = tool_data.get("2h_result", ToolData())
        if result_2h.is_valid:
            data = result_2h.data
            wp = data.get("weighted_probabilities", {})
            quality = self._get_quality(data)

            home_2h = data.get("home_win_2h_probability", 0)
            draw_2h = data.get("draw_2h_probability", 0)
            away_2h = data.get("away_win_2h_probability", 0)

            w_home = wp.get("home_win_2h", home_2h)
            w_draw = wp.get("draw_2h", draw_2h)
            w_away = wp.get("away_win_2h", away_2h)

            outcomes = [
                MarketOutcome("1X", home_2h + draw_2h, w_home + w_draw, quality),
                MarketOutcome("12", home_2h + away_2h, w_home + w_away, quality),
                MarketOutcome("X2", draw_2h + away_2h, w_draw + w_away, quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="2H_DC",
                    market_name="2nd Half Double Chance",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=result_2h.metadata.get("seasons_analyzed", 0),
                    matches_analyzed=data.get("total_matches", 0),
                )
            )

        # Markets 16-18: 2H_OU (0.5, 1.5, 2.5)
        goals_2h = tool_data.get("2h_goals", ToolData())
        if goals_2h.is_valid:
            data = goals_2h.data
            quality = self._get_quality(data)
            total_2h = data.get("total_2h_goals", {})

            for threshold in [0.5, 1.5, 2.5]:
                over_key = f"over_{threshold}"
                over_prob = total_2h.get(over_key, 0)

                outcomes = [
                    MarketOutcome(f"Over {threshold}", over_prob, over_prob, quality),
                    MarketOutcome(f"Under {threshold}", 1 - over_prob, 1 - over_prob, quality),
                ]
                evaluations.append(
                    MarketEvaluation(
                        market_code=f"2H_OU{threshold}",
                        market_name=f"2nd Half Total Goals Over/Under {threshold}",
                        outcomes=outcomes,
                        best_outcome=self._get_best_outcome(outcomes),
                        data_quality=quality,
                        seasons_analyzed=goals_2h.metadata.get("seasons_analyzed", 0),
                        matches_analyzed=data.get("total_matches", 0),
                    )
                )

        return evaluations

    def _evaluate_team_specific_markets(
        self, tool_data: dict[str, ToolData]
    ) -> list[MarketEvaluation]:
        """Evaluate markets 19-24: HOME_SCORE, AWAY_SCORE, WIN_HALF variants."""
        evaluations: list[MarketEvaluation] = []

        # Markets 19, 23: HOME_SCORE / HOME_TO_SCORE
        home_score = tool_data.get("home_to_score", ToolData())
        if home_score.is_valid:
            data = home_score.data
            quality = self._get_quality(data)
            prob = data.get("home_to_score_probability", 0)
            weighted = data.get("weighted_probability", prob)

            outcomes = [
                MarketOutcome("Yes", prob, weighted, quality),
                MarketOutcome("No", 1 - prob, 1 - weighted, quality),
            ]

            for code, name in [("HOME_SCORE", "Home Team To Score"), ("HOME_TO_SCORE", "Home To Score")]:
                evaluations.append(
                    MarketEvaluation(
                        market_code=code,
                        market_name=name,
                        outcomes=outcomes.copy(),
                        best_outcome=self._get_best_outcome(outcomes),
                        data_quality=quality,
                        seasons_analyzed=home_score.metadata.get("seasons_analyzed", 0),
                        matches_analyzed=data.get("total_matches", 0),
                    )
                )

        # Markets 20, 24: AWAY_SCORE / AWAY_TO_SCORE
        away_score = tool_data.get("away_to_score", ToolData())
        if away_score.is_valid:
            data = away_score.data
            quality = self._get_quality(data)
            prob = data.get("away_to_score_probability", 0)
            weighted = data.get("weighted_probability", prob)

            outcomes = [
                MarketOutcome("Yes", prob, weighted, quality),
                MarketOutcome("No", 1 - prob, 1 - weighted, quality),
            ]

            for code, name in [("AWAY_SCORE", "Away Team To Score"), ("AWAY_TO_SCORE", "Away To Score")]:
                evaluations.append(
                    MarketEvaluation(
                        market_code=code,
                        market_name=name,
                        outcomes=outcomes.copy(),
                        best_outcome=self._get_best_outcome(outcomes),
                        data_quality=quality,
                        seasons_analyzed=away_score.metadata.get("seasons_analyzed", 0),
                        matches_analyzed=data.get("total_matches", 0),
                    )
                )

        # Market 21: HOME_WIN_HALF (Home To Win Either Half)
        home_half = tool_data.get("home_either_half", ToolData())
        if home_half.is_valid:
            data = home_half.data
            probs = data.get("weighted_probabilities", data.get("probabilities", {}))
            quality = self._get_quality(data)
            prob = probs.get("win_either_half", 0)

            outcomes = [
                MarketOutcome("Yes", prob, prob, quality),
                MarketOutcome("No", 1 - prob, 1 - prob, quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="HOME_WIN_HALF",
                    market_name="Home To Win Either Half",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=home_half.metadata.get("seasons_analyzed", 0),
                    matches_analyzed=data.get("total_matches", 0),
                )
            )

        # Market 22: AWAY_WIN_HALF (Away To Win Either Half)
        away_half = tool_data.get("away_either_half", ToolData())
        if away_half.is_valid:
            data = away_half.data
            probs = data.get("weighted_probabilities", data.get("probabilities", {}))
            quality = self._get_quality(data)
            prob = probs.get("win_either_half", 0)

            outcomes = [
                MarketOutcome("Yes", prob, prob, quality),
                MarketOutcome("No", 1 - prob, 1 - prob, quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="AWAY_WIN_HALF",
                    market_name="Away To Win Either Half",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=away_half.metadata.get("seasons_analyzed", 0),
                    matches_analyzed=data.get("total_matches", 0),
                )
            )

        return evaluations

    def _evaluate_htft_market(self, tool_data: dict[str, ToolData]) -> list[MarketEvaluation]:
        """Evaluate market 25: HT/FT (9 combinations)."""
        evaluations: list[MarketEvaluation] = []

        ht_ft = tool_data.get("ht_ft", ToolData())
        if ht_ft.is_valid:
            data = ht_ft.data
            quality = self._get_quality(data)
            outcome_list = data.get("outcomes", [])

            outcomes = []
            for item in outcome_list:
                ht = item.get("halftime", "")
                ft = item.get("fulltime", "")
                prob = item.get("probability", 0)

                # Map to standard codes: 1=Home, X=Draw, 2=Away
                ht_code = {"Home": "1", "Draw": "X", "Away": "2"}.get(ht, "X")
                ft_code = {"Home": "1", "Draw": "X", "Away": "2"}.get(ft, "X")
                code = f"{ht_code}/{ft_code}"

                outcomes.append(MarketOutcome(code, prob, prob, quality))

            if outcomes:
                evaluations.append(
                    MarketEvaluation(
                        market_code="HT/FT",
                        market_name="Half-Time/Full-Time",
                        outcomes=outcomes,
                        best_outcome=self._get_best_outcome(outcomes),
                        data_quality=quality,
                        seasons_analyzed=ht_ft.metadata.get("seasons_analyzed", 0),
                        matches_analyzed=data.get("total_matches", 0),
                    )
                )

        return evaluations

    async def _evaluate_combination_and_markets(
        self, tool_data: dict[str, ToolData]
    ) -> list[MarketEvaluation]:
        """Evaluate AND logic markets (11 markets).

        Markets 26-36:
        - 1X2_OU1.5, 1X2_OU2.5, 1X2_OU3.5, 1X2_OU4.5 (4)
        - 1X2_BTTS (1)
        - DC_OU1.5, DC_OU2.5, DC_OU3.5 (3)
        - DC_BTTS (1)
        - BTTS_OU2.5, BTTS_OU3.5 (2)
        """
        evaluations: list[MarketEvaluation] = []

        # Use existing data for composite calculations
        ftr_data = tool_data.get("h2h_ftr", ToolData())
        goals_data = tool_data.get("h2h_goals", ToolData())
        bts_data = tool_data.get("bts", ToolData())

        if not (ftr_data.is_valid and goals_data.is_valid):
            return evaluations

        ftr = ftr_data.data
        goals = goals_data.data
        wp_ftr = ftr.get("weighted_probabilities", {})
        wp_goals = goals.get("weighted_probabilities", {})
        quality = self._get_quality(ftr)
        matches = ftr.get("total_matches", 0)
        seasons = ftr_data.metadata.get("seasons_analyzed", 0)

        # 1X2 probabilities
        p_home = wp_ftr.get("home_win", 0)
        p_draw = wp_ftr.get("draw", 0)
        p_away = wp_ftr.get("away_win", 0)

        # Markets 26-29: 1X2 & Total Goals (AND logic)
        # For AND logic: P(Result AND Goals) - we use conditional estimates
        # Simplification: P(A AND B) ≈ P(A) × P(B) (independence assumption)
        for threshold in [1.5, 2.5, 3.5, 4.5]:
            over_prob = wp_goals.get(f"over_{threshold}", 0)
            under_prob = 1 - over_prob

            outcomes = [
                # Result AND Over
                MarketOutcome(f"1&Over", p_home * over_prob, p_home * over_prob, quality),
                MarketOutcome(f"X&Over", p_draw * over_prob, p_draw * over_prob, quality),
                MarketOutcome(f"2&Over", p_away * over_prob, p_away * over_prob, quality),
                # Result AND Under
                MarketOutcome(f"1&Under", p_home * under_prob, p_home * under_prob, quality),
                MarketOutcome(f"X&Under", p_draw * under_prob, p_draw * under_prob, quality),
                MarketOutcome(f"2&Under", p_away * under_prob, p_away * under_prob, quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code=f"1X2_OU{threshold}",
                    market_name=f"1X2 & Total Goals {threshold}",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=seasons,
                    matches_analyzed=matches,
                )
            )

        # Market 30: 1X2_BTTS (AND logic)
        if bts_data.is_valid:
            bts = bts_data.data
            p_gg = bts.get("weighted_bts_probability", bts.get("bts_probability", 0))
            p_ng = 1 - p_gg

            outcomes = [
                MarketOutcome("1&GG", p_home * p_gg, p_home * p_gg, quality),
                MarketOutcome("1&NG", p_home * p_ng, p_home * p_ng, quality),
                MarketOutcome("X&GG", p_draw * p_gg, p_draw * p_gg, quality),
                MarketOutcome("X&NG", p_draw * p_ng, p_draw * p_ng, quality),
                MarketOutcome("2&GG", p_away * p_gg, p_away * p_gg, quality),
                MarketOutcome("2&NG", p_away * p_ng, p_away * p_ng, quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="1X2_BTTS",
                    market_name="1X2 & Both Teams To Score",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=seasons,
                    matches_analyzed=matches,
                )
            )

        # Double Chance probabilities
        p_1x = p_home + p_draw
        p_12 = p_home + p_away
        p_x2 = p_draw + p_away

        # Markets 31-33: DC & Total Goals (AND logic)
        for threshold in [1.5, 2.5, 3.5]:
            over_prob = wp_goals.get(f"over_{threshold}", 0)
            under_prob = 1 - over_prob

            outcomes = [
                MarketOutcome("1X&Over", p_1x * over_prob, p_1x * over_prob, quality),
                MarketOutcome("1X&Under", p_1x * under_prob, p_1x * under_prob, quality),
                MarketOutcome("12&Over", p_12 * over_prob, p_12 * over_prob, quality),
                MarketOutcome("12&Under", p_12 * under_prob, p_12 * under_prob, quality),
                MarketOutcome("X2&Over", p_x2 * over_prob, p_x2 * over_prob, quality),
                MarketOutcome("X2&Under", p_x2 * under_prob, p_x2 * under_prob, quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code=f"DC_OU{threshold}",
                    market_name=f"Double Chance & Total Goals {threshold}",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=seasons,
                    matches_analyzed=matches,
                )
            )

        # Market 34: DC_BTTS (AND logic)
        if bts_data.is_valid:
            bts = bts_data.data
            p_gg = bts.get("weighted_bts_probability", bts.get("bts_probability", 0))
            p_ng = 1 - p_gg

            outcomes = [
                MarketOutcome("1X&GG", p_1x * p_gg, p_1x * p_gg, quality),
                MarketOutcome("1X&NG", p_1x * p_ng, p_1x * p_ng, quality),
                MarketOutcome("12&GG", p_12 * p_gg, p_12 * p_gg, quality),
                MarketOutcome("12&NG", p_12 * p_ng, p_12 * p_ng, quality),
                MarketOutcome("X2&GG", p_x2 * p_gg, p_x2 * p_gg, quality),
                MarketOutcome("X2&NG", p_x2 * p_ng, p_x2 * p_ng, quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="DC_BTTS",
                    market_name="Double Chance & Both Teams To Score",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=seasons,
                    matches_analyzed=matches,
                )
            )

        # Markets 35-36: BTTS & Total Goals (AND logic)
        if bts_data.is_valid:
            bts = bts_data.data
            p_gg = bts.get("weighted_bts_probability", bts.get("bts_probability", 0))
            p_ng = 1 - p_gg

            for threshold in [2.5, 3.5]:
                over_prob = wp_goals.get(f"over_{threshold}", 0)
                under_prob = 1 - over_prob

                outcomes = [
                    MarketOutcome("GG+Over", p_gg * over_prob, p_gg * over_prob, quality),
                    MarketOutcome("GG+Under", p_gg * under_prob, p_gg * under_prob, quality),
                    MarketOutcome("NG+Over", p_ng * over_prob, p_ng * over_prob, quality),
                    MarketOutcome("NG+Under", p_ng * under_prob, p_ng * under_prob, quality),
                ]
                evaluations.append(
                    MarketEvaluation(
                        market_code=f"BTTS_OU{threshold}",
                        market_name=f"GG/NG & Total Goal {threshold}",
                        outcomes=outcomes,
                        best_outcome=self._get_best_outcome(outcomes),
                        data_quality=quality,
                        seasons_analyzed=seasons,
                        matches_analyzed=matches,
                    )
                )

        return evaluations

    async def _evaluate_chance_mix_markets(
        self, tool_data: dict[str, ToolData]
    ) -> list[MarketEvaluation]:
        """Evaluate OR logic markets (7 markets).

        Markets 37-43:
        - CHANCEMIX_1X2_OU15, CHANCEMIX_1X2_OU25, CHANCEMIX_1X2_OU35 (3)
        - CHANCEMIX_1X2_BTTS (1)
        - CHANCEMIX_BTTS_OU15, CHANCEMIX_BTTS_OU25, CHANCEMIX_BTTS_OU35 (3)
        """
        evaluations: list[MarketEvaluation] = []

        ftr_data = tool_data.get("h2h_ftr", ToolData())
        goals_data = tool_data.get("h2h_goals", ToolData())
        bts_data = tool_data.get("bts", ToolData())

        if not (ftr_data.is_valid and goals_data.is_valid):
            return evaluations

        ftr = ftr_data.data
        goals = goals_data.data
        wp_ftr = ftr.get("weighted_probabilities", {})
        wp_goals = goals.get("weighted_probabilities", {})
        quality = self._get_quality(ftr)
        matches = ftr.get("total_matches", 0)
        seasons = ftr_data.metadata.get("seasons_analyzed", 0)

        p_home = wp_ftr.get("home_win", 0)
        p_draw = wp_ftr.get("draw", 0)
        p_away = wp_ftr.get("away_win", 0)

        # OR logic: P(A OR B) = P(A) + P(B) - P(A AND B)
        # Using independence: P(A AND B) ≈ P(A) × P(B)

        # Markets 37-39: 1X2 OR Total Goals (OR logic)
        for threshold in [1.5, 2.5, 3.5]:
            over_prob = wp_goals.get(f"over_{threshold}", 0)
            under_prob = 1 - over_prob

            outcomes = [
                # Result OR Over (high probability safety bets)
                MarketOutcome(
                    "1orOver",
                    p_home + over_prob - (p_home * over_prob),
                    p_home + over_prob - (p_home * over_prob),
                    quality,
                ),
                MarketOutcome(
                    "XorOver",
                    p_draw + over_prob - (p_draw * over_prob),
                    p_draw + over_prob - (p_draw * over_prob),
                    quality,
                ),
                MarketOutcome(
                    "2orOver",
                    p_away + over_prob - (p_away * over_prob),
                    p_away + over_prob - (p_away * over_prob),
                    quality,
                ),
                # Result OR Under
                MarketOutcome(
                    "1orUnder",
                    p_home + under_prob - (p_home * under_prob),
                    p_home + under_prob - (p_home * under_prob),
                    quality,
                ),
                MarketOutcome(
                    "XorUnder",
                    p_draw + under_prob - (p_draw * under_prob),
                    p_draw + under_prob - (p_draw * under_prob),
                    quality,
                ),
                MarketOutcome(
                    "2orUnder",
                    p_away + under_prob - (p_away * under_prob),
                    p_away + under_prob - (p_away * under_prob),
                    quality,
                ),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code=f"CHANCEMIX_1X2_OU{int(threshold*10)}",
                    market_name=f"Chance Mix 1X2 or Total Goal {threshold}",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=seasons,
                    matches_analyzed=matches,
                )
            )

        # Market 40: CHANCEMIX_1X2_BTTS (OR logic)
        if bts_data.is_valid:
            bts = bts_data.data
            p_gg = bts.get("weighted_bts_probability", bts.get("bts_probability", 0))
            p_ng = 1 - p_gg

            outcomes = [
                MarketOutcome("1orGG", p_home + p_gg - (p_home * p_gg), p_home + p_gg - (p_home * p_gg), quality),
                MarketOutcome("XorGG", p_draw + p_gg - (p_draw * p_gg), p_draw + p_gg - (p_draw * p_gg), quality),
                MarketOutcome("2orGG", p_away + p_gg - (p_away * p_gg), p_away + p_gg - (p_away * p_gg), quality),
                MarketOutcome("1orNG", p_home + p_ng - (p_home * p_ng), p_home + p_ng - (p_home * p_ng), quality),
                MarketOutcome("XorNG", p_draw + p_ng - (p_draw * p_ng), p_draw + p_ng - (p_draw * p_ng), quality),
                MarketOutcome("2orNG", p_away + p_ng - (p_away * p_ng), p_away + p_ng - (p_away * p_ng), quality),
            ]
            evaluations.append(
                MarketEvaluation(
                    market_code="CHANCEMIX_1X2_BTTS",
                    market_name="Chance Mix 1X2 or GG/NG",
                    outcomes=outcomes,
                    best_outcome=self._get_best_outcome(outcomes),
                    data_quality=quality,
                    seasons_analyzed=seasons,
                    matches_analyzed=matches,
                )
            )

        # Markets 41-43: BTTS OR Total Goals (OR logic)
        if bts_data.is_valid:
            bts = bts_data.data
            p_gg = bts.get("weighted_bts_probability", bts.get("bts_probability", 0))
            p_ng = 1 - p_gg

            for threshold in [1.5, 2.5, 3.5]:
                over_prob = wp_goals.get(f"over_{threshold}", 0)
                under_prob = 1 - over_prob

                outcomes = [
                    MarketOutcome(
                        "GGorOver",
                        p_gg + over_prob - (p_gg * over_prob),
                        p_gg + over_prob - (p_gg * over_prob),
                        quality,
                    ),
                    MarketOutcome(
                        "GGorUnder",
                        p_gg + under_prob - (p_gg * under_prob),
                        p_gg + under_prob - (p_gg * under_prob),
                        quality,
                    ),
                    MarketOutcome(
                        "NGorOver",
                        p_ng + over_prob - (p_ng * over_prob),
                        p_ng + over_prob - (p_ng * over_prob),
                        quality,
                    ),
                    MarketOutcome(
                        "NGorUnder",
                        p_ng + under_prob - (p_ng * under_prob),
                        p_ng + under_prob - (p_ng * under_prob),
                        quality,
                    ),
                ]
                evaluations.append(
                    MarketEvaluation(
                        market_code=f"CHANCEMIX_BTTS_OU{int(threshold*10)}",
                        market_name=f"Chance Mix GG/NG or Total {threshold}",
                        outcomes=outcomes,
                        best_outcome=self._get_best_outcome(outcomes),
                        data_quality=quality,
                        seasons_analyzed=seasons,
                        matches_analyzed=matches,
                    )
                )

        return evaluations

    def _evaluate_advanced_markets(self, tool_data: dict[str, ToolData]) -> list[MarketEvaluation]:
        """Evaluate market 44: MULTI_GOAL (goal ranges)."""
        evaluations: list[MarketEvaluation] = []

        goals_range = tool_data.get("total_goals_range", ToolData())
        if goals_range.is_valid:
            data = goals_range.data
            quality = self._get_quality(data)
            dist = data.get("goal_distribution", {})
            wp = data.get("weighted_probabilities", dist)

            # Build outcomes for each goal range
            outcomes = []
            for range_key in ["0-1", "2-3", "4-5", "6+"]:
                prob = dist.get(range_key, 0)
                if isinstance(prob, dict):
                    prob = prob.get("probability", 0)
                weighted = wp.get(range_key, prob)
                if isinstance(weighted, dict):
                    weighted = weighted.get("probability", prob)

                outcomes.append(
                    MarketOutcome(f"{range_key} goals", prob, weighted, quality)
                )

            if outcomes:
                evaluations.append(
                    MarketEvaluation(
                        market_code="MULTI_GOAL",
                        market_name="Multi Goal",
                        outcomes=outcomes,
                        best_outcome=self._get_best_outcome(outcomes),
                        data_quality=quality,
                        seasons_analyzed=goals_range.metadata.get("seasons_analyzed", 0),
                        matches_analyzed=data.get("total_matches", 0),
                    )
                )

        return evaluations
