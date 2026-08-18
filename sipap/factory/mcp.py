"""MCP Factory - Creates MCP client instances from YAML configuration.

Pattern adapted from Sentinel's factory pattern and sipap's AgentToolFactory.

This factory:
1. Loads MCP server configurations from YAML
2. Processes environment variables (${ENV})
3. Creates MCPClient instances
4. Handles connection pooling and lifecycle
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment

from sipap.core.mcp_client import MCPClient


class MCPFactory:
    """
    Creates MCP client instances from YAML configuration.

    This factory manages all MCP server connections for sipap-master.

    Example:
        >>> factory = MCPFactory()
        >>> data_mcp = factory.create("data")
        >>> tools = await data_mcp.list_tools()
        >>> result = await data_mcp.call_tool("get_match_schedule", {"date": "2024-01-15"})
    """

    def __init__(
        self,
        config_path: Path | str | None = None,
        environment: str | None = None,
        logger: logging.Logger | None = None,
    ):
        """
        Initialize MCP factory.

        Args:
            config_path: Path to mcp_servers.yml (default: config/mcp_servers.yml)
            environment: Environment name (dev, staging, prod). If None, uses ENV env var
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.environment = environment or os.getenv("ENV", "dev")

        # Set config path
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "mcp_servers.yml"
        self.config_path = Path(config_path)

        # Initialize Jinja environment before loading config
        # Note: Use default undefined behavior (returns empty string for missing vars)
        self._jinja_env = Environment()

        # Load configuration
        self.config = self._load_config()

        # MCP client instances (lazy loaded)
        self._clients: dict[str, MCPClient] = {}

        self.logger.info(
            f"MCPFactory initialized for environment: {self.environment}",
            extra={"config_path": str(self.config_path)},
        )

    def _load_config(self) -> dict[str, Any]:
        """
        Load MCP server configuration from YAML.

        Returns:
            Parsed configuration dict

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"MCP config not found: {self.config_path}")

        with open(self.config_path, "r") as f:
            config_str = f.read()

        # Process environment variables (${ENV})
        config_str = self._process_template(config_str)

        config_data = yaml.safe_load(config_str)

        # Ensure config is a dictionary
        if not isinstance(config_data, dict):
            raise ValueError(f"Invalid MCP config format: expected dict, got {type(config_data)}")

        config: dict[str, Any] = config_data

        self.logger.debug(
            f"Loaded MCP config: {len(config.get('mcp_servers', {}))} servers",
            extra={"servers": list(config.get("mcp_servers", {}).keys())},
        )

        return config

    def _process_template(self, template_str: str) -> str:
        """
        Process environment variable substitution.

        Replaces ${VAR} or ${VAR:-default} with environment variable values.

        Args:
            template_str: Template string with ${VAR} placeholders

        Returns:
            Rendered template with environment variables substituted
        """
        # Replace ${VAR:-default} with {{ VAR|default('default') }}
        template_str = re.sub(
            r"\$\{(\w+):-([^}]+)\}",
            r"{{ \1 if \1 else '\2' }}",
            template_str,
        )

        # Replace ${VAR} with {{ VAR }}
        template_str = re.sub(r"\$\{(\w+)\}", r"{{ \1 if \1 else '' }}", template_str)

        # Render template with environment variables
        template = self._jinja_env.from_string(template_str)
        return template.render(**os.environ)

    def create(self, server_name: str) -> MCPClient:
        """
        Create or retrieve MCP client instance.

        Args:
            server_name: MCP server name (e.g., "data", "intelligence")

        Returns:
            MCPClient instance

        Raises:
            ValueError: If server name not found in config
        """
        # Return cached client if exists
        if server_name in self._clients:
            self.logger.debug(f"Returning cached MCP client: {server_name}")
            return self._clients[server_name]

        # Get server config
        servers = self.config.get("mcp_servers", {})
        if server_name not in servers:
            available = list(servers.keys())
            raise ValueError(
                f"MCP server '{server_name}' not found in config. Available: {available}"
            )

        server_config = servers[server_name]

        # Get endpoint for current environment
        endpoints = server_config.get("endpoints", {})
        if self.environment not in endpoints:
            raise ValueError(
                f"No endpoint for environment '{self.environment}' in server '{server_name}'. "
                f"Available environments: {list(endpoints.keys())}"
            )

        base_url = endpoints[self.environment]
        timeout = server_config.get("timeout", 30.0)
        mcp_name = server_config.get("name", server_name)

        # Get retry configuration
        retry_config = server_config.get("retry", {})
        max_retries = retry_config.get("max_attempts", 3)
        backoff_factor = retry_config.get("backoff_factor", 0.5)

        # Create MCP client with retry configuration
        client = MCPClient(
            name=mcp_name,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            logger=self.logger,
        )

        # Cache client
        self._clients[server_name] = client

        self.logger.info(
            f"Created MCP client: {server_name}",
            extra={
                "mcp_name": mcp_name,
                "base_url": base_url,
                "environment": self.environment,
            },
        )

        return client

    def create_all(self) -> dict[str, MCPClient]:
        """
        Create all MCP clients defined in config.

        Returns:
            Dict mapping server names to MCPClient instances
        """
        servers = self.config.get("mcp_servers", {})
        clients = {}

        for server_name in servers.keys():
            try:
                clients[server_name] = self.create(server_name)
            except Exception as e:
                self.logger.error(
                    f"Failed to create MCP client: {server_name}",
                    extra={"error": str(e)},
                    exc_info=True,
                )

        self.logger.info(f"Created {len(clients)} MCP clients")
        return clients

    def get_tool_routing(self) -> dict[str, str]:
        """
        Get tool-to-MCP routing map.

        Returns:
            Dict mapping tool names to MCP server names
        """
        routing: dict[str, str] = self.config.get("tool_routing", {})
        return routing

    def get_server_for_tool(self, tool_name: str) -> str | None:
        """
        Get MCP server name for a given tool.

        Args:
            tool_name: Tool name

        Returns:
            MCP server name or None if not found
        """
        routing = self.get_tool_routing()
        return routing.get(tool_name)

    async def health_check_all(self) -> dict[str, bool]:
        """
        Health check all MCP servers.

        Returns:
            Dict mapping server names to health status (True/False)
        """
        servers = self.config.get("mcp_servers", {})
        health_status = {}

        for server_name in servers.keys():
            try:
                client = self.create(server_name)
                health_status[server_name] = await client.health_check()
            except Exception as e:
                self.logger.error(
                    f"Health check failed for {server_name}: {e}",
                    exc_info=True,
                )
                health_status[server_name] = False

        return health_status

    async def warmup(
        self,
        server_names: list[str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, bool]:
        """
        Warm up MCP servers by pinging them to trigger Lambda cold starts.

        This should be called BEFORE batch processing to ensure MCPs are ready.
        The warmup:
        1. Resets circuit breakers for all specified MCPs
        2. Concurrently pings each MCP with list_tools
        3. Waits for responses (with timeout)
        4. Returns success status for each MCP

        Args:
            server_names: List of MCP server names to warm up (default: all)
            timeout: Maximum time to wait for each MCP (default: 10s)

        Returns:
            Dict mapping server names to warmup success status (True/False)

        Example:
            >>> factory = MCPFactory()
            >>> status = await factory.warmup(["data", "intelligence"])
            >>> print(status)
            {"data": True, "intelligence": True}
        """
        if server_names is None:
            servers = self.config.get("mcp_servers", {})
            server_names = list(servers.keys())

        self.logger.info(
            f"🔥 Warming up {len(server_names)} MCP servers: {server_names}"
        )

        warmup_status: dict[str, bool] = {}

        async def warmup_single(server_name: str) -> tuple[str, bool]:
            """Warm up a single MCP server."""
            try:
                client = self.create(server_name)

                # Reset circuit breaker before warmup
                client.reset_circuit_breaker()

                # Ping with list_tools (lightweight operation)
                await asyncio.wait_for(
                    client.list_tools(),
                    timeout=timeout,
                )

                self.logger.info(f"✅ MCP warmed up: {server_name}")
                return (server_name, True)

            except asyncio.TimeoutError:
                self.logger.warning(
                    f"⚠️ MCP warmup timeout ({timeout}s): {server_name}"
                )
                return (server_name, False)

            except Exception as e:
                self.logger.warning(
                    f"⚠️ MCP warmup failed: {server_name} - {e}"
                )
                return (server_name, False)

        # Warm up all MCPs concurrently
        tasks = [warmup_single(name) for name in server_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for result in results:
            if isinstance(result, tuple):
                server_name, success = result
                warmup_status[server_name] = success
            else:
                # Exception occurred
                self.logger.error(f"Warmup task failed: {result}")

        success_count = sum(1 for v in warmup_status.values() if v)
        self.logger.info(
            f"🔥 MCP warmup complete: {success_count}/{len(server_names)} successful"
        )

        return warmup_status

    async def get_tools_for_agent(self, server_name: str) -> list[Any]:
        """
        Get MCP server's tools as Strands-compatible tool functions.

        This method:
        1. Fetches tool definitions from MCP server (tools/list)
        2. Creates async wrapper functions for each tool
        3. Returns list of callable tools for Strands Agent

        Args:
            server_name: MCP server name (e.g., "data", "intelligence")

        Returns:
            List of async tool functions compatible with Strands Agent

        Example:
            >>> factory = MCPFactory()
            >>> data_tools = await factory.get_tools_for_agent("data")
            >>> agent = Agent(model=model, tools=data_tools, ...)
        """
        from functools import wraps

        # Get MCP client
        client = self.create(server_name)

        # Fetch tool definitions from MCP server
        try:
            tool_definitions = await client.list_tools()
            self.logger.info(
                f"Loaded {len(tool_definitions)} tools from {server_name}",
                extra={"server": server_name, "tool_count": len(tool_definitions)},
            )
        except Exception as e:
            self.logger.error(
                f"Failed to load tools from {server_name}: {e}",
                exc_info=True,
            )
            return []

        # Create wrapper functions for each tool
        tools = []
        for tool_def in tool_definitions:
            tool_name = tool_def["name"]
            tool_description = tool_def.get("description", "")
            input_schema = tool_def.get("inputSchema", {})

            # Create factory function to fix closure issue
            def create_mcp_tool(
                name: str, server: str, mcp_client: MCPClient
            ) -> Any:
                """Factory function to create MCP tool wrapper with correct closure."""

                async def mcp_tool_wrapper(**kwargs: Any) -> dict[str, Any]:
                    """MCP tool wrapper (dynamically created)."""
                    try:
                        result = await mcp_client.call_tool(name, kwargs)
                        return result
                    except Exception as e:
                        self.logger.error(
                            f"MCP tool call failed: {server}.{name}",
                            extra={"error": str(e), "arguments": kwargs},
                            exc_info=True,
                        )
                        raise

                # Set function metadata
                mcp_tool_wrapper.__name__ = name
                mcp_tool_wrapper.__doc__ = tool_description

                return mcp_tool_wrapper

            # Create the wrapper function
            wrapper = create_mcp_tool(tool_name, server_name, client)

            # Decorate with @tool
            from strands import tool

            tool_func = tool(
                name=tool_name,
                description=tool_description,
                input_schema=input_schema,
            )(wrapper)

            tools.append(tool_func)

            self.logger.debug(
                f"Created tool wrapper: {server_name}.{tool_name}",
                extra={"tool_name": tool_name},
            )

        return tools

    async def close_all(self) -> None:
        """Close all MCP client connections."""
        for server_name, client in self._clients.items():
            try:
                await client.close()
                self.logger.debug(f"Closed MCP client: {server_name}")
            except Exception as e:
                self.logger.error(
                    f"Error closing MCP client {server_name}: {e}",
                    exc_info=True,
                )

        self._clients.clear()
