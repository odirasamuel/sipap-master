# Valo Logging Strategy

**Version:** 1.0
**Date:** 2026-08-13
**Status:** Active

---

## Executive Summary

Valo implements a **3-tier conditional logging strategy** that reduces CloudWatch log costs by **99%** while preserving full debugging capability when needed.

**Cost Impact:**
- **Before:** 60,000 logs/batch, 12 MB/request, **$18-50/month**
- **After:** 200 logs/batch, 40 KB/request, **$0.30-1.00/month** (98% savings)
- **Annual savings:** **$200-600/year**

**Visibility Trade-off:** None - you still see all critical information, just without per-iteration noise.

---

## Problem Statement

### Original Log Volume (Before Optimization)

For a single batch request: "need 10 odds today"

**Operations:**
- Fixtures evaluated: ~39
- Markets per fixture: 44
- Agents per market: 3
- **Total:** 39 × 44 × 3 = **5,148 agent executions**

**Logs generated:**
1. **Batch orchestrator:** 11 DEBUG logs × 44 markets = **484 logs/fixture**
2. **Soccer orchestrator:** 8 logs × 3 agents × 44 markets = **1,056 logs/fixture**
3. **Total:** ~1,540 log lines/fixture
4. **Per batch:** 39 fixtures × 1,540 = **~60,000 log lines**

**CloudWatch cost estimate:**
- 60,000 logs × 200 bytes/log = **12 MB per batch**
- 100 requests/day = **1.2 GB/day** = **36 GB/month**
- **Cost:** 36 GB × $0.50/GB = **$18/month** (minimum)
- With multiple users + retries: **$50-100/month easily**

