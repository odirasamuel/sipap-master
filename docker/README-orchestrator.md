# Valo Orchestrator Docker Build Guide

This directory contains Docker build infrastructure for the Valo AI Orchestrator, following Sentinel's proven multi-stage build patterns.

## Overview

The Valo Orchestrator is an AI-powered sports intelligence platform that coordinates multiple MCP (Model Context Protocol) servers to generate probability assessments and identify positive expected value (+EV) betting opportunities.

**Architecture:**
- **FastAPI HTTP API** - Prediction endpoints
- **MCP Client Layer** - Communicates with Lambda MCP servers via Function URLs
- **Strands Agents** - AI orchestration with Claude models
- **Multi-Agent System** - Specialized agents for data aggregation, analysis, and prediction

## Prerequisites

### Required
- **Docker Desktop** - Installed and running
- **AWS CLI** - Configured with credentials (`aws configure`)
- **Python 3.12+** - For build script execution
- **AWS Account Access** - ECR repository permissions

### AWS Permissions Required
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:sipap-build-config-*"
    }
  ]
}
```

## Quick Start

### Automated Build via GitHub Actions (Recommended)

The orchestrator is automatically built and pushed to ECR when code changes are pushed to the `main` branch.

**Trigger Automatic Build:**
```bash
# Push code changes to main branch
git add .
git commit -m "Update orchestrator code"
git push origin main

# GitHub Actions workflow will:
# 1. Build Docker image
# 2. Push to ECR (sipap-dev-orchestrator)
# 3. Report image digest and size
```

**Manual Trigger:**
```bash
# Via GitHub Actions UI:
# 1. Go to Actions tab in GitHub
# 2. Select "Build and Push Valo Orchestrator to ECR"
# 3. Click "Run workflow"
# 4. Optional: specify custom tag (default: latest)
```

**Check Build Status:**
```bash
# View in GitHub Actions UI or check via API:
gh run list --workflow=build-push-orchestrator.yml --limit 5
```

### Manual Build (Local Development Only)

For local testing and development:

#### 1. Verify ECR Repository Exists

```bash
aws ecr describe-repositories --repository-names sipap-dev-orchestrator --profile odiraaws --region us-east-1
```

If not exists (auto-created by workflow):
```bash
aws ecr create-repository --repository-name sipap-dev-orchestrator --profile odiraaws --region us-east-1
```

#### 2. Build Docker Image Locally

```bash
cd /Users/charlesotuya/AI-Odi/sentinel/sipap/repos/sipap-master
python docker/build-orchestrator.py build
```

**Expected Output:**
```
2026-07-19 12:00:00 - INFO - Loading config from file: docker/config.json
2026-07-19 12:00:00 - INFO - ✅ Config loaded from file
2026-07-19 12:00:00 - INFO - Building Docker image: 810278669998.dkr.ecr.us-east-1.amazonaws.com/sipap-dev-orchestrator:latest
2026-07-19 12:00:00 - INFO - Dockerfile generated successfully
...
2026-07-19 12:05:00 - INFO - ✅ Image built successfully
```

#### 3. Push to ECR (Optional - CI/CD Handles This)

```bash
python docker/build-orchestrator.py push
```

**Note**: Manual push requires AWS credentials. Prefer using GitHub Actions for production builds.

#### 4. Verify Image in ECR

```bash
aws ecr describe-images --repository-name sipap-dev-orchestrator --profile odiraaws --region us-east-1
```

## Build Script Usage

### Basic Commands

```bash
# Build only
python docker/build-orchestrator.py build

# Build and push
python docker/build-orchestrator.py build push

# Pull from ECR
python docker/build-orchestrator.py pull

# Cleanup local artifacts
python docker/build-orchestrator.py cleanup
```

### Advanced Options

```bash
# Build with custom tag
python docker/build-orchestrator.py --tag v1.0.0 build push

# Override ECR registry
python docker/build-orchestrator.py --ecr-registry 123456789012.dkr.ecr.us-east-1.amazonaws.com build push

# Use config from AWS Secrets Manager
python docker/build-orchestrator.py --config-secret-arn arn:aws:secretsmanager:us-east-1:810278669998:secret:sipap-build-config-AbCdEf build push

# Use custom config file
python docker/build-orchestrator.py --config-file /path/to/custom-config.json build push
```

## Configuration

### Local Configuration (config.json)

```json
{
  "ecr_registry": "810278669998.dkr.ecr.us-east-1.amazonaws.com",
  "ecr_repository": "sipap-orchestrator",
  "aws_region": "us-east-1",
  "aws_profile": "odiraaws",
  "build_platform": "linux/amd64",
  "python_version": "3.12",
  "description": "Valo AI Orchestrator"
}
```

### Secrets Manager Configuration

For production deployments, store build configuration in AWS Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name sipap-build-config \
  --secret-string file://docker/config.json \
  --profile odiraaws \
  --region us-east-1
```

Then use with build script:
```bash
python docker/build-orchestrator.py \
  --config-secret-arn arn:aws:secretsmanager:us-east-1:810278669998:secret:sipap-build-config-AbCdEf \
  build push
```

## Dockerfile Architecture

### Multi-Stage Build

**Stage 1: Builder**
- Base image: `python:3.12-slim`
- Installs system dependencies (build-essential, curl)
- Installs Python dependencies from `requirements.txt`
- Creates wheels for faster production deployment

