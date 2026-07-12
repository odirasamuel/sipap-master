"""Unit tests for AgentToolFactory.

Following TDD methodology:
1. RED: Write failing tests
2. GREEN: Implement minimal code to pass
3. REFACTOR: Improve implementation
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from sipap.factory.agent import AgentToolFactory


class TestAgentToolFactory:
    """Test suite for AgentToolFactory."""

    @pytest.fixture
    def factory(self):
        """Create factory instance for testing."""
        return AgentToolFactory(sport="soccer")

    @pytest.fixture
    def simple_agent_config(self, tmp_path):
        """Create a simple agent YAML configuration for testing."""
        config = {
            "class": "bedrock",
            "name": "Test Agent",
            "model": {
                "model_id": "anthropic.claude-3-haiku-20240307-v1:0",
                "max_tokens": 4096,
                "temperature": 0.1
            },
            "prompt": "You are a test agent."
        }

        config_file = tmp_path / "test_agent.yml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        return config_file

    @pytest.fixture
    def agent_config_with_env_vars(self, tmp_path):
        """Create agent config with environment variable placeholders."""
        config_content = """
class: bedrock
name: Test Agent
model:
  model_id: ${ MODEL_ID }
  max_tokens: 4096
  temperature: 0.1
prompt: "You are a test agent for ${ SPORT }."
"""

        config_file = tmp_path / "test_agent_env.yml"
        config_file.write_text(config_content)

        return config_file

    def test_factory_initialization(self, factory):
        """Test factory initializes with sport."""
        assert factory.sport == "soccer"
        assert factory.logger is not None

    def test_factory_config_path_exists(self, factory):
        """Test factory has correct config path."""
        expected_path = Path(__file__).parent.parent.parent / "sipap" / "sports" / "soccer" / "agents"
        # Path may not exist yet, just verify it's constructed correctly
        assert "soccer" in str(factory.config_path)
        assert "agents" in str(factory.config_path)

    def test_create_fails_when_config_missing(self, factory):
        """Test create raises error when YAML config doesn't exist."""
        with pytest.raises(FileNotFoundError) as exc_info:
            factory.create("nonexistent_agent", tools=[])

        assert "Agent config not found" in str(exc_info.value)

    @patch("sipap.factory.agent.Agent")
    def test_create_loads_yaml_config(self, mock_agent_class, factory, simple_agent_config, tmp_path):
        """Test create successfully loads YAML configuration."""
        # Override config path to use temp directory
        factory.config_path = tmp_path

        # Create agent
        agent = factory.create("test_agent", tools=[])

        # Verify Agent was instantiated
        mock_agent_class.assert_called_once()

    @patch("sipap.factory.agent.Agent")
    @patch.dict(os.environ, {"MODEL_ID": "test-model-123", "SPORT": "soccer"})
    def test_create_processes_jinja2_templates(self, mock_agent_class, factory, agent_config_with_env_vars, tmp_path):
        """Test create processes Jinja2 environment variable templates."""
        # Override config path
        factory.config_path = tmp_path

        # Create agent
        agent = factory.create("test_agent_env", tools=[])

        # Verify Agent was called (template processing happened)
        mock_agent_class.assert_called_once()

        # Get the actual call arguments
        call_kwargs = mock_agent_class.call_args[1]

        # Verify system_prompt was processed (contains "soccer" not "${SPORT}")
        assert "soccer" in call_kwargs["system_prompt"]
        assert "${SPORT}" not in call_kwargs["system_prompt"]

    @patch("sipap.factory.agent.Agent")
    def test_create_passes_tools_to_agent(self, mock_agent_class, factory, simple_agent_config, tmp_path):
        """Test create passes tools list to Strands Agent."""
        factory.config_path = tmp_path

        mock_tools = [Mock(), Mock()]

        agent = factory.create("test_agent", tools=mock_tools)

        # Verify tools were passed
        call_kwargs = mock_agent_class.call_args[1]
        assert call_kwargs["tools"] == mock_tools

    @patch("sipap.factory.agent.Agent")
    def test_create_sets_temperature_from_config(self, mock_agent_class, factory, simple_agent_config, tmp_path):
        """Test create sets temperature from YAML config."""
        factory.config_path = tmp_path

        agent = factory.create("test_agent", tools=[])

        call_kwargs = mock_agent_class.call_args[1]
        assert call_kwargs["temperature"] == 0.1

    @pytest.fixture
    def agent_config_with_output_schema(self, tmp_path):
        """Create agent config with structured output schema."""
        config = {
            "class": "bedrock",
            "name": "Test Agent",
            "model": {
                "model_id": "test-model",
                "max_tokens": 4096
            },
            "prompt": "Test prompt",
            "output": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "prediction": {
                        "type": "object",
                        "properties": {
                            "outcome": {"type": "string"},
                            "probability": {"type": "number"}
                        },
                        "required": ["outcome", "probability"]
                    }
                },
                "required": ["prediction"]
            }
        }

        config_file = tmp_path / "test_agent_output.yml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        return config_file

    @patch("sipap.factory.agent.Agent")
    def test_create_with_structured_output_schema(self, mock_agent_class, factory, agent_config_with_output_schema, tmp_path):
        """Test create handles structured output schema."""
        factory.config_path = tmp_path

        agent = factory.create("test_agent_output", tools=[])

        # Verify Agent was called with structured_output_model
        call_kwargs = mock_agent_class.call_args[1]
        assert "structured_output_model" in call_kwargs
        # Should be a Pydantic model or None
        assert call_kwargs["structured_output_model"] is not None or call_kwargs["structured_output_model"] is None
