"""AWS Lambda Function URL signing middleware for SIPAP.

Adapted from Sentinel's proven AWS signing pattern.
Provides automatic SigV4 request signing for Lambda Function URLs using
boto3 credentials and botocore's SigV4Auth.
"""

import logging
import re
import time

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


class AWSLambdaURLSigner:
    """
    AWS SigV4 request signer for Lambda Function URLs.

    Automatically signs requests to Lambda Function URLs using boto3 credentials
    and botocore's SigV4Auth. Supports credential caching for performance.

    Features:
    - Automatic Lambda URL detection via pattern matching
    - Boto3 default credential chain (IAM role → env vars → credentials file)
    - 5-minute credential caching
    - <2ms signing overhead
    - Zero-impact for non-Lambda URLs

    Example:
        >>> signer = AWSLambdaURLSigner()
        >>> client = httpx.AsyncClient(event_hooks={"request": [signer.sign_request]})
    """

    # Lambda Function URL pattern: https://{id}.lambda-url.{region}.on.aws
    LAMBDA_URL_PATTERN = r'\.lambda-url\.([a-z0-9-]+)\.on\.aws'

    def __init__(
        self,
        session: boto3.Session | None = None,
        cache_ttl: int = 300,
        logger: logging.Logger | None = None
    ):
        """
        Initialize AWS Lambda URL signer.

        Args:
            session: Optional boto3.Session (creates default session if None)
            cache_ttl: Credential cache TTL in seconds (default: 300 = 5 minutes)
            logger: Optional logger instance
        """
        self._session = session if session is not None else boto3.Session()
        self._cache_ttl = cache_ttl
        self._logger = logger if logger is not None else logging.getLogger(__name__)

        # Credential caching
        self._credentials_cache = None
        self._cache_timestamp = None

        # Compile regex once for performance
        self._lambda_url_regex = re.compile(self.LAMBDA_URL_PATTERN)

        self._logger.debug(
            "Initialized AWSLambdaURLSigner (cache_ttl=%ds)",
            self._cache_ttl
        )

    def should_sign(self, url: str) -> bool:
        """
        Check if URL is a Lambda Function URL.

        Args:
            url: The URL to check

        Returns:
            True if URL matches Lambda Function URL pattern
        """
        return bool(self._lambda_url_regex.search(url))

    def get_region_from_url(self, url: str) -> str:
        """
        Extract AWS region from Lambda Function URL.

        Args:
            url: Lambda Function URL

        Returns:
            AWS region (e.g., 'us-east-1')

        Raises:
            ValueError: If region cannot be extracted from URL
        """
        match = self._lambda_url_regex.search(url)
        if not match:
            raise ValueError(f"Cannot extract region from URL: {url}")

        region = match.group(1)
        self._logger.debug("Extracted region=%s from Lambda URL", region)
        return region

    def _get_credentials(self):
        """
        Get AWS credentials with caching.

        Uses boto3's default credential chain:
        1. IAM role (ECS task role, EC2 instance profile)
        2. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        3. Credentials file (~/.aws/credentials)

        Returns:
            botocore.credentials.Credentials object

        Raises:
            RuntimeError: If credentials cannot be retrieved
        """
        # Check cache validity
        now = time.time()
        if (self._credentials_cache is not None and
            self._cache_timestamp is not None and
            (now - self._cache_timestamp) < self._cache_ttl):
            return self._credentials_cache

        # Fetch new credentials
        self._logger.debug("Fetching AWS credentials via boto3 default chain")
        credentials = self._session.get_credentials()

        if credentials is None:
            raise RuntimeError(
                "AWS credentials not found. Configure credentials via IAM role, "
                "environment variables, or credentials file."
            )

        # Update cache
        self._credentials_cache = credentials
        self._cache_timestamp = now
        self._logger.debug("Cached fresh credentials (TTL=%ds)", self._cache_ttl)

        return credentials

    def _convert_to_aws_request(self, request: httpx.Request) -> AWSRequest:
        """
        Convert httpx.Request to botocore.awsrequest.AWSRequest.

        Only includes headers that should be signed. Excludes headers that
        httpx might modify after signing.

        Args:
            request: httpx request to convert

        Returns:
            AWSRequest suitable for SigV4Auth signing
        """
        # Extract request components
        method = request.method
        url = str(request.url)
        body = request.content if request.content else b''

        # Only include headers that should be signed
        # Exclude headers that httpx might modify
        headers_to_exclude = {
            'accept', 'accept-encoding', 'connection', 'user-agent',
            'Accept', 'Accept-Encoding', 'Connection', 'User-Agent'
        }

        filtered_headers = {
            k: v for k, v in request.headers.items()
            if k not in headers_to_exclude
        }

        # Create AWS request with filtered headers
        aws_request = AWSRequest(method=method, url=url, headers=filtered_headers, data=body)

        return aws_request

    async def sign_request(self, request: httpx.Request) -> None:
        """
        Sign httpx request with AWS SigV4 (event hook for httpx.AsyncClient).

        Adds the following headers:
        - Authorization: AWS4-HMAC-SHA256 Credential=..., SignedHeaders=..., Signature=...
        - X-Amz-Date: 20260803T123456Z
        - X-Amz-Security-Token: <session token> (if using temporary credentials)

        Args:
            request: httpx.Request to sign (modified in-place)

        Raises:
            RuntimeError: If credentials cannot be retrieved or signing fails
            ValueError: If region cannot be extracted from URL
        """
        url = str(request.url)

        # Skip non-Lambda URLs
        if not self.should_sign(url):
            return

        try:
            # Get credentials
            credentials = self._get_credentials()

            # Freeze credentials for SigV4 signing
            frozen_credentials = credentials.get_frozen_credentials()

            # Extract region from URL
            region = self.get_region_from_url(url)

            # Convert to AWS request
            aws_request = self._convert_to_aws_request(request)

            # Sign with SigV4Auth
            signer = SigV4Auth(frozen_credentials, 'lambda', region)
            signer.add_auth(aws_request)

            # Copy signed headers back to httpx request
            for header_name in ['Authorization', 'X-Amz-Date', 'X-Amz-Security-Token']:
                if header_name in aws_request.headers:
                    request.headers[header_name] = aws_request.headers[header_name]

            self._logger.debug(f"Signed Lambda Function URL request to {region}")

        except Exception as e:
            self._logger.error(f"Failed to sign Lambda Function URL request: {e}")
            raise
