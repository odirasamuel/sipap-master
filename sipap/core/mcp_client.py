"""MCP Client - HTTP client for calling MCP servers via JSON-RPC 2.0.

This client communicates with MCP servers deployed on Lambda/Fargate using
the MCP protocol (JSON-RPC 2.0 over HTTP).

Pattern adapted from Sentinel's MCP client implementation.

Features:
- Automatic retry with exponential backoff
- Circuit breaker pattern for fault tolerance
- Comprehensive error handling
"""

import asyncio
import logging
import time
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel

from sipap.aws.signing import AWSLambdaURLSigner


class MCPRequest(BaseModel):
    """JSON-RPC 2.0 request structure."""

    jsonrpc: str = "2.0"
    id: str
    method: str
    params: dict[str, Any] | None = None


class MCPResponse(BaseModel):
    """JSON-RPC 2.0 response structure."""

    jsonrpc: str
    id: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class MCPClient:
    """
    HTTP client for calling MCP servers.

    Communicates with MCP servers using JSON-RPC 2.0 protocol over HTTP.

    Example:
        >>> client = MCPClient(
        ...     name="sports-data-mcp",
        ...     base_url="http://sipap-data-mcp.us-east-1.elb.amazonaws.com"
        ... )
        >>> result = await client.call_tool("get_match_schedule", {"date": "2024-01-15"})
        >>> print(result["matches"])
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        logger: logging.Logger | None = None,
    ):
        """
        Initialize MCP client.

        Args:
            name: MCP server name (for logging)
            base_url: Base URL of MCP server
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts (default: 3)
            backoff_factor: Backoff multiplier for retries (default: 0.5)
            logger: Logger instance
        """
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.logger = logger or logging.getLogger(__name__)

        # Circuit breaker state
        self._failure_count = 0
        self._circuit_open = False
        self._circuit_open_until = 0.0
        self._failure_threshold = 5  # Open circuit after 5 consecutive failures
        self._recovery_timeout = 60.0  # Try to recover after 60 seconds

        # Initialize AWS Lambda URL signer for automatic request signing
        self._aws_signer = AWSLambdaURLSigner(logger=self.logger)

        # HTTP client (lazy-initialized on first use to ensure it binds to the correct event loop)
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """
        Get HTTP client, creating it lazily if needed.

        Lazy initialization ensures the client is created inside an async context
        with the event loop running, preventing "Event loop is closed" errors.

        Returns:
            httpx.AsyncClient instance
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=True,
                event_hooks={"request": [self._aws_signer.sign_request]},
            )
            self.logger.debug(f"Created httpx client for {self.name}")
        return self._client

    def _check_circuit_breaker(self) -> None:
        """
        Check if circuit breaker is open.

        Raises:
            RuntimeError: If circuit is open and not yet recovered
        """
        if self._circuit_open:
            # Check if recovery timeout has passed
            if time.time() < self._circuit_open_until:
                raise RuntimeError(
                    f"Circuit breaker open for {self.name} "
                    f"(recovery in {int(self._circuit_open_until - time.time())}s)"
                )
            else:
                # Attempt recovery (half-open state)
                self.logger.info(f"Circuit breaker entering half-open state: {self.name}")
                self._circuit_open = False

    def _record_success(self) -> None:
        """Record successful call and reset failure count."""
        if self._failure_count > 0:
            self.logger.info(
                f"MCP call succeeded, resetting failure count: {self.name}",
                extra={"previous_failures": self._failure_count},
            )
        self._failure_count = 0

    def _record_failure(self) -> None:
        """Record failed call and open circuit if threshold reached."""
        self._failure_count += 1

        if self._failure_count >= self._failure_threshold:
            self._circuit_open = True
            self._circuit_open_until = time.time() + self._recovery_timeout

            self.logger.error(
                f"Circuit breaker opened for {self.name}",
                extra={
                    "consecutive_failures": self._failure_count,
                    "recovery_timeout": self._recovery_timeout,
                },
            )

    async def _call_with_retry(
        self,
        request: MCPRequest,
        endpoint: str = "/mcp",
    ) -> MCPResponse:
        """
        Make HTTP request with retry logic and exponential backoff.

        Args:
            request: MCP request object
            endpoint: API endpoint (default: /mcp)

        Returns:
            MCP response object

        Raises:
            httpx.HTTPError: If all retries exhausted
            ValueError: If MCP server returns error
            RuntimeError: If circuit breaker is open
        """
        # Check circuit breaker
        self._check_circuit_breaker()

        last_exception: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                # Make HTTP POST request
                response = await self.client.post(
                    endpoint,
                    json=request.model_dump(exclude_none=True),
                )
                response.raise_for_status()

                # Parse JSON-RPC response
                mcp_response = MCPResponse(**response.json())

                # Record success
                self._record_success()

                return mcp_response

            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_exception = e

                # Check if we should retry
                if attempt < self.max_retries:
                    # Calculate backoff delay
                    backoff = self.backoff_factor * (2 ** (attempt - 1))

                    self.logger.warning(
                        f"MCP call failed (attempt {attempt}/{self.max_retries}), retrying in {backoff}s",
                        extra={
                            "server": self.name,
                            "error": str(e),
                            "backoff": backoff,
                        },
                    )

                    # Wait before retry
                    await asyncio.sleep(backoff)
                else:
                    # Final attempt failed
                    self.logger.error(
                        f"MCP call failed after {self.max_retries} attempts",
                        extra={
                            "server": self.name,
                            "error": str(e),
                        },
                        exc_info=True,
                    )

                    # Record failure for circuit breaker
                    self._record_failure()

        # All retries exhausted
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError("Unexpected retry logic state")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call an MCP tool.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result

        Raises:
            httpx.HTTPError: If HTTP request fails
            ValueError: If MCP server returns error response
        """
        # Create JSON-RPC 2.0 request
        request = MCPRequest(
            id=str(uuid4()),
            method="tools/call",
            params={
                "name": tool_name,
                "arguments": arguments,
            },
        )

        self.logger.debug(
            f"Calling MCP tool: {self.name}.{tool_name}",
            extra={"tool": tool_name, "arguments": arguments},
        )

        try:
            # Make HTTP request with retry logic
            mcp_response = await self._call_with_retry(request)

            # Check for error
            if mcp_response.error:
                error_message = mcp_response.error.get("message", "Unknown error")
                error_code = mcp_response.error.get("code", -1)
                self.logger.error(
                    f"MCP error: {self.name}.{tool_name} - {error_message}",
                    extra={"error_code": error_code, "error": mcp_response.error},
                )
                raise ValueError(f"MCP error ({error_code}): {error_message}")

            # Return result
            if mcp_response.result is None:
                raise ValueError("MCP response missing result field")

            # Unwrap MCP tool response from content array
            # MCP protocol returns: {"content": [{"type": "text", "text": "..."}]}
            # We need to extract and parse the JSON from content[0].text
            import json as json_lib
            result = mcp_response.result

            self.logger.debug(
                f"Raw MCP response result type: {type(result).__name__}",
                extra={"has_content": "content" in result if isinstance(result, dict) else False}
            )

            if isinstance(result, dict) and "content" in result:
                content_items = result.get("content", [])
                if content_items and len(content_items) > 0:
                    first_item = content_items[0]
                    if isinstance(first_item, dict) and first_item.get("type") == "text":
                        text_content = first_item.get("text", "")
                        if text_content:
                            # Parse JSON string to dict
                            try:
                                result = json_lib.loads(text_content)
                                self.logger.debug(
                                    f"Unwrapped MCP response: {len(text_content)} bytes → {type(result).__name__}"
                                )
                            except json_lib.JSONDecodeError as e:
                                self.logger.warning(
                                    f"Failed to parse MCP tool response as JSON: {text_content[:100]}...",
                                    extra={"error": str(e)}
                                )

            self.logger.debug(
                f"MCP tool call successful: {self.name}.{tool_name}",
                extra={"result_keys": list(result.keys()) if isinstance(result, dict) else []},
            )

            return result

        except httpx.HTTPError as e:
            self.logger.error(
                f"HTTP error calling MCP: {self.name}.{tool_name}",
                extra={"error": str(e), "url": self.base_url},
                exc_info=True,
            )
            raise

    async def list_tools(self) -> list[dict[str, Any]]:
        """
        List all available tools from MCP server.

        Returns:
            List of tool definitions with names, descriptions, and schemas
        """
        request = MCPRequest(
            id=str(uuid4()),
            method="tools/list",
        )

        self.logger.debug(f"Listing tools from MCP: {self.name}")

        try:
            # Make HTTP request with retry logic
            mcp_response = await self._call_with_retry(request)

            if mcp_response.error:
                raise ValueError(f"MCP error: {mcp_response.error.get('message')}")

            if mcp_response.result is None:
                raise ValueError("MCP response missing result field")

            tools_list: list[dict[str, Any]] = mcp_response.result.get("tools", [])
            self.logger.info(f"Found {len(tools_list)} tools from {self.name}")

            return tools_list

        except httpx.HTTPError as e:
            self.logger.error(
                f"HTTP error listing tools from MCP: {self.name}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise

    async def health_check(self) -> bool:
        """
        Check if MCP server is healthy.

        Returns:
            True if server is responding, False otherwise
        """
        try:
            # Try to list tools as health check
            await self.list_tools()
            return True
        except Exception as e:
            self.logger.warning(
                f"Health check failed for {self.name}: {e}",
                extra={"error": str(e)},
            )
            return False

    async def close(self) -> None:
        """Close HTTP client and cleanup resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self.logger.debug(f"Closed MCP client: {self.name}")

    async def __aenter__(self) -> "MCPClient":
        """Context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        """Context manager exit - cleanup resources."""
        # Suppress unused parameter warnings (required by context manager protocol)
        _ = exc_type, exc_val, exc_tb
        await self.close()
