"""Example 2: FastAPI Server

Demonstrates running the SIPAP prediction API server.

This example shows how to:
1. Start the FastAPI server
2. Make prediction requests via HTTP
3. Check health and sports endpoints

Usage:
    # Start server
    python examples/02_api_server.py

    # In another terminal, test with curl:
    curl http://localhost:8000/health
    curl http://localhost:8000/sports
    curl -X POST http://localhost:8000/predict \
      -H "Content-Type: application/json" \
      -d '{"sport": "soccer", "match_id": "Man_United_vs_Liverpool", "market": "1X2"}'
"""

import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Add sipap to path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from sipap.api.handlers import app

if __name__ == "__main__":
    import uvicorn

    print("=" * 70)
    print("SIPAP Example 2: FastAPI Server")
    print("=" * 70)
    print()
    print("Starting SIPAP Prediction API server...")
    print("API Documentation available at: http://localhost:8000/docs")
    print()
    print("Endpoints:")
    print("  GET  /          - Root endpoint (API info)")
    print("  GET  /health    - Health check")
    print("  GET  /sports    - List supported sports")
    print("  POST /predict   - Generate prediction")
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 70)
    print()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
