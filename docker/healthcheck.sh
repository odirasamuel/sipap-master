#!/bin/bash
# SIPAP Orchestrator Health Check
# Works for both daemon mode (heartbeat file) and API mode (HTTP endpoint)

# Check 1: Heartbeat file (daemon mode)
if [ -f "/tmp/sipap-heartbeat" ]; then
    # Read timestamp and compare with current time
    heartbeat_age=$(python3 -c "
import json
import time
try:
    with open('/tmp/sipap-heartbeat') as f:
        data = json.load(f)
        age = time.time() - data['timestamp']
        print(int(age))
except:
    print(999)
" 2>/dev/null)

    # If heartbeat is fresh (<90s), consider healthy
    if [ "$heartbeat_age" -lt 90 ] 2>/dev/null; then
        exit 0
    fi
fi

# Check 2: HTTP endpoint (API mode fallback)
curl -f http://localhost:8080/health >/dev/null 2>&1 && exit 0

# Both checks failed
exit 1
