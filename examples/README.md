# SIPAP-Master Examples

Comprehensive working examples demonstrating the Phase 3 Intelligence Layer components.

## Overview

This directory contains 3 production-ready examples that demonstrate the core functionality of sipap-master:

1. **Statistical Functions** - Core prediction algorithms (Poisson, xG, Elo, Form)
2. **ML Prediction** - Machine learning prediction pipeline
3. **Ensemble Prediction** - Full multi-agent orchestration with quality gates

All examples are **runnable** and **fully documented**.

---

## Prerequisites

### Python Environment

- Python 3.12+ required
- Virtual environment activated

```bash
# Ensure you're in the sipap-master directory
cd /path/to/sipap-master

# Activate virtual environment
source .venv/bin/activate
```

### Dependencies Installed

```bash
# Verify installation
python -c "from sipap.factory.agent import AgentToolFactory; print('✅ sipap-master installed')"
```

If not installed:

```bash
pip install -e .
```

---

## Running the Examples

### Example 1: Statistical Functions

**Purpose:** Demonstrates the core statistical prediction functions that power the Statistical Agent.

**Run:**

```bash
python examples/example_statistical_functions.py
```

**What it demonstrates:**

- **Poisson Model:** Calculate match outcome probabilities from goal-scoring rates
- **xG Calculator:** Evaluate shot quality and expected goals
- **Elo Rating:** Win probability from team strength ratings
- **Form Score:** Weighted analysis of recent performance

**Output:** Detailed breakdown of each function with real-world examples (Arsenal vs Chelsea, Liverpool analysis, etc.).

**Key Learnings:**

- How Poisson distribution models goal probabilities
- Shot location impact on expected goals
- Elo rating system for team strength
- Weighted form scoring with momentum detection

---

### Example 2: ML Prediction

**Purpose:** Demonstrates the machine learning prediction pipeline that powers the ML Agent.

**Run:**

```bash
python examples/example_ml_prediction.py
```

**What it demonstrates:**

- **Feature Engineering:** Extract 12 features from match context
- **ML Prediction:** Generate probability predictions (simplified for MVP)
- **Confidence Calculation:** Assess prediction certainty

**Output:** Step-by-step walkthrough of the ML pipeline with Liverpool vs Manchester United example.

**Key Learnings:**

- How match context is converted to model features
- Feature importance (Elo, form, attack stats, etc.)
- Confidence calculation from probability distributions
- Integration with ensemble system

---

### Example 3: Ensemble Prediction

**Purpose:** Demonstrates the complete orchestration system coordinating all 5 agents.

**Run:**

```bash
python examples/example_ensemble_prediction.py
```

**What it demonstrates:**

- **Multi-Agent Coordination:** 5 agents with different approaches
- **Weighted Ensemble:** Combine predictions with accuracy-based weights
- **Quality Gates:** Enforce minimum standards (confidence, probability, consensus)
- **Transparency:** Full reasoning and evidence trails

**Output:** Complete prediction workflow from agent predictions to final recommendation, including both passing and failing quality gate scenarios.

**Key Learnings:**

- How agents are weighted (ML 30%, Statistical 25%, Form 20%, Market 15%, News 10%)
- Confidence calculation from agent agreement
- Quality gate enforcement (55% confidence, 50% probability, 3/5 consensus)
- Why low-confidence predictions are blocked

---

## Example Output Samples

### Statistical Functions

```
1. POISSON MODEL - Arsenal vs Chelsea
----------------------------------------------------------------------
   Home Avg Goals: 2.1
   Away Avg Goals: 1.6
   League Average: 1.5

   PREDICTIONS:
   - Home Win: 59.23% (probability: 0.5923)
   - Draw:     22.45% (probability: 0.2245)
   - Away Win: 18.32% (probability: 0.1832)

   Expected Goals:
   - Arsenal (home): 2.73 xG
   - Chelsea (away): 1.6 xG
```

### ML Prediction

```
STEP 2: ML Model Prediction
======================================================================

Model Prediction:
  - Market: v2.1
  - Probability: 63.45%
  - Confidence: 67/100

Interpretation: STRONG home win prediction
```

### Ensemble Prediction

```
FINAL PREDICTION
======================================================================

Market: 1X2
Outcome: Home Win
Probability: 64.26%
Confidence: 84/100

Quality Gate: PASSED
Recommendation: Prediction ready for user
```

---

## Understanding the Output

### Probability vs Confidence

**Probability** (0-1 or 0%-100%):
- Likelihood of the predicted outcome
- Example: 0.65 = 65% chance of home win

