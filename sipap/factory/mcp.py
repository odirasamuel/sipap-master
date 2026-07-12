"""MCP Factory - Creates MCP client instances from YAML configuration.

Pattern adapted from Sentinel's factory pattern and sipap's AgentToolFactory.

This factory:
1. Loads MCP server configurations from YAML
2. Processes environment variables (${ENV})
3. Creates MCPClient instances
4. Handles connection pooling and lifecycle
"""

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
                "name": mcp_name,
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
