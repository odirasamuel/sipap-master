"""SIPAP Orchestrator - Main Entry Point.

Supports dual execution modes:
- daemon: Continuous SQS polling (production)
- api: FastAPI server (development/testing)

Mode is selected via ORCHESTRATOR_MODE environment variable.

Usage:
    # Daemon mode (production)
    export ORCHESTRATOR_MODE=daemon
    python -m sipap

    # API mode (development)
    export ORCHESTRATOR_MODE=api
    python -m sipap
"""

import logging
import os
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def main_daemon_mode() -> None:
    """Start daemon mode with SQS polling.

    Requires environment variables:
    - SQS_QUEUE_URL: Full SQS queue URL
    - AWS_REGION: AWS region (default: us-east-1)
    """
    from sipap.core.daemon import start_daemon

    queue_url = os.getenv("SQS_QUEUE_URL")
    if not queue_url:
        logger.error("SQS_QUEUE_URL environment variable not set")
        logger.error("Required for daemon mode")
        sys.exit(1)

    region = os.getenv("AWS_REGION", "us-east-1")
    heartbeat_path = os.getenv("HEARTBEAT_PATH", "/tmp/sipap-heartbeat")

    logger.info("Starting SIPAP orchestrator in daemon mode")

    start_daemon(
        queue_url=queue_url,
        region=region,
        heartbeat_path=heartbeat_path,
    )


def main_api_mode() -> None:
    """Start FastAPI server mode.

    Useful for:
    - Development and testing
    - Direct API access (if ALB configured)
    - Health check endpoints
    """
    import uvicorn

    from sipap.api.handlers import app

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8080"))
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    logger.info("Starting SIPAP orchestrator in API mode")
    logger.info(f"Server will run on {host}:{port}")
    logger.info(f"API documentation available at http://{host}:{port}/docs")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
    )


def main() -> None:
    """Main entry point with mode selection.

    Mode is determined by ORCHESTRATOR_MODE environment variable:
    - daemon: SQS polling mode (production)
    - api: FastAPI server mode (development)

    Default: daemon (production-ready)
    """
    mode = os.getenv("ORCHESTRATOR_MODE", "daemon").lower()

    logger.info("=" * 70)
    logger.info("SIPAP Orchestrator - Sports Intelligence Platform")
    logger.info("=" * 70)
    logger.info(f"Execution Mode: {mode.upper()}")
    logger.info("=" * 70)

    if mode == "daemon":
        main_daemon_mode()
    elif mode == "api":
        main_api_mode()
    else:
        logger.error(f"Invalid ORCHESTRATOR_MODE: {mode}")
        logger.error("Valid modes: daemon, api")
        sys.exit(1)


if __name__ == "__main__":
    main()
