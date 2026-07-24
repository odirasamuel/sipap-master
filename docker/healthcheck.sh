#!/bin/bash
# SIPAP Orchestrator Health Check
# Works for both daemon mode (heartbeat file) and API mode (HTTP endpoint)

set -e

# Check 1: Heartbeat file (daemon mode)
if [ -f "/tmp/sipap-heartbeat" ]; then
    # Read timestamp from heartbeat file
    timestamp=$(python3 -c "import json; print(json.load(open('/tmp/sipap-heartbeat'))['timestamp'])" 2>/dev/null || echo "0")
    current_time=$(python3 -c "import time; print(time.time())" 2>/dev/null || echo "0")
    age=$(python3 -c "print($current_time - $timestamp)" 2>/dev/null || echo "999")

    # If heartbeat is fresh (<90s), consider healthy
    if (( $(echo "$age < 90" | bc -l) )); then
        exit 0
    fi
fi

# Check 2: HTTP endpoint (API mode fallback)
if curl -f http://localhost:8080/health 2>/dev/null; then
    exit 0
fi

# Both checks failed
exit 1
