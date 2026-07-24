#!/bin/bash

# SIPAP AI Orchestrator Entrypoint Script
# Processes sports intelligence predictions through AI-powered MCP orchestration

set -e

# Default values
LOG_LEVEL=${LOG_LEVEL:-INFO}
BEDROCK_MODEL_ID=${BEDROCK_MODEL_ID:-}
PORT=${PORT:-8080}
ORCHESTRATOR_MODE=${ORCHESTRATOR_MODE:-daemon}  # daemon or api

# Function to show help
show_help() {
    echo "SIPAP AI Orchestrator - AI-Powered Sports Intelligence Platform"
    echo ""
    echo "Execution Modes (set via ORCHESTRATOR_MODE):"
    echo "  daemon - Continuous SQS polling (production) [DEFAULT]"
    echo "  api    - FastAPI server (development/testing)"
    echo ""
    echo "Environment Variables:"
    echo "  ORCHESTRATOR_MODE       - Execution mode: daemon or api (default: daemon)"
    echo "  BEDROCK_MODEL_ID        - Bedrock model ID or inference profile ARN (optional)"
    echo "  BEDROCK_PROFILE_ARN     - Bedrock inference profile ARN (optional, fallback for MODEL_ID)"
    echo "  LOG_LEVEL               - Logging level (default: INFO)"
    echo ""
    echo "  DATA_MCP_URL            - Data MCP Lambda Function URL (required)"
    echo "  INTELLIGENCE_MCP_URL    - Intelligence MCP Lambda Function URL (required)"
    echo ""
    echo "  SQS_QUEUE_URL           - SQS queue URL (required for daemon mode)"
    echo "  AWS_REGION              - AWS region (default: us-east-1)"
    echo ""
    echo "  REDIS_ENDPOINT          - Redis endpoint for caching (optional)"
    echo "  POSTGRES_HOST           - PostgreSQL host for persistence (optional)"
    echo "  PORT                    - API server port (default: 8080, api mode only)"
    echo ""
    echo "Authentication:"
    echo "  Uses AWS IAM credentials from ECS task role (no API key needed)"
    echo ""
    echo "Usage:"
    echo "  # Daemon mode (production) - polls SQS continuously"
    echo "  docker run -e ORCHESTRATOR_MODE=daemon -e SQS_QUEUE_URL=https://... sipap-orchestrator"
    echo ""
    echo "  # API mode (development) - runs FastAPI server"
    echo "  docker run -e ORCHESTRATOR_MODE=api -p 8080:8080 sipap-orchestrator"
    echo ""
    echo "  # With explicit model ID"
    echo "  docker run -e BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5-20250929-v1 sipap-orchestrator"
}

# Check if help is requested
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    show_help
    exit 0
fi

# Set MODEL_ID from BEDROCK_PROFILE_ARN if BEDROCK_MODEL_ID not set
# This allows the agent YAML configs to use ${ MODEL_ID } for Jinja2 substitution
if [ -z "$BEDROCK_MODEL_ID" ] && [ -n "$BEDROCK_PROFILE_ARN" ]; then
    # Use inference profile ARN as MODEL_ID
    export MODEL_ID="$BEDROCK_PROFILE_ARN"
    echo "Using Bedrock inference profile: $MODEL_ID"
elif [ -n "$BEDROCK_MODEL_ID" ]; then
    export MODEL_ID="$BEDROCK_MODEL_ID"
    echo "Using Bedrock model: $MODEL_ID"
else
    echo "Warning: Neither BEDROCK_MODEL_ID nor BEDROCK_PROFILE_ARN set"
    echo "Agent configurations may fail if they reference \${ MODEL_ID }"
fi

# Validate MCP endpoints
if [ -z "$DATA_MCP_URL" ]; then
    echo "Warning: DATA_MCP_URL not set - data queries will fail"
fi

if [ -z "$INTELLIGENCE_MCP_URL" ]; then
    echo "Warning: INTELLIGENCE_MCP_URL not set - intelligence queries will fail"
fi

# Set log level
export LOG_LEVEL="$LOG_LEVEL"

# Create necessary directories
mkdir -p logs sessions

# If no command provided, run orchestrator in configured mode
if [ $# -eq 0 ]; then
    echo "Starting SIPAP Orchestrator in ${ORCHESTRATOR_MODE} mode..."

    if [ "$ORCHESTRATOR_MODE" = "daemon" ]; then
        echo "Daemon mode: Continuous SQS polling"
        echo "Queue URL: ${SQS_QUEUE_URL:-Not configured}"

        # Validate required environment variables for daemon mode
        if [ -z "$SQS_QUEUE_URL" ]; then
            echo "ERROR: SQS_QUEUE_URL not set (required for daemon mode)"
            exit 1
        fi

        # Run orchestrator in daemon mode
        exec python -m sipap

    elif [ "$ORCHESTRATOR_MODE" = "api" ]; then
        echo "API mode: FastAPI server on port ${PORT}"

        # Run orchestrator in API mode
        exec python -m sipap

    else
        echo "ERROR: Invalid ORCHESTRATOR_MODE: ${ORCHESTRATOR_MODE}"
        echo "Valid modes: daemon, api"
        exit 1
    fi
else
    # Execute provided command
    exec "$@"
fi
