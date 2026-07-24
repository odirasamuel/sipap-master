#!/bin/bash

# SIPAP AI Orchestrator Entrypoint Script
# Processes sports intelligence predictions through AI-powered MCP orchestration

set -e

# Default values
LOG_LEVEL=${LOG_LEVEL:-INFO}
BEDROCK_MODEL_ID=${BEDROCK_MODEL_ID:-}
PORT=${PORT:-8080}

# Function to show help
show_help() {
    echo "SIPAP AI Orchestrator - AI-Powered Sports Intelligence Platform"
    echo ""
    echo "Environment Variables:"
    echo "  BEDROCK_MODEL_ID        - Bedrock model ID or inference profile ARN (optional)"
    echo "  BEDROCK_PROFILE_ARN     - Bedrock inference profile ARN (optional, fallback for MODEL_ID)"
    echo "  LOG_LEVEL               - Logging level (default: INFO)"
    echo "  PORT                    - API server port (default: 8080)"
    echo ""
    echo "  DATA_MCP_URL            - Data MCP Lambda Function URL (required)"
    echo "  INTELLIGENCE_MCP_URL    - Intelligence MCP Lambda Function URL (required)"
    echo ""
    echo "  REDIS_ENDPOINT          - Redis endpoint for caching (optional)"
    echo "  POSTGRES_HOST           - PostgreSQL host for persistence (optional)"
    echo ""
    echo "Authentication:"
    echo "  Uses AWS IAM credentials from ECS task role (no API key needed)"
    echo ""
    echo "Usage:"
    echo "  # Run API server with Bedrock (uses BEDROCK_PROFILE_ARN from env)"
    echo "  docker run -e DATA_MCP_URL=https://... -e INTELLIGENCE_MCP_URL=https://... -p 8080:8080 sipap-orchestrator"
    echo ""
    echo "  # With explicit model ID"
    echo "  docker run -e BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5-20250929-v1 -p 8080:8080 sipap-orchestrator"
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

# If no command provided, run API server
if [ $# -eq 0 ]; then
    echo "Starting SIPAP Orchestrator API server on port ${PORT}..."
    exec uvicorn sipap.api.handlers:app --host 0.0.0.0 --port "${PORT}" --log-level "${LOG_LEVEL,,}"
else
    # Execute provided command
    exec "$@"
fi
