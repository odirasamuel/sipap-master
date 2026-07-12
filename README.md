# sipap-master

**SIPAP Main Orchestrator** - AI-powered sports prediction with multi-agent coordination

## Overview

sipap-master is the core orchestration layer for SIPAP (Sports Intelligence Platform and Outcome Probability Assessment Platform). It coordinates multiple AI agents to generate ensemble predictions for sports betting markets.

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

```python
from sipap.sports.soccer.orchestrator import SoccerOrchestrator

# Initialize orchestrator
orchestrator = SoccerOrchestrator(sport="soccer")

# Generate prediction
prediction = await orchestrator.predict(
    match_id="match-123",
    market="1X2"  # Home Win, Draw, Away Win
)

# Result structure
{
    "ensemble": {
        "market": "1X2",
        "outcome": "home_win",
        "probability": 0.62,
        "confidence": 75
    },
    "agent_predictions": [
        {"agent": "statistical", "probability": 0.58, ...},
        {"agent": "ml", "probability": 0.65, ...},
        {"agent": "form", "probability": 0.60, ...},
        {"agent": "market", "probability": 0.63, ...},
        {"agent": "news", "probability": 0.64, ...}
    ],
    "reasoning": "Ensemble analysis indicates...",
    "evidence": [...]
}
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
│   ├── core/                   # Core orchestration
│   │   ├── orchestrator.py     # Base orchestrator
│   │   ├── mcp_client.py       # MCP server client
│   │   └── session.py          # Session management
│   ├── sports/
│   │   └── soccer/
│   │       ├── orchestrator.py # Soccer orchestrator
│   │       ├── agents/         # Agent YAML configs
│   │       └── config/         # Sport config
│   ├── tools/
│   │   └── function/           # Python @tool functions
│   │       ├── statistical.py
│   │       ├── ml.py
│   │       ├── form.py
│   │       └── market.py
│   ├── factory/
│   │   └── agent.py            # AgentToolFactory
│   └── utils/
│       ├── ensemble.py         # Ensemble calculation
│       └── quality_gates.py    # Quality validation
├── tests/
├── examples/
└── config/
```

## License

MIT

## Contributing

This is part of the SIPAP project. See main repository for contribution guidelines.
