#!/usr/bin/env python3
"""
SIPAP Orchestrator Docker Build and Push Tool

Builds and pushes the SIPAP AI Orchestrator to AWS ECR.
The orchestrator is an AI-powered sports intelligence platform that coordinates
multiple MCP servers (Data MCP, Intelligence MCP) to generate probability assessments
and identify positive expected value (+EV) betting opportunities.

Prerequisites:
    - AWS CLI configured with valid credentials
    - Docker installed and running
    - AWS Secrets Manager secret containing build configuration (optional)

Usage:
    python build-orchestrator.py [options] {build|push|pull|cleanup}

Examples:
    # Build with local config.json
    python build-orchestrator.py build

    # Build and push to ECR
    python build-orchestrator.py build push

    # Build with custom tag
    python build-orchestrator.py --tag v1.0.0 build push

    # Build with config from Secrets Manager
    python build-orchestrator.py --config-secret-arn arn:aws:secretsmanager:us-east-1:123456789012:secret:sipap-build-config-AbCdEf build push
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SIPAPOrchestratorDockerBuilder:
    """SIPAP AI Orchestrator Docker Builder"""

    def __init__(self, config: Dict):
        self.config = config
        self.project_root = Path(__file__).parent.parent
        self.docker_dir = self.project_root / "docker"

        # Validate orchestrator structure exists
        if not (self.project_root / "sipap").exists():
            raise ValueError(f"SIPAP package not found at {self.project_root}/sipap")

        if not (self.project_root / "config").exists():
            raise ValueError(f"Config directory not found at {self.project_root}/config")

    def generate_dockerfile(self) -> str:
        """Generate Dockerfile for SIPAP Orchestrator"""

        dockerfile_content = """# SIPAP AI Orchestrator Dockerfile
# Multi-stage build for optimal image size
# Build context: parent directory containing sipap-master and sipap-common

# Use Python 3.12 slim image
FROM python:3.12-slim AS builder

# Set environment variables
ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PIP_NO_CACHE_DIR=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set working directory
WORKDIR /app

