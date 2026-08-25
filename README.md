# sipap-master

**Valo Main Orchestrator** - AI-powered sports prediction with multi-agent coordination

**Company**: Ridha Tech
**Product**: Valo (Sports Intelligence Platform and Outcome Probability Assessment Platform)
**Phase**: 6A - WhatsApp Integration (In Progress)
**Version**: 0.1.0
**Status**: Production-ready MVP

---

## About Ridha Tech

Ridha Tech is an AI solutions company specializing in intelligent automation and conversational AI platforms. Valo is our flagship product, delivering AI-powered sports intelligence through WhatsApp.

---

## Overview

sipap-master is the core orchestration layer for Valo (Sports Intelligence Platform and Outcome Probability Assessment Platform). It coordinates multiple AI agents and MCP servers to generate ensemble predictions for sports betting markets with expected value (+EV) analysis.

This repository contains the main orchestrator, AI agents, daemon mode (SQS polling), and WhatsApp integration via Twilio.

### Phase 4 Highlights (NEW)

- ✅ **MainOrchestrator** - Sport-agnostic routing to specialized orchestrators
- ✅ **FastAPI Endpoints** - Production HTTP API with Swagger documentation
- ✅ **MCP Integration** - Async client with retry logic and circuit breakers
- ✅ **Complete Pipeline** - 9-step prediction flow from request to recommendation
- ✅ **Quality Gates** - Zero errors (pytest: 72/72, mypy: 0, ruff: 0)
- ✅ **Working Examples** - 6 comprehensive examples (Phase 3 + Phase 4)

### Architecture

```
sipap-master
├── Agent YAML Configurations (5 agents)
│   ├── statistical.yml  - Poisson, xG, Elo predictions
│   ├── ml.yml          - XGBoost model predictions
│   ├── form.yml        - Recent form analysis
│   ├── market.yml      - Market sentiment analysis
│   └── news.yml        - News sentiment analysis
│
├── Python @tool Functions
│   ├── statistical.py  - Statistical calculation functions
│   ├── ml.py          - ML model wrapper functions
│   ├── form.py        - Form analysis functions
│   └── market.py      - Market analysis functions
│
├── AgentToolFactory
│   └── Creates Strands Agent instances from YAML configs
│
└── SoccerOrchestrator
    └── Coordinates all agents for ensemble predictions
```

### Key Components

**Agents (YAML + Strands Library)**
- Agents are NOT separate MCP servers
- Agent behavior defined in YAML configuration files
- Executed by Strands Agents library
- Agents CALL MCP servers and Python functions

**MCP Servers (Called by Agents)**
- sipap-data-mcp: Match schedules, team stats, H2H history
- sipap-intelligence-mcp: Weather intelligence, news sentiment, injury impact

**Python @tool Functions**
- Statistical models (Poisson, xG, Elo, form scoring)
- ML models (XGBoost wrapper)
- Form analysis algorithms
- Market sentiment analysis

## Installation

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e '.[dev]'
```

## Usage

### Option 1: MainOrchestrator (Phase 4 - Recommended)

```python
from sipap.core.orchestrator import MainOrchestrator

# Initialize main orchestrator (handles all sports)
orchestrator = MainOrchestrator()

# Generate prediction with full pipeline
prediction = await orchestrator.predict(
    sport="soccer",
    match_id="Man_United_vs_Liverpool",
    market="1X2"  # Home Win, Draw, Away Win
)

# Result structure (Phase 4 - Complete)
{
    "outcome": "Home Win",
    "probability": 0.65,
    "confidence": 78.0,
    "quality_gate": "PASSED",
    "recommendation": "Prediction ready for user",
    "expected_value": {
        "expected_value": 0.25,
        "edge": 0.15,
        "is_positive_ev": True,
        "our_probability": 0.65,
        "implied_probability": 0.50,
        "recommendation": "PLACE BET - Positive expected value"
    },
    "reasoning": "statistical: Poisson model favors home team | ml: XGBoost...",
    "evidence": ["Home team in better form", "H2H favors home"]
}
```

### Option 2: FastAPI Server (Phase 4)

```bash
# Start API server
python examples/02_api_server.py

# Server runs at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

```bash
# Make prediction request
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "soccer",
    "match_id": "Man_United_vs_Liverpool",
    "market": "1X2"
  }'
```

### Option 3: Direct Orchestrator (Phase 3 - Legacy)

```python
from sipap.sports.soccer.orchestrator import SoccerOrchestrator

# Initialize sport-specific orchestrator
orchestrator = SoccerOrchestrator()

# Generate prediction (simplified)
ensemble = orchestrator._calculate_ensemble(agent_predictions, "1X2")
```

## Development

### Test-Driven Development (TDD)

This project follows strict TDD methodology:

1. **RED**: Write failing test first
2. **GREEN**: Implement minimal code to pass
3. **REFACTOR**: Improve implementation

### Quality Gates

```bash
# Run tests with coverage
pytest --cov=sipap --cov-report=term-missing

# Type checking (strict mode)
mypy sipap --strict

# Linting
ruff check sipap tests
```

**Targets:**
- ✅ Tests: 80%+ coverage, all passing
- ✅ Type checking: 0 errors (mypy --strict)
- ✅ Linting: 0 errors (ruff)

## Project Structure

```
sipap-master/
├── sipap/
│   ├── core/                   # Core orchestration (Phase 4)
│   │   ├── orchestrator.py     # MainOrchestrator (sport routing) ⭐ NEW
│   │   └── mcp_client.py       # MCP HTTP client (retry + circuit breaker) ⭐ NEW
│   ├── sports/
│   │   └── soccer/
│   │       ├── orchestrator.py # SoccerOrchestrator (updated Phase 4) ⭐
│   │       │   # - aggregate_context() - MCP data aggregation ⭐ NEW
│   │       │   # - validate_context_quality() - Quality checks ⭐ NEW
│   │       │   # - calculate_expected_value() - +EV analysis ⭐ NEW
│   │       │   # - save_prediction() - Aurora persistence ⭐ NEW
│   │       └── agents/         # Agent YAML configs (Phase 3)
│   ├── api/                    # FastAPI endpoints (Phase 4) ⭐ NEW
│   │   └── handlers.py         # HTTP request handlers
│   ├── factory/
│   │   ├── agent.py            # AgentToolFactory (Phase 3)
│   │   └── mcp.py              # MCPFactory (YAML → clients) ⭐ NEW
│   ├── tools/
│   │   └── function/           # Python @tool functions (Phase 3)
│   │       ├── statistical.py  # Poisson, xG, Elo, form
│   │       └── ml.py           # ML prediction wrapper
│   └── utils/
│       └── monitoring.py       # Performance tracking ⭐ NEW
├── tests/
│   ├── unit/                   # 72 tests passing ✅
│   └── integration/            # End-to-end tests ⭐ NEW
├── examples/                   # 6 working examples
│   ├── 01_basic_prediction.py       # Phase 4 pipeline ⭐ NEW
│   ├── 02_api_server.py             # FastAPI server ⭐ NEW
│   ├── 03_mcp_integration.py        # MCP usage ⭐ NEW
│   ├── example_statistical_functions.py # Phase 3
│   ├── example_ml_prediction.py         # Phase 3
│   └── example_ensemble_prediction.py   # Phase 3
├── config/
│   └── mcp_servers.yml         # MCP server registry ⭐ NEW
└── pyproject.toml              # Updated with fastapi, uvicorn
```

⭐ = New in Phase 4

## License

MIT

## Contributing

This is part of the Valo project. See main repository for contribution guidelines.