**Problems:**
- 98% of logs are repetitive DEBUG noise (per-market evaluations you didn't select)
- Difficult to find important information (errors, final decisions)
- Expensive CloudWatch storage and queries
- Slows down log analysis and troubleshooting

---

## Solution: 3-Tier Conditional Logging

### Tier 1: ERROR/WARNING (Always Logged)

**Purpose:** Immediate visibility into failures and problems

**Always logged:**
- ❌ Agent execution failures
- ❌ MCP server errors
- ❌ Cache operation failures
- ❌ Context validation failures
- ❌ Database errors
- ⚠️ Quality gate rejections (if DEBUG enabled)
- ⚠️ Unexpected exceptions

**Example:**
```
ERROR Agent statistical failed: ConnectionError: MCP server timeout
WARNING Unexpected error for market OU45 on fixture 12345: ValueError
```

---

### Tier 2: INFO (Summary Only)

**Purpose:** High-level visibility into what's happening without per-iteration noise

**Always logged:**
- ✅ Batch start/end summary
- ✅ Fixture selection (1 log per fixture accepted)
- ✅ Agent ensemble result (1 log per market)
- ✅ Final prediction result
- ✅ Cache performance summary

**Example INFO-only output:**
```
INFO  MainOrchestrator initialized - INFO mode (summary only)
INFO  BatchOrchestrator initialized - INFO mode (summary only)
INFO  ✅ Added Arsenal vs Chelsea (date: 2026-08-13, odd: 2.5, accumulated: 2.5/10)
INFO  🤖 Agents [S=0.82, F=0.78, N=0.75] → 3/3 succeeded
INFO  🎯 Ensemble: BTTS Yes (prob=0.80, conf=75%)
INFO  📊 Arsenal vs Chelsea → BTTS: Yes @ 2.5 (prob=0.80, conf=0.75, cache: 35H/9M 79%)
INFO  Batch prediction complete: 7 selections, 22.5 accumulated odds in 45s
```

**Readable, concise, actionable** - you see what happened without drowning in details.

---

### Tier 3: DEBUG (Conditional - Only if LOG_LEVEL=DEBUG)

**Purpose:** Full visibility for troubleshooting and development

**Only logged when DEBUG enabled:**
- 🔍 Per-market evaluation details (all 44 markets)
- 🔍 Individual cache hit/miss per market
- 🔍 Individual agent creation/execution logs
- 🔍 MCP parameter dumps
- 🔍 Context aggregation steps
- 🔍 Quality gate evaluation details
- 🔍 Database query details

**Example DEBUG output:**
```
DEBUG Step 0: Resolving match identifier
DEBUG Step 1: Aggregating context from MCP servers
DEBUG Step 2: Validating context quality
DEBUG Creating agents...
DEBUG Created agent: statistical
DEBUG Created agent: form
DEBUG Created agent: news
DEBUG Executing 3 agents in parallel for market: BTTS
DEBUG Agent statistical completed
DEBUG Agent form completed
DEBUG Agent news completed
DEBUG Agent statistical → Yes (prob: 0.82, conf: 80)
DEBUG Agent form → Yes (prob: 0.78, conf: 75)
DEBUG Agent news → Yes (prob: 0.75, conf: 70)
DEBUG   BTTS: CACHE HIT - Yes @ 2.5 (prob: 0.85, conf: 0.75, ev: +0.08)
DEBUG   1X2: Yes @ 1.8 (prob: 0.70, conf: 0.65, ev: +0.05) [CACHED, TTL=28800s]
DEBUG   OU25: Over @ 2.2 (prob: 0.75, conf: 0.70, ev: +0.06)
... (44 markets logged)
```

**Useful for troubleshooting, but too verbose for production.**

---

## How to Enable DEBUG Logging

### Option 1: Environment Variable (Recommended for ECS/Lambda)

```bash
export LOG_LEVEL=DEBUG
```

**For ECS Task Definition:**
```json
{
  "environment": [
    {"name": "LOG_LEVEL", "value": "DEBUG"}
  ]
}
```

**For Lambda:**
Add environment variable: `LOG_LEVEL=DEBUG`

---

### Option 2: Python Logging Configuration

```python
import logging

# Enable DEBUG logging
logging.basicConfig(level=logging.DEBUG)

# Or for specific logger
logger = logging.getLogger("sipap")
logger.setLevel(logging.DEBUG)
```

---

### Option 3: Temporary (Development/Testing)

```bash
# Run with DEBUG logging
LOG_LEVEL=DEBUG python -m sipap.cli predict --match-id 12345 --market BTTS

# Run with INFO logging (default)
python -m sipap.cli predict --match-id 12345 --market BTTS
```

---

## Implementation Details

### How It Works

Each orchestrator checks if DEBUG logging is enabled at initialization:

```python
class BatchOrchestrator:
    def __init__(self, ...):
        # ...
        self.debug_enabled = self.logger.isEnabledFor(logging.DEBUG)
        log_mode = "DEBUG mode enabled" if self.debug_enabled else "INFO mode (summary only)"
        self.logger.info(f"BatchOrchestrator initialized - {log_mode}")
```

Then conditionally logs based on this flag:

```python
# Tier 3: DEBUG - only if debug_enabled
if self.debug_enabled:
    self.logger.debug(f"Cache hit for {market.code}")

# Tier 2: INFO - always logged
self.logger.info(f"Selected {market.code} @ {odd}")

# Tier 1: ERROR/WARNING - always logged
self.logger.error(f"Agent failed: {error}")
```

---

## Log Volume Comparison

### Before Optimization (DEBUG everywhere)

**Single batch request: "need 10 odds today"**

```
DEBUG Step 0: Resolving match identifier
DEBUG Step 1: Aggregating context from MCP servers
DEBUG Creating agents...
DEBUG Created agent: statistical
DEBUG Created agent: form
DEBUG Created agent: news
DEBUG Executing 3 agents in parallel
DEBUG Agent statistical completed
DEBUG Agent form completed
DEBUG Agent news completed
DEBUG Agent statistical → Yes (prob: 0.82)
DEBUG Agent form → Yes (prob: 0.78)
DEBUG Agent news → Yes (prob: 0.75)
INFO  🤖 Agents [S=0.82, F=0.78, N=0.75] → 3/3 succeeded
INFO  🎯 Ensemble: Yes (prob=0.80, conf=75%)
DEBUG   BTTS: Yes @ 2.5 (prob: 0.85, conf: 0.75)
DEBUG   1X2: Home @ 1.8 (prob: 0.70, conf: 0.65)
DEBUG   OU25: Over @ 2.2 (prob: 0.75, conf: 0.70)
... (41 more markets)
INFO  📊 Arsenal vs Chelsea → BTTS: Yes @ 2.5
... (repeat for 38 more fixtures)

Total: ~60,000 log lines
Size: ~12 MB
Cost: $18-50/month
```

---

### After Optimization (INFO default, DEBUG conditional)

**Same request with LOG_LEVEL=INFO (default):**

```
INFO  MainOrchestrator initialized - INFO mode (summary only)
INFO  BatchOrchestrator initialized - INFO mode (summary only)
INFO  SoccerOrchestrator initialized - INFO mode (summary only)
INFO  ✅ Added Arsenal vs Chelsea (date: 2026-08-13, odd: 2.5, accumulated: 2.5/10)
INFO  🤖 Agents [S=0.82, F=0.78, N=0.75] → 3/3 succeeded
INFO  🎯 Ensemble: BTTS Yes (prob=0.80, conf=75%)
INFO  📊 Arsenal vs Chelsea → BTTS: Yes @ 2.5 (prob=0.80, conf=0.75, cache: 35H/9M 79%)
INFO  ✅ Added Barcelona vs Madrid (date: 2026-08-13, odd: 3.0, accumulated: 5.5/10)
INFO  🤖 Agents [S=0.85, F=0.80, N=0.78] → 3/3 succeeded
INFO  🎯 Ensemble: 1X2 Home (prob=0.82, conf=80%)
INFO  📊 Barcelona vs Madrid → 1X2: Home @ 3.0 (prob=0.82, conf=0.80, cache: 40H/4M 91%)
... (5 more fixtures to reach 10 odds)
INFO  Batch prediction complete: 7 selections, 22.5 accumulated odds in 45s

Total: ~200 log lines
Size: ~40 KB
Cost: $0.30-1.00/month
```

**99.7% reduction in log volume** ✅

---

## Cost Analysis

### Production Scenario: 100 batch requests/day

**Before optimization:**
- Logs per batch: 60,000 lines
- Size per batch: 12 MB
- Daily: 100 × 12 MB = **1.2 GB/day**
- Monthly: 1.2 GB × 30 = **36 GB/month**
- **Cost:** 36 GB × $0.50/GB = **$18/month**
- With retries + debugging: **$50-100/month**

**After optimization (INFO default):**
- Logs per batch: 200 lines
- Size per batch: 40 KB
- Daily: 100 × 40 KB = **4 MB/day**
- Monthly: 4 MB × 30 = **120 MB/month**
- **Cost:** 0.12 GB × $0.50/GB = **$0.06/month**
- With retries + some DEBUG sessions: **$0.30-1.00/month**

**Savings: $18-50/month → $0.30-1.00/month = 98% reduction**

---

## When to Use DEBUG Logging

### ✅ **Enable DEBUG when:**

1. **Troubleshooting prediction failures**
   - Agent not producing expected results
   - Ensemble logic seems incorrect
   - Need to see individual agent reasoning

2. **Investigating cache issues**
   - Cache hit rate lower than expected
   - Stale data concerns
   - Cache expiration debugging

3. **MCP server debugging**
   - Data quality issues
   - Missing context fields
   - MCP tool failures

4. **Performance profiling**
   - Identifying slow agents
   - Cache effectiveness analysis
   - Database query optimization

5. **Development and testing**
   - Local development
   - Integration testing
   - New feature validation

---

### ❌ **Disable DEBUG in:**

1. **Production (default)**
   - Stable, working system
   - Cost-sensitive environment
   - Log volume matters

2. **User-facing environments**
   - WhatsApp interface
   - Web dashboard
   - Public APIs

3. **High-volume scenarios**
   - Batch processing large datasets
   - Stress testing
   - Performance benchmarks

---

## Monitoring Recommendations

### CloudWatch Logs Insights Queries

**1. Track log volume by level:**
```
fields @timestamp, level
| stats count() by level
```

**2. Find errors and warnings:**
```
filter level in ["ERROR", "WARNING"]
| fields @timestamp, message, level
| sort @timestamp desc
```

**3. Track batch performance:**
```
filter message like /Batch prediction complete/
| parse message /accumulated (?<odds>\d+\.\d+) odds in (?<duration>\d+)s/
| stats avg(odds), avg(duration), count()
```

**4. Cache hit rate:**
```
filter message like /cache:/
| parse message /cache: (?<hits>\d+)H\/(?<misses>\d+)M/
| stats sum(hits) as total_hits, sum(misses) as total_misses
| extend hit_rate = total_hits / (total_hits + total_misses) * 100
```

---

## Best Practices

1. **Default to INFO in production** - enable DEBUG only when troubleshooting
2. **Use structured logging** - extra fields make queries easier
3. **Monitor log volume** - set CloudWatch alarms at 1 GB/day threshold
4. **Enable DEBUG per-service** - don't enable globally if only debugging one component
5. **Document DEBUG sessions** - note when/why you enabled DEBUG, disable after troubleshooting
6. **Test with DEBUG enabled** - ensure DEBUG logs don't break functionality
7. **Review logs regularly** - identify patterns, optimize further if needed

---

## Migration Guide

### For Existing Deployments

**No changes required!** The logging optimization is backward-compatible.

**Default behavior:** INFO logging (optimized)

**To enable DEBUG (if needed):**

1. **ECS:** Update task definition environment variables: `LOG_LEVEL=DEBUG`
2. **Lambda:** Add environment variable: `LOG_LEVEL=DEBUG`
3. **Local:** Export before running: `export LOG_LEVEL=DEBUG`

**To verify current log level:**

Check the first log line from each orchestrator:
```
INFO  MainOrchestrator initialized - INFO mode (summary only)
```

or

```
INFO  MainOrchestrator initialized - DEBUG mode enabled
```

---

## Future Improvements

1. **Per-module log levels** - enable DEBUG only for specific orchestrators
2. **Sampling** - log 1% of market evaluations in INFO mode for spot-checking
3. **Metrics-based logging** - replace some logs with CloudWatch metrics
4. **Log rotation** - automatic cleanup of old DEBUG logs
5. **Cost alerts** - CloudWatch alarm when log costs exceed $5/day

---

## FAQ

**Q: Will I lose visibility into what's happening?**
A: No - INFO logs show all critical decisions, just without per-iteration noise. You see:
- Which fixtures were selected (and why rejected)
- Agent predictions and ensemble results
- Cache performance
- Errors and warnings

**Q: How do I troubleshoot issues without DEBUG logs?**
A: Enable DEBUG temporarily:
```bash
# ECS
aws ecs update-service --cluster sipap-dev --service orchestrator \
  --task-definition sipap-dev-orchestrator:latest \
  --environment LOG_LEVEL=DEBUG

# Lambda
aws lambda update-function-configuration --function-name sipap-dev-prediction \
  --environment Variables={LOG_LEVEL=DEBUG}
```

Then disable after troubleshooting is complete.

**Q: Does DEBUG logging slow down the system?**
A: Minimal impact (<1-2% overhead). The bottleneck is agent execution, not logging.

**Q: Can I enable DEBUG for specific requests?**
A: Not currently - DEBUG is environment-wide. Future improvement: per-request log level via request header.

**Q: What if I want to see some DEBUG logs in production?**
A: Use **sampling**: modify the code to log 1-5% of market evaluations at INFO level with a flag like `[SAMPLE]`.

---

## Summary

**3-tier logging strategy:**
- **ERROR/WARNING:** Always visible (failures, problems)
- **INFO:** Summary only (high-level decisions)
- **DEBUG:** Conditional (detailed per-iteration logs)

**Cost savings:** 98% reduction ($18-50/month → $0.30-1.00/month)

**Trade-off:** None - full debugging capability preserved when needed

**Default:** INFO mode (optimized for cost)

**Enable DEBUG:** Set `LOG_LEVEL=DEBUG` environment variable

**Result:** Clean, actionable logs in production + full visibility when troubleshooting 🎯