# Install system dependencies for ML libraries
RUN apt-get update && apt-get install -y \\
    build-essential \\
    curl \\
    git \\
    && rm -rf /var/lib/apt/lists/*

# Copy sipap-common package source and install it first
# This is a private package not on PyPI
COPY sipap-common/src /tmp/sipap-common/src
COPY sipap-common/pyproject.toml /tmp/sipap-common/
RUN pip install --no-cache-dir /tmp/sipap-common && \\
    rm -rf /tmp/sipap-common

# Copy requirements and install remaining dependencies
COPY sipap-master/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy installed packages and binaries from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy the SIPAP orchestrator code
COPY sipap-master/sipap/ /app/sipap/
COPY sipap-master/config/ /app/config/
COPY sipap-master/examples/ /app/examples/
COPY sipap-master/docker/entrypoint-orchestrator.sh /app/docker/entrypoint-orchestrator.sh

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app && \\
    mkdir -p logs sessions && \\
    chown -R app:app /app && \\
    chmod +x /app/docker/entrypoint-orchestrator.sh

USER app

# Expose API port (for API mode)
EXPOSE 8080

# Health check - Heartbeat file based (works for daemon and API mode)
# Checks if /tmp/sipap-heartbeat exists and timestamp is fresh (<90s old)
# Falls back to HTTP check for API mode
# This matches the Sentinel pattern for daemon health monitoring
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \\
    CMD python -c "import json,time,os; \\
path='/tmp/sipap-heartbeat'; \\
exit(0 if os.path.exists(path) and (time.time()-json.load(open(path))['timestamp']<90) else 1)" 2>/dev/null \\
    || curl -f http://localhost:8080/health 2>/dev/null \\
    || exit 1

# Set the entrypoint
ENTRYPOINT ["/app/docker/entrypoint-orchestrator.sh"]

# No default command - entrypoint handles mode selection via ORCHESTRATOR_MODE
# For custom commands (debugging, etc.), override at runtime:
#   docker run <image> <custom-command>
CMD []
"""
        return dockerfile_content

    def build_image(self, tag: str = "latest") -> None:
        """Build Docker image using BuildKit"""
        ecr_registry = self.config.get('ecr_registry', 'localhost')
        ecr_repository = self.config.get('ecr_repository', 'sipap-orchestrator')
        image_name = f"{ecr_registry}/{ecr_repository}:{tag}"

        logger.info(f"Building Docker image: {image_name}")

        # Generate Dockerfile
        dockerfile_content = self.generate_dockerfile()
        dockerfile_path = self.project_root / "Dockerfile"

        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)

        logger.info("Dockerfile generated successfully")

        # Determine build context
        # If sipap-common exists as sibling directory, use parent as context
        sipap_common_path = self.project_root.parent / "sipap-common"
        if sipap_common_path.exists():
            build_context = self.project_root.parent
            dockerfile_relative = "sipap-master/Dockerfile"
            logger.info(f"Using parent directory as build context (sipap-common detected)")
        else:
            build_context = self.project_root
            dockerfile_relative = "Dockerfile"
            logger.info(f"Using project root as build context (sipap-common not found)")

        # Build image with BuildKit
        build_cmd = [
            "docker", "build",
            "--platform", "linux/amd64",
            "--build-arg", "BUILDKIT_INLINE_CACHE=1",
            "-t", image_name,
            "-f", dockerfile_relative,
            "."
        ]

        logger.info(f"Running: {' '.join(build_cmd)}")
        logger.info(f"Build context: {build_context}")

        try:
            subprocess.run(build_cmd, check=True, cwd=build_context)
            logger.info(f"✅ Image built successfully: {image_name}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Build failed: {e}")
            raise

    def authenticate_ecr(self) -> None:
        """Authenticate Docker with Amazon ECR"""
        ecr_registry = self.config.get('ecr_registry')
        if not ecr_registry:
            raise ValueError("ECR registry not configured")

        # Extract region and account ID from registry URL
        # Format: <account_id>.dkr.ecr.<region>.amazonaws.com
        parts = ecr_registry.split('.')
        if len(parts) < 4:
            raise ValueError(f"Invalid ECR registry format: {ecr_registry}")

        region = parts[3]

        logger.info(f"Authenticating with ECR in region {region}")

        # Get ECR login password
        get_login_cmd = [
            "aws", "ecr", "get-login-password",
            "--region", region
        ]

        try:
            login_password = subprocess.run(
                get_login_cmd,
                check=True,
                capture_output=True,
                text=True
            ).stdout.strip()

            # Docker login
            docker_login_cmd = [
                "docker", "login",
                "--username", "AWS",
                "--password-stdin",
                ecr_registry
            ]

            subprocess.run(
                docker_login_cmd,
                input=login_password,
                check=True,
                text=True
            )

            logger.info("✅ ECR authentication successful")

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ ECR authentication failed: {e}")
            raise

    def push_image(self, tag: str = "latest") -> None:
        """Push Docker image to ECR"""
        ecr_registry = self.config.get('ecr_registry')
        ecr_repository = self.config.get('ecr_repository', 'sipap-orchestrator')
        image_name = f"{ecr_registry}/{ecr_repository}:{tag}"

        logger.info(f"Pushing image to ECR: {image_name}")

        # Authenticate with ECR
        self.authenticate_ecr()

        # Push image
        push_cmd = ["docker", "push", image_name]

        try:
            subprocess.run(push_cmd, check=True)
            logger.info(f"✅ Image pushed successfully: {image_name}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Push failed: {e}")
            raise

    def pull_image(self, tag: str = "latest") -> None:
        """Pull Docker image from ECR"""
        ecr_registry = self.config.get('ecr_registry')
        ecr_repository = self.config.get('ecr_repository', 'sipap-orchestrator')
        image_name = f"{ecr_registry}/{ecr_repository}:{tag}"

        logger.info(f"Pulling image from ECR: {image_name}")

        # Authenticate with ECR
        self.authenticate_ecr()

        # Pull image
        pull_cmd = ["docker", "pull", image_name]

        try:
            subprocess.run(pull_cmd, check=True)
            logger.info(f"✅ Image pulled successfully: {image_name}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Pull failed: {e}")
            raise

    def cleanup(self) -> None:
        """Clean up generated files and Docker artifacts"""
        logger.info("Cleaning up Docker artifacts")

        # Remove Dockerfile
        dockerfile_path = self.project_root / "Dockerfile"
        if dockerfile_path.exists():
            dockerfile_path.unlink()
            logger.info("Removed Dockerfile")

        # Prune dangling images
        try:
            subprocess.run(
                ["docker", "image", "prune", "-f"],
                check=True,
                capture_output=True
            )
            logger.info("✅ Cleanup complete")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Docker prune failed: {e}")


def load_config(config_path: Optional[Path] = None, secret_arn: Optional[str] = None) -> Dict:
    """Load build configuration from file or Secrets Manager"""

    if secret_arn:
        # Load from AWS Secrets Manager
        logger.info(f"Loading config from Secrets Manager: {secret_arn}")
        try:
            import boto3
            sm_client = boto3.client('secretsmanager')
            response = sm_client.get_secret_value(SecretId=secret_arn)
            config = json.loads(response['SecretString'])
            logger.info("✅ Config loaded from Secrets Manager")
            return config
        except Exception as e:
            logger.error(f"❌ Failed to load config from Secrets Manager: {e}")
            raise

    # Load from local file
    if config_path is None:
        config_path = Path(__file__).parent / "config.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.info(f"Loading config from file: {config_path}")
    with open(config_path, 'r') as f:
        config = json.load(f)

    logger.info("✅ Config loaded from file")
    return config


def main():
    parser = argparse.ArgumentParser(
        description="Build and push SIPAP Orchestrator Docker image to ECR",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--config-secret-arn',
        type=str,
        help='AWS Secrets Manager ARN containing build configuration'
    )

    parser.add_argument(
        '--config-file',
        type=Path,
        help='Path to local config.json file (default: docker/config.json)'
    )

    parser.add_argument(
        '--tag',
        type=str,
        default='latest',
        help='Docker image tag (default: latest)'
    )

    parser.add_argument(
        '--ecr-registry',
        type=str,
        help='Override ECR registry from config'
    )

    parser.add_argument(
        'commands',
        nargs='+',
        choices=['build', 'push', 'pull', 'cleanup'],
        help='Commands to execute (in order)'
    )

    args = parser.parse_args()

    try:
        # Load configuration
        config = load_config(args.config_file, args.config_secret_arn)

        # Override ECR registry if provided
        if args.ecr_registry:
            config['ecr_registry'] = args.ecr_registry
            logger.info(f"Overriding ECR registry: {args.ecr_registry}")

        # Create builder
        builder = SIPAPOrchestratorDockerBuilder(config)

        # Execute commands in order
        for command in args.commands:
            if command == 'build':
                builder.build_image(args.tag)
            elif command == 'push':
                builder.push_image(args.tag)
            elif command == 'pull':
                builder.pull_image(args.tag)
            elif command == 'cleanup':
                builder.cleanup()

        logger.info("✅ All commands completed successfully")

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
