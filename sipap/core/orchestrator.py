"""Main Orchestrator - Sport-agnostic routing to specialized orchestrators.

Pattern adapted from Sentinel's routing and delegation patterns.

This orchestrator provides a unified API for all sports and routes requests
to sport-specific orchestrators (SoccerOrchestrator, BasketballOrchestrator, etc.).
"""

import logging
from typing import Any

from sipap.sports.soccer.orchestrator import SoccerOrchestrator


class MainOrchestrator:
    """
    Main orchestrator that routes prediction requests to sport-specific orchestrators.

    Supports:
    - Soccer (current)
    - Basketball (future)
    - Tennis (future)
    - American Football (future)

    Example:
        >>> orchestrator = MainOrchestrator()
        >>> prediction = await orchestrator.predict(
        ...     sport="soccer",
        ...     match_id="12345",
        ...     market="1X2"
        ... )
    """

    def __init__(self, logger: logging.Logger | None = None):
        """
        Initialize the main orchestrator.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        # Register sport-specific orchestrators
        self._orchestrators: dict[str, Any] = {
            "soccer": SoccerOrchestrator(logger=self.logger),
            # Future: "basketball": BasketballOrchestrator(logger=self.logger),
            # Future: "tennis": TennisOrchestrator(logger=self.logger),
        }

        self.logger.info(
            "MainOrchestrator initialized",
            extra={"supported_sports": list(self._orchestrators.keys())},
        )

    def get_supported_sports(self) -> list[str]:
        """
        Get list of supported sports.

        Returns:
            List of sport identifiers
        """
        return list(self._orchestrators.keys())

    async def predict(
        self,
        sport: str,
        match_id: str,
        market: str,
    ) -> dict[str, Any]:
        """
        Generate prediction for a match.

        This is the main entry point for all prediction requests. It:
        1. Routes to appropriate sport orchestrator
        2. Aggregates context from MCP servers
        3. Validates context quality
        4. Runs ensemble prediction
        5. Calculates expected value
        6. Applies quality gates
        7. Saves prediction
        8. Returns final recommendation

        Args:
            sport: Sport identifier (e.g., "soccer", "basketball")
            match_id: Match identifier
            market: Betting market (e.g., "1X2", "BTTS", "OU2.5")
            **kwargs: Additional sport-specific parameters

        Returns:
            Final prediction with recommendation

        Raises:
            ValueError: If sport not supported or invalid parameters

        Example:
            >>> prediction = await orchestrator.predict(
            ...     sport="soccer",
            ...     match_id="Man_United_vs_Liverpool",
            ...     market="1X2"
            ... )
            >>> print(prediction["recommendation"])
            "PLACE BET - Positive expected value"
        """
        self.logger.info(
            "Prediction request received",
            extra={"sport": sport, "match_id": match_id, "market": market},
        )

        # Validate sport
        if sport not in self._orchestrators:
            supported = list(self._orchestrators.keys())
            raise ValueError(
                f"Sport '{sport}' not supported. Available sports: {supported}"
            )

        # Get sport-specific orchestrator
        orchestrator = self._orchestrators[sport]

        # Step 1: Aggregate context from MCP servers
        self.logger.debug("Step 1: Aggregating context from MCP servers")
        context = await orchestrator.aggregate_context(match_id)

        # Step 2: Validate context quality
        self.logger.debug("Step 2: Validating context quality")
        validation = orchestrator.validate_context_quality(context)

        if validation["status"] == "FAILED":
            return {
                "status": "FAILED",
                "reason": validation["reason"],
                "recommendation": "SKIP - Insufficient data quality",
                "validation": validation,
            }

        # Step 3: Run ensemble prediction (simplified for now)
        # TODO: Integrate with actual agent execution
        self.logger.debug("Step 3: Running ensemble prediction")

        # Placeholder: Mock agent predictions for MVP
        agent_predictions = self._mock_agent_predictions(market)

        # Calculate ensemble
        ensemble = orchestrator._calculate_ensemble(agent_predictions, market)

        # Step 4: Calculate expected value
        self.logger.debug("Step 4: Calculating expected value")
        odds = context.get("odds", {})
        ev_analysis = orchestrator.calculate_expected_value(ensemble, odds)

        # Add EV to ensemble
        ensemble["expected_value"] = ev_analysis

        # Step 5: Apply quality gates
        self.logger.debug("Step 5: Applying quality gates")
        final_prediction: dict[str, Any] = orchestrator._apply_quality_gates(ensemble, agent_predictions)

        # Step 6: Save prediction
        self.logger.debug("Step 6: Saving prediction to database")
        save_result = await orchestrator.save_prediction(match_id, final_prediction, context)

        # Add save result to prediction
        final_prediction["save_result"] = save_result

        self.logger.info(
            "Prediction complete",
            extra={
                "match_id": match_id,
                "quality_gate": final_prediction.get("quality_gate"),
                "recommendation": final_prediction.get("recommendation"),
                "prediction_id": save_result.get("prediction_id"),
            },
        )

        return final_prediction

    def _mock_agent_predictions(self, market: str) -> list[dict[str, Any]]:
        """
        Mock agent predictions for testing.

        TODO: Remove this when actual agent execution is integrated.
        TODO: Use market parameter to generate market-specific predictions.

        Args:
            market: Betting market (not used in mock, reserved for future)

        Returns:
            List of mock agent predictions
        """
        # Note: market parameter reserved for future use
        _ = market  # Suppress unused warning

        # Mock predictions for 5 agents
        return [
            {
                "agent": "statistical",
                "prediction": {"outcome": "Home Win", "probability": 0.55},
                "reasoning": "Poisson model favors home team",
                "evidence": ["Home team xG: 1.8", "Away team xG: 1.2"],
            },
            {
                "agent": "ml",
                "prediction": {"outcome": "Home Win", "probability": 0.60},
                "reasoning": "XGBoost model prediction",
                "evidence": ["Model confidence: 85%"],
            },
            {
                "agent": "form",
                "prediction": {"outcome": "Home Win", "probability": 0.52},
                "reasoning": "Home team in better form",
                "evidence": ["Home form: WWDWL", "Away form: LLWDD"],
            },
            {
                "agent": "market",
                "prediction": {"outcome": "Home Win", "probability": 0.58},
                "reasoning": "Betting market sentiment",
                "evidence": ["Market probability: 58%"],
            },
            {
                "agent": "news",
                "prediction": {"outcome": "Home Win", "probability": 0.50},
                "reasoning": "Neutral news impact",
                "evidence": ["No significant team news"],
            },
        ]
