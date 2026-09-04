"""Agent Tool Factory - Creates Strands Agent instances from YAML configurations.

Pattern adopted from Sentinel's sentinel/factory/agent.py

This factory:
1. Loads agent YAML files
2. Processes Jinja2 templates (environment variables)
3. Creates Strands Agent instances
4. Returns callable agents
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel, create_model
from strands import Agent


class AgentToolFactory:
    """Creates Agent instances from YAML configurations.

    This is the glue code that connects YAML config files to Strands Agents.

    Example:
        >>> factory = AgentToolFactory(sport="soccer")
        >>> agent = factory.create("statistical", tools=[...])
        >>> result = agent("Predict outcome for Arsenal vs Chelsea")
    """

    def __init__(self, sport: str, logger: logging.Logger | None = None):
        """Initialize factory.

        Args:
            sport: Sport type (e.g., "soccer")
            logger: Logger instance (optional)
        """
        self.sport = sport
        self.logger = logger or logging.getLogger(__name__)
        self._jinja_env = Environment(undefined=StrictUndefined)

        # Agent config base path
        self.config_path = Path(__file__).parent.parent / "sports" / sport / "agents"

    def create(self, agent_name: str, tools: list[Any]) -> Agent:
        """Create Strands Agent instance from YAML config.

        Args:
            agent_name: Agent name (e.g., "statistical", "ml")
            tools: List of loaded tools (MCP servers + Python functions)

        Returns:
            Strands Agent instance (callable)

        Raises:
            FileNotFoundError: If agent config file doesn't exist
        """
        # 1. Load YAML file
        yaml_path = self.config_path / f"{agent_name}.yml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"Agent config not found: {yaml_path}")

        with open(yaml_path, "r") as f:
            config_str = f.read()

        # 2. Process Jinja2 templates (environment variable substitution)
        config_str = self._process_template(config_str)

        # 3. Parse YAML
        config = yaml.safe_load(config_str)

        # 4. Create Bedrock model
        model = self._create_model(config["model"])

        # 5. Load structured output schema (if defined)
        structured_output_model = None
        if "output" in config:
            structured_output_model = self._create_output_model(config["output"])

        # 6. Create Strands Agent instance
        agent = Agent(
            model=model,
            system_prompt=config["prompt"],
            tools=tools,  # MCP servers + Python functions
            structured_output_model=structured_output_model
        )

        self.logger.info(f"Created agent: {agent_name} (sport={self.sport})")
        return agent

    def _process_template(self, template_str: str) -> str:
        """Process Jinja2 templates (${VAR} → environment variable).

        Args:
            template_str: Template string with ${VAR} placeholders

        Returns:
            Rendered template with environment variables substituted
        """
        # Replace ${ VAR } with {{ VAR }} for Jinja2
        template_str = re.sub(r"\$\{\s*(\w+)\s*\}", r"{{ \1 }}", template_str)

        # Render template with environment variables
        template = self._jinja_env.from_string(template_str)
        return template.render(**os.environ)

    def _create_model(self, model_config: dict[str, Any]) -> Any:
        """Create Bedrock model instance with Claude prompt caching enabled.

        Args:
            model_config: Model configuration from YAML

        Returns:
            Bedrock model instance with prompt caching

        Note:
            Claude prompt caching significantly reduces token usage by caching
            the system prompt. The system prompt (~1000+ tokens) is cached for
            1 hour, reducing costs by ~90% for repeated agent calls.
        """
        from strands.models import BedrockModel
        from strands.models.model import CacheConfig

        return BedrockModel(
            model_id=model_config["model_id"],
            max_tokens=model_config.get("max_tokens", 4096),
            temperature=model_config.get("temperature", 0.1),
            # System prompt caching enabled - saves ~70-80% tokens
            cache_config=CacheConfig(
                strategy="auto",  # Automatically detect and inject cache points
                ttl="1h",         # Cache for 1 hour (default is 5 minutes)
            ),
            # Re-enabled 2026-09-03: MODEL_ID switched from cross-region inference profile
            # (us.anthropic.claude-sonnet-4-5-20250929-v1:0) to direct regional model
            # (anthropic.claude-sonnet-4-5-20250929-v1:0). Inference profiles rejected
            # cache_tools="auto" with: Value 'auto' at 'toolConfig.tools.49.member.cachePoint.type'
            # Direct regional model supports tool definition caching (~1K-5K tokens per agent call).
            cache_tools="auto",
        )

    def _create_output_model(self, output_schema: dict[str, Any]) -> type[BaseModel] | None:
        """Convert JSON Schema to Pydantic model.

        Args:
            output_schema: JSON Schema definition

        Returns:
            Pydantic BaseModel class or None
        """
        if not output_schema or "properties" not in output_schema:
            return None

        # Extract properties from JSON Schema
        properties = output_schema["properties"]
        required_fields = output_schema.get("required", [])

        # Build Pydantic model fields
        field_definitions = {}
        for field_name, field_schema in properties.items():
            # Map JSON Schema types to Python types
            python_type = self._json_type_to_python(field_schema)

            # Mark as required or optional
            if field_name in required_fields:
                field_definitions[field_name] = (python_type, ...)
            else:
                field_definitions[field_name] = (python_type | None, None)  # type: ignore[assignment]

        # Create Pydantic model dynamically
        model = create_model("AgentOutput", **field_definitions)  # type: ignore[call-overload]

        return model  # type: ignore[no-any-return]

    def _json_type_to_python(self, field_schema: dict[str, Any]) -> type:
        """Map JSON Schema type to Python type.

        Args:
            field_schema: JSON Schema field definition

        Returns:
            Python type
        """
        json_type = field_schema.get("type", "string")

        type_mapping = {
            "string": str,
            "number": float,
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict
        }

        return type_mapping.get(json_type, str)
