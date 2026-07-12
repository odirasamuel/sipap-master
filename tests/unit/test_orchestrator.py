"""Unit tests for SoccerOrchestrator.

Following TDD methodology:
1. RED: Write failing tests
2. GREEN: Implement minimal code to pass
3. REFACTOR: Improve implementation

NOTE: This is a simplified implementation for Phase 3 MVP.
Full MCP integration will be added in later phases.
"""

import pytest

from sipap.sports.soccer.orchestrator import SoccerOrchestrator


class TestSoccerOrchestratorInit:
    """Test suite for orchestrator initialization."""

    def test_orchestrator_initialization(self):
        """Test orchestrator initializes correctly."""
        orchestrator = SoccerOrchestrator()

        # Verify orchestrator has logger
        assert orchestrator.logger is not None

    def test_orchestrator_with_custom_logger(self):
        """Test orchestrator accepts custom logger."""
        import logging
        custom_logger = logging.getLogger("test")

        orchestrator = SoccerOrchestrator(logger=custom_logger)

        assert orchestrator.logger == custom_logger

    def test_orchestrator_has_agent_factory(self):
        """Test orchestrator has AgentToolFactory."""
        orchestrator = SoccerOrchestrator()

        assert hasattr(orchestrator, 'agent_factory')
        assert orchestrator.agent_factory is not None


class TestEnsembleCalculation:
    """Test suite for ensemble calculation logic."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance for testing."""
        return SoccerOrchestrator()

    @pytest.fixture
    def sample_agent_predictions(self):
        """Sample agent predictions for testing."""
        return [
            {
                "agent": "statistical",
                "prediction": {
                    "market": "1X2",
                    "outcome": "home_win",
                    "probability": 0.65,
                    "confidence": 70
                },
                "reasoning": "Statistical analysis favors home team",
                "evidence": ["Home team has 70% win rate", "Strong Elo rating"]
            },
            {
                "agent": "ml",
                "prediction": {
                    "market": "1X2",
                    "outcome": "home_win",
                    "probability": 0.68,
                    "confidence": 75
                },
                "reasoning": "ML model predicts home win",
                "evidence": ["Model confidence: 75%"]
            },
            {
                "agent": "form",
                "prediction": {
                    "market": "1X2",
                    "outcome": "home_win",
                    "probability": 0.62,
                    "confidence": 65
                },
                "reasoning": "Home team in better form",
                "evidence": ["5-match win streak"]
            },
            {
                "agent": "market",
                "prediction": {
                    "market": "1X2",
                    "outcome": "draw",
                    "probability": 0.45,
                    "confidence": 50
                },
                "reasoning": "Market suggests close match",
                "evidence": ["Odds imply tight contest"]
            },
            {
                "agent": "news",
                "prediction": {
                    "market": "1X2",
                    "outcome": "home_win",
                    "probability": 0.58,
                    "confidence": 60
                },
                "reasoning": "No major injuries for home team",
                "evidence": ["Full squad available"]
            }
        ]

    def test_calculate_ensemble_structure(self, orchestrator, sample_agent_predictions):
        """Test ensemble calculation returns correct structure."""
        ensemble = orchestrator._calculate_ensemble(sample_agent_predictions, "1X2")

        # Verify structure
        assert "market" in ensemble
        assert "outcome" in ensemble
        assert "probability" in ensemble
        assert "confidence" in ensemble
        assert "agent_predictions" in ensemble
        assert "reasoning" in ensemble
        assert "evidence" in ensemble

    def test_calculate_ensemble_probability(self, orchestrator, sample_agent_predictions):
        """Test ensemble probability calculation."""
        ensemble = orchestrator._calculate_ensemble(sample_agent_predictions, "1X2")

        # Probability should be between 0 and 1
        assert 0 <= ensemble["probability"] <= 1
        # Should be rounded to 4 decimal places
        assert isinstance(ensemble["probability"], float)

    def test_calculate_ensemble_confidence(self, orchestrator, sample_agent_predictions):
        """Test ensemble confidence calculation."""
        ensemble = orchestrator._calculate_ensemble(sample_agent_predictions, "1X2")

        # Confidence should be between 0 and 100
        assert 0 <= ensemble["confidence"] <= 100
        assert isinstance(ensemble["confidence"], (int, float))

    def test_select_outcome_majority_vote(self, orchestrator, sample_agent_predictions):
        """Test outcome selection by majority vote."""
        outcome = orchestrator._select_outcome(sample_agent_predictions)

        # 4 out of 5 agents predict "home_win"
        assert outcome == "home_win"

    def test_calculate_agreement_high(self, orchestrator):
        """Test agreement calculation for high consensus."""
        # All agents predict similar probabilities
        predictions = [
            {"prediction": {"probability": 0.65}},
            {"prediction": {"probability": 0.67}},
            {"prediction": {"probability": 0.66}},
            {"prediction": {"probability": 0.64}},
            {"prediction": {"probability": 0.65}}
        ]

        confidence = orchestrator._calculate_agreement(predictions)

        # Low standard deviation → high confidence
        assert confidence > 80

    def test_calculate_agreement_low(self, orchestrator):
        """Test agreement calculation for low consensus."""
        # Agents disagree significantly
        predictions = [
            {"prediction": {"probability": 0.2}},
            {"prediction": {"probability": 0.9}},
            {"prediction": {"probability": 0.4}},
            {"prediction": {"probability": 0.7}},
            {"prediction": {"probability": 0.5}}
        ]

        confidence = orchestrator._calculate_agreement(predictions)

        # High standard deviation → low confidence
        assert confidence < 50

    def test_generate_reasoning(self, orchestrator, sample_agent_predictions):
        """Test reasoning aggregation."""
        reasoning = orchestrator._generate_reasoning(sample_agent_predictions)

        # Should combine all agent reasoning
        assert "statistical" in reasoning
        assert "ml" in reasoning
        assert "form" in reasoning
        assert "market" in reasoning
        assert "news" in reasoning
        assert isinstance(reasoning, str)

    def test_aggregate_evidence(self, orchestrator, sample_agent_predictions):
        """Test evidence aggregation."""
        evidence = orchestrator._aggregate_evidence(sample_agent_predictions)

        # Should be a list
        assert isinstance(evidence, list)
        # Should have multiple evidence items
        assert len(evidence) > 0
        # All items should be strings
        assert all(isinstance(e, str) for e in evidence)


