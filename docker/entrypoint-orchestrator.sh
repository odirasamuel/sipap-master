#!/bin/bash

# SIPAP AI Orchestrator Entrypoint Script
# Processes sports intelligence predictions through AI-powered MCP orchestration

set -e

# Default values
LOG_LEVEL=${LOG_LEVEL:-INFO}
MODEL_API_KEY=${MODEL_API_KEY:-}
MODEL_ID=${MODEL_ID:-claude-sonnet-4-5-20250929}
PORT=${PORT:-8080}

# Function to show help
show_help() {
    echo "SIPAP AI Orchestrator - AI-Powered Sports Intelligence Platform"
    echo ""
    echo "Environment Variables:"
    echo "  MODEL_API_KEY           - Anthropic API key (required)"
    echo "  MODEL_ID                - Anthropic model ID (default: claude-sonnet-4-5-20250929)"
    echo "  LOG_LEVEL               - Logging level (default: INFO)"
    echo "  PORT                    - API server port (default: 8080)"
    echo ""
    echo "  MCP_DATA_URL            - Data MCP Lambda Function URL (required)"
    echo "  MCP_INTELLIGENCE_URL    - Intelligence MCP Lambda Function URL (required)"
    echo ""
    echo "  REDIS_ENDPOINT          - Redis endpoint for caching (optional)"
    echo "  POSTGRES_HOST           - PostgreSQL host for persistence (optional)"
    echo ""
    echo "Usage:"
    echo "  # Run API server"
    echo "  docker run -e MODEL_API_KEY=your-key -e MCP_DATA_URL=https://... -e MCP_INTELLIGENCE_URL=https://... -p 8080:8080 sipap-orchestrator"
    echo ""
    echo "  # With custom model and logging"
    echo "  docker run -e MODEL_API_KEY=your-key -e MODEL_ID=claude-sonnet-4-5-20250929 -e LOG_LEVEL=DEBUG -p 8080:8080 sipap-orchestrator"
}

# Check if help is requested
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    show_help
    exit 0
fi

# Validate required environment variables
if [ -z "$MODEL_API_KEY" ]; then
    echo "Error: MODEL_API_KEY environment variable is required"
    echo "Use --help for usage information"
    exit 1
fi

# Validate API key format
if [[ ! "$MODEL_API_KEY" =~ ^sk-ant-api ]]; then
    echo "Error: MODEL_API_KEY format is invalid - should start with 'sk-ant-api'"
    exit 1
fi

# Validate MCP endpoints
if [ -z "$MCP_DATA_URL" ]; then
    echo "Warning: MCP_DATA_URL not set - data queries will fail"
fi

if [ -z "$MCP_INTELLIGENCE_URL" ]; then
    echo "Warning: MCP_INTELLIGENCE_URL not set - intelligence queries will fail"
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
