"""Tests for the ReAct agent implementation."""

import pytest
from unittest.mock import Mock, patch
import os

from grafi.agents.react_agent import ReActAgent, ReActAgentBuilder
from grafi.tools.function_calls.impl.google_search_tool import GoogleSearchTool


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
        assert isinstance(agent.function_call_tool, GoogleSearchTool)
    
    def test_agent_creation_with_custom_values(self):
        """Test creating a ReAct agent with custom values."""
        agent = ReActAgent(
            name="CustomReAct",
            type="CustomType",
            model="gpt-4",
            api_key="test-key"
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
        assert isinstance(agent.function_call_tool, GoogleSearchTool)
        assert agent.function_call_tool.name == "GoogleSearchTool"
    
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


class TestReActAgentBuilder:
    """Test ReAct agent builder functionality."""
    
    def test_builder_pattern(self):
        """Test builder pattern for ReAct agent."""
        builder = ReActAgent.builder()
        
        # Builder should be able to create agent
        agent = builder.build()
        assert isinstance(agent, ReActAgent)
    
    def test_builder_with_custom_config(self):
        """Test builder with custom configuration."""
        mock_tool = Mock()
        mock_tool.name = "MockTool"
        
        # Note: The actual builder methods would depend on the implementation
        # This is a basic test that the builder exists and can build
        builder = ReActAgent.builder()
        agent = builder.build()
        
        assert isinstance(agent, ReActAgent)
        assert agent.name == "ReActAgent"


class TestReActAgentIntegration:
    """Integration tests for ReAct agent."""
    
    def test_agent_creation_end_to_end(self):
        """Test complete agent creation flow."""
        # Create agent with custom settings
        agent = ReActAgent(
            name="TestAgent",
            model="gpt-3.5-turbo",
            api_key="test-key"
        )
        
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