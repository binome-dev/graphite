"""Tests for the ReAct agent implementation."""

import os
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


# Set a dummy TAVILY_API_KEY to prevent initialization errors
os.environ["TAVILY_API_KEY"] = "test-tavily-key"

# Now import after setting the environment variable
from grafi.agents.react_agent import ReActAgent  # noqa: E402
from grafi.agents.react_agent import ReActAgentBuilder  # noqa: E402
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool  # noqa: E402


@pytest.fixture(autouse=True)
def mock_tavily_client():
    """Automatically mock TavilyClient for all tests."""
    with patch(
        "grafi.tools.function_calls.impl.tavily_tool.TavilyClient"
    ) as mock_client_class:
        # Create a mock instance
        mock_instance = MagicMock()
        mock_instance.search.return_value = {
            "query": "test query",
            "answer": "Mock search result",
            "results": [
                {
                    "title": "Mock Result",
                    "url": "https://example.com/mock",
                    "content": "Mock content for testing",
                    "score": 0.9,
                }
            ],
        }

        # Make the class return our mock instance when instantiated
        mock_client_class.return_value = mock_instance
        yield mock_client_class


class TestReActAgentBuilder:
    """Test ReAct agent builder pattern."""

    def test_agent_builder_creation(self):
        """Test creating a ReAct agent builder."""
        builder = ReActAgent.builder()
        assert isinstance(builder, ReActAgentBuilder)

    def test_agent_creation_with_defaults(self):
        """Test creating a ReAct agent with default values."""
        agent = ReActAgent()

        assert agent.name == "ReActAgent"
        assert agent.type == "ReActAgent"
        assert agent.model == "gpt-4o-mini"
        assert agent.system_prompt is not None
        assert isinstance(agent.function_call_tool, TavilyTool)

    def test_agent_creation_with_custom_values(self):
        """Test creating a ReAct agent with custom values."""
        agent = ReActAgent(
            name="CustomReAct", type="CustomType", model="gpt-4", api_key="test-key"
        )

        assert agent.name == "CustomReAct"
        assert agent.type == "CustomType"
        assert agent.model == "gpt-4"
        assert agent.api_key == "test-key"

    def test_agent_system_prompt(self):
        """Test that agent has a system prompt."""
        agent = ReActAgent()

        assert agent.system_prompt is not None
        assert "helpful and knowledgeable agent" in agent.system_prompt
        assert "search tool" in agent.system_prompt

    def test_agent_function_call_tool(self):
        """Test that agent has a function call tool."""
        agent = ReActAgent()

        assert agent.function_call_tool is not None
        assert isinstance(agent.function_call_tool, TavilyTool)
        assert agent.function_call_tool.name == "TavilyTestTool"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "env-test-key"})
    def test_api_key_from_environment(self):
        """Test that API key is read from environment."""
        agent = ReActAgent()
        assert agent.api_key == "env-test-key"

    def test_workflow_construction(self):
        """Test that agent can construct its workflow."""
        agent = ReActAgent()

        # The _construct_workflow method should return the agent itself
        constructed = agent._construct_workflow()
        assert constructed is agent

    def test_agent_oi_span_type(self):
        """Test that agent has correct OpenInference span type."""
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        agent = ReActAgent()
        assert agent.oi_span_type == OpenInferenceSpanKindValues.AGENT


class TestReActAgentIntegration:
    """Integration tests for ReAct agent."""

    def test_agent_creation_end_to_end(self):
        """Test complete agent creation flow."""
        # Create agent with custom settings
        agent = ReActAgent(name="TestAgent", model="gpt-3.5-turbo", api_key="test-key")

        # Verify agent properties
        assert agent.name == "TestAgent"
        assert agent.model == "gpt-3.5-turbo"
        assert agent.api_key == "test-key"

        # Verify agent can construct workflow
        constructed = agent._construct_workflow()
        assert constructed is agent

    def test_agent_serialization_properties(self):
        """Test that agent has serializable properties."""
        agent = ReActAgent()

        # Test that all required fields are accessible
        assert hasattr(agent, "name")
        assert hasattr(agent, "type")
        assert hasattr(agent, "model")
        assert hasattr(agent, "api_key")
        assert hasattr(agent, "system_prompt")
        assert hasattr(agent, "function_call_tool")

    def test_agent_inheritance(self):
        """Test that ReActAgent properly inherits from Assistant."""
        from grafi.assistants.assistant import Assistant

        agent = ReActAgent()
        assert isinstance(agent, Assistant)

    def test_multiple_agents_independent(self):
        """Test that multiple agents are independent."""
        agent1 = ReActAgent(name="Agent1", api_key="key1")
        agent2 = ReActAgent(name="Agent2", api_key="key2")

        assert agent1.name != agent2.name
        assert agent1.api_key != agent2.api_key
        assert agent1 is not agent2
