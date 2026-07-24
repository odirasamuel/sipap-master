#!/bin/bash
# SIPAP Orchestrator Health Check
# Ultra-simple: Check if heartbeat file was modified in last 90 seconds

HEARTBEAT_FILE="/tmp/sipap-heartbeat"

# Check 1: Heartbeat file (daemon mode)
if [ -f "$HEARTBEAT_FILE" ]; then
    # Get file modification time in seconds since epoch
    file_mtime=$(stat -c %Y "$HEARTBEAT_FILE" 2>/dev/null || stat -f %m "$HEARTBEAT_FILE" 2>/dev/null || echo "0")
    current_time=$(date +%s)
    age=$((current_time - file_mtime))

    # If file was modified in last 90 seconds, consider healthy
    if [ "$age" -lt 90 ]; then
        exit 0
    fi
fi

# Check 2: HTTP endpoint (API mode fallback)
curl -f http://localhost:8080/health >/dev/null 2>&1 && exit 0

# Both checks failed
exit 1