**Stage 2: Runtime**
- Base image: `python:3.12-slim`
- Copies only installed packages (no build tools)
- Copies application code (sipap/, config/, examples/)
- Creates non-root user for security
- Exposes port 8080
- Configures health check endpoint

### Security Features

1. **Non-Root User**: Container runs as `app` user (not root)
2. **Minimal Base Image**: `python:3.12-slim` (not full Python image)
3. **Multi-Stage Build**: Build dependencies not in final image
4. **No Secrets in Image**: API keys via environment variables at runtime

### Image Size Optimization

- Multi-stage build eliminates build tools (~200 MB savings)
- Slim base image instead of full Python (~400 MB savings)
- No cache directories (`PIP_NO_CACHE_DIR=1`)
- Clean up apt lists after installation

**Expected Image Size:** ~350-400 MB (vs ~1 GB without optimization)

## Running the Container Locally

### With Docker CLI

```bash
docker run -p 8080:8080 \
  -e MODEL_API_KEY=sk-ant-api03-your-key-here \
  -e MCP_DATA_URL=https://mcn4s4lbwvoybp3xjvi27u2vuy0ghmuj.lambda-url.us-east-1.on.aws/ \
  -e MCP_INTELLIGENCE_URL=https://tbnkkzw6cgqgmw2ewnuufboud40mlibo.lambda-url.us-east-1.on.aws/ \
  810278669998.dkr.ecr.us-east-1.amazonaws.com/sipap-orchestrator:latest
```

### With Environment File

Create `.env`:
```bash
MODEL_API_KEY=sk-ant-api03-your-key-here
MODEL_ID=claude-sonnet-4-5-20250929
MCP_DATA_URL=https://mcn4s4lbwvoybp3xjvi27u2vuy0ghmuj.lambda-url.us-east-1.on.aws/
MCP_INTELLIGENCE_URL=https://tbnkkzw6cgqgmw2ewnuufboud40mlibo.lambda-url.us-east-1.on.aws/
LOG_LEVEL=INFO
```

Run with env file:
```bash
docker run -p 8080:8080 --env-file .env \
  810278669998.dkr.ecr.us-east-1.amazonaws.com/sipap-orchestrator:latest
```

### Test Health Endpoint

```bash
curl http://localhost:8080/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "timestamp": "2026-07-19T12:00:00Z"
}
```

### Test Prediction Endpoint

```bash
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": "test-123",
    "sport": "soccer",
    "home_team": "Manchester United",
    "away_team": "Liverpool",
    "date": "2026-07-20T15:00:00Z"
  }'
```

## ECS Deployment

Once the image is pushed to ECR, deploy to AWS ECS Fargate:

1. **Create ECS Task Definition** (references ECR image)
2. **Configure Environment Variables** (Model API key, MCP URLs)
3. **Deploy ECS Service** (Fargate, 1-3 tasks, auto-scaling)
4. **Configure Load Balancer** (ALB for HTTPS)

See `../terraform/core_deploy/` for infrastructure as code.

## Troubleshooting

### Build Fails with "Permission Denied"

Make entrypoint executable:
```bash
chmod +x docker/entrypoint-orchestrator.sh
```

### ECR Authentication Fails

Check AWS credentials:
```bash
aws sts get-caller-identity --profile odiraaws
```

Verify ECR permissions:
```bash
aws ecr get-authorization-token --profile odiraaws --region us-east-1
```

### Container Exits Immediately

Check logs:
```bash
docker logs <container_id>
```

Common issues:
- Missing `MODEL_API_KEY` environment variable
- Invalid API key format (must start with `sk-ant-api`)
- Missing MCP endpoint URLs

### Health Check Fails

Verify API server is running:
```bash
docker exec <container_id> curl http://localhost:8080/health
```

Check container logs for startup errors:
```bash
docker logs -f <container_id>
```

### Image Too Large

Check image size:
```bash
docker images | grep sipap-orchestrator
```

If > 500 MB, verify:
- Multi-stage build is working
- No large files in context (`.dockerignore` configured)
- Build cache is clean (`docker image prune`)

## Files in This Directory

- **build-orchestrator.py** (450+ lines) - Docker build script with ECR integration
- **entrypoint-orchestrator.sh** (80 lines) - Container entrypoint with validation
- **config.json** (10 lines) - Build configuration (ECR registry, region, etc.)
- **README-orchestrator.md** (this file) - Comprehensive documentation

## References

- **Sentinel Docker Patterns**: `/Users/charlesotuya/AI-Odi/sentinel/repos/sentinel-master/docker/`
- **Valo Architecture**: `/Users/charlesotuya/AI-Odi/sentinel/sipap/technical-architecture-v2.md`
- **AWS ECR Documentation**: https://docs.aws.amazon.com/ecr/
- **Docker Multi-Stage Builds**: https://docs.docker.com/build/building/multi-stage/

## Next Steps

After building and pushing the orchestrator image:

1. ✅ Build Docker image locally
2. ✅ Push to ECR
3. ⏳ Create ECS Task Definition
4. ⏳ Deploy ECS Service on Fargate
5. ⏳ Configure Application Load Balancer
6. ⏳ Test end-to-end prediction flow
7. ⏳ Integrate WhatsApp interface

**Current Status**: Docker build infrastructure complete, ready for ECS deployment.
