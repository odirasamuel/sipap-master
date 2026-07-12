# SIPAP-Master Examples

Comprehensive working examples demonstrating the Phase 3 & 4 components: Intelligence Layer + Integration Layer.

## Overview

This directory contains 6 production-ready examples that demonstrate the full functionality of sipap-master:

### Phase 3 Examples (Intelligence Layer)
1. **Statistical Functions** - Core prediction algorithms (Poisson, xG, Elo, Form)
2. **ML Prediction** - Machine learning prediction pipeline
3. **Ensemble Prediction** - Full multi-agent orchestration with quality gates

### Phase 4 Examples (Integration Layer) **NEW**
4. **Basic Prediction** - End-to-end prediction pipeline with MCP integration
5. **API Server** - FastAPI server with HTTP endpoints
6. **MCP Integration** - MCP client usage and tool routing

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

## Phase 4 Examples (NEW)

### Example 4: Basic Prediction (`01_basic_prediction.py`)

**Purpose:** Demonstrates the complete end-to-end prediction pipeline with MCP integration.

**Run:**

```bash
python examples/01_basic_prediction.py
```

**What it demonstrates:**

- **MainOrchestrator:** Sport-agnostic routing to specialized orchestrators
- **Context Aggregation:** Fetching data from MCP servers in parallel
- **Quality Gates:** Validation and confidence thresholds
- **Expected Value:** +EV analysis for betting opportunities
- **Complete Pipeline:** All 9 steps from request to recommendation

**Output:** Detailed prediction report with quality gates, +EV analysis, and actionable recommendations.

**Key Learnings:**

- How MainOrchestrator coordinates predictions
- Understanding the 9-step prediction pipeline
- Quality gate enforcement in production
- Expected value calculation and interpretation

---

### Example 5: API Server (`02_api_server.py`)

**Purpose:** Demonstrates running the SIPAP prediction API with FastAPI.

**Run:**

```bash
python examples/02_api_server.py
```

**What it demonstrates:**

- **FastAPI Server:** Production-ready HTTP API
- **Swagger UI:** Interactive API documentation
- **Request/Response Models:** Pydantic validation
- **Error Handling:** Proper HTTP status codes and error messages
- **CORS:** Cross-origin resource sharing setup

**API Endpoints:**
- `GET /` - Root endpoint (API info)
- `GET /health` - Health check
- `GET /sports` - List supported sports
- `POST /predict` - Generate prediction

**Testing the API:**

```bash
# Health check
curl http://localhost:8000/health

# List sports
curl http://localhost:8000/sports

# Generate prediction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "soccer",
    "match_id": "Man_United_vs_Liverpool",
    "market": "1X2"
  }'
```

**Key Learnings:**

- How to run FastAPI applications
- Understanding HTTP API design
- Request/response validation with Pydantic
- Testing APIs with curl and Swagger UI

---

### Example 6: MCP Integration (`03_mcp_integration.py`)

**Purpose:** Demonstrates MCP client usage, tool routing, and error handling.

**Run:**

```bash
python examples/03_mcp_integration.py
```

**What it demonstrates:**

- **MCPFactory:** Creating and managing MCP clients
- **Tool Routing:** Mapping tools to MCP servers
- **Health Checks:** Verifying MCP server availability
- **Error Handling:** Circuit breaker and retry logic
- **Async Operations:** Parallel MCP calls with asyncio

**Output:** Step-by-step walkthrough of MCP integration patterns.

**Key Learnings:**

- How MCPFactory creates clients from YAML config
- Tool-to-server routing mechanism
- Circuit breaker pattern for fault tolerance
- Retry logic with exponential backoff
- Health check patterns

**Note:** This example works with or without running MCP servers. If servers are not available, it demonstrates graceful error handling.

---

## Phase 4 Architecture

### Prediction Pipeline (9 Steps)

1. **Request Routing** - MainOrchestrator routes to sport-specific orchestrator
2. **Context Aggregation** - Fetch data from MCP servers (parallel)
3. **Context Validation** - Check data quality (70%+ completeness)
4. **Agent Predictions** - 5 agents generate predictions
5. **Ensemble Calculation** - Weighted average with agent agreement
6. **Expected Value** - Calculate +EV from odds
7. **Quality Gates** - Enforce minimum standards
8. **Persistence** - Save to Aurora database
9. **Response** - Return prediction with recommendation

### MCP Integration

**Configuration:** `config/mcp_servers.yml`

```yaml
mcp_servers:
  data:
    name: "sipap-data-mcp"
    endpoints:
      local: "http://localhost:8001"
      dev: "http://sipap-data-mcp-dev.us-east-1.elb.amazonaws.com"
    timeout: 5.0
    tools:
      - get_match_schedule
      - get_team_stats
      # ... more tools

  intelligence:
    name: "sipap-intelligence-mcp"
    endpoints:
      local: "http://localhost:8002"
    timeout: 10.0
    tools:
      - get_match_weather
      - analyze_team_news
      # ... more tools
```

**Tool Routing:** Automatic mapping of tool names to MCP servers

```python
factory = MCPFactory()
data_mcp = factory.create("data")
result = await data_mcp.call_tool("get_match_schedule", {"date": "2024-01-15"})
```

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
