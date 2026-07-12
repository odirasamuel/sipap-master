"""Soccer Orchestrator - Coordinates all agents to generate ensemble predictions.

Pattern adapted from Sentinel's multi-agent workflow system.

NOTE: This is a simplified implementation for Phase 3 MVP.
Full MCP integration and async execution will be added in later phases.
"""

import logging
import statistics
from collections import Counter
from typing import List, Optional

from sipap.factory.agent import AgentToolFactory


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

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the orchestrator.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        # Initialize AgentToolFactory
        self.agent_factory = AgentToolFactory(sport="soccer", logger=self.logger)

        self.logger.info("SoccerOrchestrator initialized")

    def _calculate_ensemble(self, agent_predictions: List[dict], market: str) -> dict:
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

    def _calculate_agreement(self, predictions: List[dict]) -> float:
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

    def _select_outcome(self, predictions: List[dict]) -> str:
        """
        Select most common outcome from agents (majority vote).

        Args:
            predictions: List of agent predictions

        Returns:
            Most common outcome
        """
        outcomes = [p["prediction"]["outcome"] for p in predictions]
        return Counter(outcomes).most_common(1)[0][0]

    def _generate_reasoning(self, predictions: List[dict]) -> str:
        """
        Aggregate reasoning from all agents.

        Args:
            predictions: List of agent predictions

        Returns:
            Combined reasoning string
        """
        reasons = [f"{p['agent']}: {p['reasoning']}" for p in predictions]
        return " | ".join(reasons)

    def _aggregate_evidence(self, predictions: List[dict]) -> List[str]:
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

    def _apply_quality_gates(self, ensemble: dict, agent_predictions: List[dict]) -> dict:
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
