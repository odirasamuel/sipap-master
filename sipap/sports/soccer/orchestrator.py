"""Soccer Orchestrator - Coordinates all agents to generate ensemble predictions.

Pattern adapted from Sentinel's multi-agent workflow system.

Phase 4: Now includes MCP integration for data aggregation and validation.
"""

import asyncio
import logging
import statistics
from collections import Counter
from datetime import datetime
from typing import Any

from sipap.factory.agent import AgentToolFactory
from sipap.factory.mcp import MCPFactory


class SoccerOrchestrator:
    """
    Coordinates 5 specialized agents to generate ensemble predictions.

    Agents:
    1. Statistical Agent - Poisson, xG, Elo
    2. ML Agent - XGBoost model
    3. Form Agent - Recent form analysis
    4. Market Agent - Betting market sentiment
    5. News Agent - Contextual news analysis

    This is a simplified implementation focusing on ensemble logic and quality gates.
    """

    def __init__(self, logger: logging.Logger | None = None):
        """
        Initialize the orchestrator.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        # Initialize AgentToolFactory
        self.agent_factory = AgentToolFactory(sport="soccer", logger=self.logger)

        # Initialize MCPFactory for data aggregation
        self.mcp_factory = MCPFactory(logger=self.logger)

        self.logger.info("SoccerOrchestrator initialized")

    async def aggregate_context(self, match_id: str) -> dict[str, Any]:
        """
        Aggregate context from all MCP servers in parallel.

        Fetches data from:
        - Sports Data MCP: fixtures, stats, odds, form
        - Intelligence MCP: weather, injuries, news

        Args:
            match_id: Match identifier (e.g., "12345")

        Returns:
            Aggregated context dictionary with all data

        Raises:
            Exception: If critical data cannot be fetched
        """
        self.logger.info(f"Aggregating context for match {match_id}")

        # Create MCP clients
        data_mcp = self.mcp_factory.create("data")
        intelligence_mcp = self.mcp_factory.create("intelligence")

        # Parse match_id to extract team names (temporary - will use proper ID lookup later)
        # For now, assume match_id format is "home_team_vs_away_team"
        teams = match_id.split("_vs_")
        home_team = teams[0] if len(teams) > 0 else "unknown"
        away_team = teams[1] if len(teams) > 1 else "unknown"

        try:
            # Fetch all data in parallel
            results = await asyncio.gather(
                # Sports data
                data_mcp.call_tool("get_match_schedule", {"match_id": match_id}),
                data_mcp.call_tool("get_team_stats", {"team": home_team}),
                data_mcp.call_tool("get_team_stats", {"team": away_team}),
                data_mcp.call_tool("get_head_to_head", {"home_team": home_team, "away_team": away_team}),
                data_mcp.call_tool("get_recent_form", {"team": home_team}),
                data_mcp.call_tool("get_recent_form", {"team": away_team}),
                data_mcp.call_tool("get_match_odds", {"match_id": match_id}),
                # Intelligence data
                intelligence_mcp.call_tool("get_match_weather", {"match_id": match_id}),
                intelligence_mcp.call_tool("get_injury_reports", {"team": home_team}),
                intelligence_mcp.call_tool("get_injury_reports", {"team": away_team}),
                return_exceptions=True,
            )

            # Unpack results
            (
                fixture,
                home_stats,
                away_stats,
                head_to_head,
                home_form,
                away_form,
                odds,
                weather,
                home_injuries,
                away_injuries,
            ) = results

            # Build aggregated context
            context = {
                "match_id": match_id,
                "fixture": fixture if not isinstance(fixture, Exception) else None,
                "home_team": {
                    "name": home_team,
                    "stats": home_stats if not isinstance(home_stats, Exception) else None,
                    "form": home_form if not isinstance(home_form, Exception) else None,
                    "injuries": home_injuries if not isinstance(home_injuries, Exception) else None,
                },
                "away_team": {
                    "name": away_team,
                    "stats": away_stats if not isinstance(away_stats, Exception) else None,
                    "form": away_form if not isinstance(away_form, Exception) else None,
                    "injuries": away_injuries if not isinstance(away_injuries, Exception) else None,
                },
                "head_to_head": head_to_head if not isinstance(head_to_head, Exception) else None,
                "odds": odds if not isinstance(odds, Exception) else None,
                "weather": weather if not isinstance(weather, Exception) else None,
            }

            self.logger.info(
                f"Context aggregation complete for match {match_id}",
                extra={"data_points": len([v for v in context.values() if v is not None])},
            )

            return context

        except Exception as e:
            self.logger.error(
                f"Failed to aggregate context for match {match_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise

    def validate_context_quality(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Validate that aggregated context has sufficient data quality.

        Quality checks:
        1. Critical fields present (fixture, odds, team stats)
        2. At least 70% of data points available
        3. No critical data fetch failures

        Args:
            context: Aggregated context dictionary

        Returns:
            Validation result with status and missing fields
        """
        self.logger.debug("Validating context quality")

        # Define critical fields
        critical_fields = [
            ("fixture", context.get("fixture")),
            ("odds", context.get("odds")),
            ("home_stats", context.get("home_team", {}).get("stats")),
            ("away_stats", context.get("away_team", {}).get("stats")),
        ]

        # Define optional fields (nice to have)
        optional_fields = [
            ("home_form", context.get("home_team", {}).get("form")),
            ("away_form", context.get("away_team", {}).get("form")),
            ("home_injuries", context.get("home_team", {}).get("injuries")),
            ("away_injuries", context.get("away_team", {}).get("injuries")),
            ("head_to_head", context.get("head_to_head")),
            ("weather", context.get("weather")),
        ]

        # Check critical fields
        missing_critical = [name for name, value in critical_fields if value is None]
        if missing_critical:
            return {
                "status": "FAILED",
                "reason": f"Missing critical fields: {', '.join(missing_critical)}",
                "missing_critical": missing_critical,
                "missing_optional": [],
                "data_completeness": 0.0,
            }

        # Check optional fields
        missing_optional = [name for name, value in optional_fields if value is None]
        total_fields = len(critical_fields) + len(optional_fields)
        available_fields = total_fields - len(missing_optional)
        data_completeness = (available_fields / total_fields) * 100

        # Quality gate: At least 70% data completeness
        if data_completeness < 70:
            return {
                "status": "FAILED",
                "reason": f"Data completeness below threshold: {data_completeness:.1f}% < 70%",
                "missing_critical": [],
                "missing_optional": missing_optional,
                "data_completeness": data_completeness,
            }

        # All gates passed
        self.logger.info(
            "Context validation passed",
            extra={"data_completeness": data_completeness},
        )

        return {
            "status": "PASSED",
            "reason": "All quality checks passed",
            "missing_critical": [],
            "missing_optional": missing_optional,
            "data_completeness": data_completeness,
        }

    async def save_prediction(
        self,
        match_id: str,
        prediction: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Save prediction to Aurora database for audit and analysis.

        Stores:
        - Prediction metadata (timestamp, match_id, market, outcome)
        - Ensemble results (probability, confidence, quality_gate)
        - Agent predictions (all 5 agent outputs)
        - Context data (aggregated match data)
        - Expected value calculation

        Args:
            match_id: Match identifier
            prediction: Final ensemble prediction
            context: Aggregated match context

        Returns:
            Save result with prediction_id

        Note:
            This is a placeholder implementation. Full Aurora integration
            will be added when database infrastructure is ready.
        """
        self.logger.info(f"Saving prediction for match {match_id}")

        # Build prediction record
        prediction_record = {
            "prediction_id": f"{match_id}_{datetime.now().isoformat()}",
            "match_id": match_id,
            "timestamp": datetime.now().isoformat(),
            "market": prediction.get("market"),
            "outcome": prediction.get("outcome"),
            "probability": prediction.get("probability"),
            "confidence": prediction.get("confidence"),
            "quality_gate": prediction.get("quality_gate"),
            "recommendation": prediction.get("recommendation"),
            "expected_value": prediction.get("expected_value"),
            "agent_predictions": prediction.get("agent_predictions", []),
            "reasoning": prediction.get("reasoning"),
            "evidence": prediction.get("evidence", []),
            "context_summary": {
                "home_team": context.get("home_team", {}).get("name"),
                "away_team": context.get("away_team", {}).get("name"),
                "data_completeness": context.get("data_completeness", 0),
            },
        }

        # TODO: Integrate with Aurora database
        # For now, log the record and return success
        self.logger.info(
            "Prediction record prepared (Aurora integration pending)",
            extra={
                "prediction_id": prediction_record["prediction_id"],
                "quality_gate": prediction_record["quality_gate"],
            },
        )

        return {
            "status": "SUCCESS",
            "prediction_id": prediction_record["prediction_id"],
            "message": "Prediction saved (Aurora integration pending)",
        }

    def calculate_expected_value(
        self,
        prediction: dict[str, Any],
        odds: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Calculate expected value (+EV) for a prediction.

        Expected Value (EV) formula:
            EV = (Probability × Payout) - (1 - Probability × Stake)
            +EV when: Our probability > Implied probability from odds

        Args:
            prediction: Ensemble prediction with probability
            odds: Market odds for the outcome

        Returns:
            Expected value analysis with recommendation

        Example:
            >>> prediction = {"outcome": "Home Win", "probability": 0.60}
            >>> odds = {"Home Win": 2.0}  # Decimal odds
            >>> result = calculate_expected_value(prediction, odds)
            >>> print(result)
            {
                "expected_value": 0.20,
                "is_positive_ev": True,
                "recommendation": "PLACE BET",
                ...
            }
        """
        outcome_raw = prediction.get("outcome")
        our_probability = prediction.get("probability", 0)

        # Ensure outcome is a string
        if not isinstance(outcome_raw, str):
            return {
                "expected_value": 0.0,
                "is_positive_ev": False,
                "recommendation": "SKIP - Invalid outcome type",
                "reason": "Outcome must be a string",
            }

        outcome: str = outcome_raw

        # Get odds for this outcome
        outcome_odds = odds.get(outcome)
        if not outcome_odds:
            return {
                "expected_value": 0.0,
                "is_positive_ev": False,
                "recommendation": "SKIP - No odds available",
                "reason": f"No odds found for outcome: {outcome}",
            }

        # Convert decimal odds to implied probability
        # Implied probability = 1 / decimal_odds
        implied_probability = 1 / outcome_odds

        # Calculate expected value
        # EV = (our_prob × (odds - 1)) - ((1 - our_prob) × 1)
        # Simplified: EV = (our_prob × odds) - 1
        expected_value = (our_probability * outcome_odds) - 1

        # +EV threshold: At least 5% edge
        ev_threshold = 0.05
        is_positive_ev = expected_value >= ev_threshold

        # Edge calculation
        edge = our_probability - implied_probability

        self.logger.info(
            "Expected value calculated",
            extra={
                "outcome": outcome,
                "our_probability": our_probability,
                "implied_probability": implied_probability,
                "expected_value": expected_value,
                "edge": edge,
                "is_positive_ev": is_positive_ev,
            },
        )

        # Build recommendation
        if is_positive_ev and edge > 0.1:
            recommendation = "STRONG BET - High +EV opportunity"
        elif is_positive_ev:
            recommendation = "PLACE BET - Positive expected value"
        elif expected_value > 0:
            recommendation = "MARGINAL - Small +EV, below threshold"
        else:
            recommendation = "SKIP - Negative expected value"

        return {
            "expected_value": round(expected_value, 4),
            "edge": round(edge, 4),
            "is_positive_ev": is_positive_ev,
            "our_probability": round(our_probability, 4),
            "implied_probability": round(implied_probability, 4),
            "odds": outcome_odds,
            "recommendation": recommendation,
        }

    def _calculate_ensemble(self, agent_predictions: list[dict[str, Any]], market: str) -> dict[str, Any]:
        """
        Calculate weighted ensemble from all agent predictions.

        Args:
            agent_predictions: List of predictions from all agents
            market: Betting market (1X2, BTTS, OU2.5)

        Returns:
            Ensemble prediction dictionary
        """
        # Weighted average (weights based on historical accuracy)
        weights = {
            "statistical": 0.25,
            "ml": 0.30,
            "form": 0.20,
            "market": 0.15,
            "news": 0.10
        }

        # Extract probabilities and calculate weighted average
        probabilities = [
            p["prediction"]["probability"] * weights[p["agent"]]
            for p in agent_predictions
        ]

        ensemble_probability = sum(probabilities)

        # Confidence based on agent agreement
        confidence = self._calculate_agreement(agent_predictions)

        return {
            "market": market,
            "outcome": self._select_outcome(agent_predictions),
            "probability": round(ensemble_probability, 4),
            "confidence": round(confidence, 0),
            "agent_predictions": agent_predictions,
            "reasoning": self._generate_reasoning(agent_predictions),
            "evidence": self._aggregate_evidence(agent_predictions)
        }

    def _calculate_agreement(self, predictions: list[dict[str, Any]]) -> float:
        """
        Calculate confidence from agent agreement.

        Args:
            predictions: List of agent predictions

        Returns:
            Confidence score (0-100)
        """
        # Extract probabilities
        probs = [p["prediction"]["probability"] for p in predictions]

        # Standard deviation of probabilities
        std_dev = statistics.stdev(probs) if len(probs) > 1 else 0

        # Low std dev = high agreement = high confidence
        # Scale std_dev more aggressively: std_dev of 0.3 → ~40% confidence
        # Formula: confidence = (1 - min(std_dev * 2, 1.0)) * 100
        confidence = (1 - min(std_dev * 2, 1.0)) * 100

        return max(0, min(100, confidence))

    def _select_outcome(self, predictions: list[dict[str, Any]]) -> str:
        """
        Select most common outcome from agents (majority vote).

        Args:
            predictions: List of agent predictions

        Returns:
            Most common outcome
        """
        outcomes = [p["prediction"]["outcome"] for p in predictions]
        most_common = Counter(outcomes).most_common(1)
        return str(most_common[0][0]) if most_common else ""

    def _generate_reasoning(self, predictions: list[dict[str, Any]]) -> str:
        """
        Aggregate reasoning from all agents.

        Args:
            predictions: List of agent predictions

        Returns:
            Combined reasoning string
        """
        reasons = [f"{p['agent']}: {p['reasoning']}" for p in predictions]
        return " | ".join(reasons)

    def _aggregate_evidence(self, predictions: list[dict[str, Any]]) -> list[str]:
        """
        Aggregate evidence from all agents.

        Args:
            predictions: List of agent predictions

        Returns:
            List of all evidence items
        """
        evidence = []
        for p in predictions:
            evidence.extend(p.get("evidence", []))
        return evidence

    def _apply_quality_gates(self, ensemble: dict[str, Any], agent_predictions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Apply quality gates to final prediction.

        Quality Gates:
        1. Minimum confidence threshold (55%)
        2. Minimum probability threshold (50%)
        3. Minimum agent consensus (3/5 agents agree)

        Args:
            ensemble: Ensemble prediction
            agent_predictions: List of agent predictions

        Returns:
            Prediction with quality gate status
        """
        # Quality Gate 1: Minimum confidence threshold
        if ensemble["confidence"] < 55:
            return {
                **ensemble,
                "quality_gate": "FAILED",
                "reason": "Confidence below threshold (55%)",
                "recommendation": "Do not place bet"
            }

        # Quality Gate 2: Minimum probability threshold
        if ensemble["probability"] < 0.50:
            return {
                **ensemble,
                "quality_gate": "FAILED",
                "reason": "Probability below threshold (50%)",
                "recommendation": "Do not place bet"
            }

        # Quality Gate 3: Agent consensus (at least 3/5 agree)
        outcome_counts = Counter([p["prediction"]["outcome"] for p in agent_predictions])
        max_count = max(outcome_counts.values())
        if max_count < 3:
            return {
                **ensemble,
                "quality_gate": "FAILED",
                "reason": "Insufficient agent consensus (< 3/5)",
                "recommendation": "Do not place bet"
            }

        # All gates passed
        return {
            **ensemble,
            "quality_gate": "PASSED",
            "recommendation": "Prediction ready for user"
        }