class TestQualityGates:
    """Test suite for quality gates."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance."""
        return SoccerOrchestrator()

    @pytest.fixture
    def passing_ensemble(self):
        """Ensemble that should pass all quality gates."""
        return {
            "market": "1X2",
            "outcome": "home_win",
            "probability": 0.65,
            "confidence": 70,
            "agent_predictions": [
                {"prediction": {"outcome": "home_win"}},
                {"prediction": {"outcome": "home_win"}},
                {"prediction": {"outcome": "home_win"}},
                {"prediction": {"outcome": "draw"}},
                {"prediction": {"outcome": "home_win"}}
            ],
            "reasoning": "Strong consensus",
            "evidence": ["Evidence 1", "Evidence 2"]
        }

    def test_quality_gate_passed(self, orchestrator, passing_ensemble):
        """Test quality gates pass for good prediction."""
        result = orchestrator._apply_quality_gates(
            passing_ensemble,
            passing_ensemble["agent_predictions"]
        )

        assert result["quality_gate"] == "PASSED"
        assert result["recommendation"] == "Prediction ready for user"

    def test_quality_gate_low_confidence(self, orchestrator):
        """Test quality gate fails for low confidence."""
        ensemble = {
            "confidence": 40,  # Below 55 threshold
            "probability": 0.65,
            "agent_predictions": []
        }

        result = orchestrator._apply_quality_gates(ensemble, [])

        assert result["quality_gate"] == "FAILED"
        assert "Confidence below threshold" in result["reason"]
        assert result["recommendation"] == "Do not place bet"

    def test_quality_gate_low_probability(self, orchestrator):
        """Test quality gate fails for low probability."""
        ensemble = {
            "confidence": 70,
            "probability": 0.45,  # Below 0.50 threshold
            "agent_predictions": []
        }

        result = orchestrator._apply_quality_gates(ensemble, [])

        assert result["quality_gate"] == "FAILED"
        assert "Probability below threshold" in result["reason"]

    def test_quality_gate_no_consensus(self, orchestrator):
        """Test quality gate fails without agent consensus."""
        ensemble = {
            "confidence": 70,
            "probability": 0.65,
            "agent_predictions": [
                {"prediction": {"outcome": "home_win"}},
                {"prediction": {"outcome": "draw"}},
                {"prediction": {"outcome": "away_win"}},
                {"prediction": {"outcome": "draw"}},
                {"prediction": {"outcome": "away_win"}}
            ]
        }

        result = orchestrator._apply_quality_gates(
            ensemble,
            ensemble["agent_predictions"]
        )

        assert result["quality_gate"] == "FAILED"
        assert "Insufficient agent consensus" in result["reason"]