**Confidence** (0-100):
- How certain we are about the probability
- High confidence: Agents strongly agree
- Low confidence: Agents disagree (prediction blocked)

### Quality Gates

Predictions must pass 3 gates to reach users:

1. **Minimum Confidence (55%):** Agents must show reasonable agreement
2. **Minimum Probability (50%):** Prediction must favor one outcome
3. **Minimum Consensus (3/5):** At least 3 agents must agree

**Why?** Prevents low-quality predictions from misleading users.

---

## Code Structure

### Statistical Functions (`sipap/tools/function/statistical.py`)

```python
from sipap.tools.function.statistical import (
    poisson_model,    # Poisson distribution for match outcomes
    xg_calculator,    # Expected goals from shots
    elo_rating,       # Win probability from Elo
    form_score        # Weighted form analysis
)
```

### ML Functions (`sipap/tools/function/ml.py`)

```python
from sipap.tools.function.ml import (
    ml_predict,           # Main prediction function
    engineer_features,    # Extract features from context
    calculate_confidence  # Confidence from probabilities
)
```

### Orchestrator (`sipap/sports/soccer/orchestrator.py`)

```python
from sipap.sports.soccer.orchestrator import SoccerOrchestrator

orchestrator = SoccerOrchestrator()
ensemble = orchestrator._calculate_ensemble(agent_predictions, "1X2")
final = orchestrator._apply_quality_gates(ensemble, agent_predictions)
```

---

## Customization

### Modify Agent Weights

Edit `sipap/sports/soccer/orchestrator.py`:

```python
weights = {
    "statistical": 0.25,  # Increase to trust statistical more
    "ml": 0.30,          # Decrease if ML less accurate
    "form": 0.20,
    "market": 0.15,
    "news": 0.10
}
```

### Adjust Quality Gates

Edit `sipap/sports/soccer/orchestrator.py`:

```python
# Stricter gates (fewer predictions pass)
if ensemble["confidence"] < 70:  # Was 55
    return "FAILED"

# Looser gates (more predictions pass)
if ensemble["confidence"] < 45:  # Was 55
    return "FAILED"
```

---

## Troubleshooting

### ImportError: No module named 'sipap'

**Solution:**

```bash
# Install package in editable mode
pip install -e .

# Verify installation
python -c "import sipap; print('✅ Installed')"
```

### ModuleNotFoundError: No module named 'scipy'

**Solution:**

```bash
# Install missing dependency
pip install scipy>=1.11.0
```

### Test Failures

**Solution:**

```bash
# Run tests to verify everything works
pytest tests/unit/ -v

# Should show: 72 passed
```

---

## Next Steps

### Integrate with MCP Servers (Phase 2)

Once Phase 2 MCP servers are available:

1. Replace mock agent predictions with real agent calls
2. Connect to `sipap-data-mcp` for match data
3. Connect to `sipap-odds-intelligence-mcp` for market data
4. Connect to `sipap-news-intelligence-mcp` for contextual data

### Train Real ML Models

Replace simplified ML prediction with XGBoost:

1. Train model on historical match data
2. Save model to S3
3. Update `ml_predict()` to load real model
4. Achieve 60%+ accuracy on test set

### Deploy to Production

1. Containerize sipap-master (Docker)
2. Deploy to AWS ECS Fargate
3. Connect to WhatsApp interface
4. Monitor predictions via telemetry

---

## Additional Resources

### Documentation

- **VERIFICATION-REPORT.md:** Quality metrics and test results
- **README.md:** Package overview and setup
- **CLAUDE.md (root):** Development standards and patterns

### Test Suite

```bash
# View all tests
pytest tests/unit/ --collect-only

# Run specific test suite
pytest tests/unit/test_statistical.py -v
pytest tests/unit/test_ml.py -v
pytest tests/unit/test_orchestrator.py -v
```

### Agent YAML Configurations

Located in `sipap/sports/soccer/agents/`:

- `statistical.yml` - Statistical Agent configuration
- `ml.yml` - ML Agent configuration
- `form.yml` - Form Agent configuration
- `market.yml` - Market Agent configuration
- `news.yml` - News Agent configuration

---

## Support

For issues or questions:

1. Check `VERIFICATION-REPORT.md` for known issues
2. Review `PROGRESS-TRACKER.md` for project status
3. Consult `CLAUDE.md` for development standards

---

**Version:** 0.1.0
**Phase:** Phase 3 - Intelligence Layer (MVP)
**Date:** 2026-07-12
**Status:** ✅ All examples verified and working
