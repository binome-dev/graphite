"""
Integration test for MCPFunctionTool.

This test directly invokes the MCPFunctionTool without using an LLM.
It tests the tool with serialized input and verifies the MCP response.

Prerequisites:
- Start the MCP server first: python tests_integration/mcp_assistant/hello_mcp_server.py
"""

import asyncio
import json
import uuid
from typing import Optional

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.mcp_connections import StreamableHttpConnection
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class MCPFunctionToolAssistant(Assistant):
    """
    A simple assistant used in integration tests that routes input through an MCPFunctionTool.

    This class sets up an event-driven workflow with a single node that invokes an MCPFunctionTool and
    publishes the tool's responses to an output topic.

    Attributes:
        oi_span_type (OpenInferenceSpanKindValues): Span kind used for OpenInference tracing (set to AGENT).
        name (str): Logical name of the assistant.
        type (str): Type identifier for the assistant.
        mcp_function_tool (Optional[MCPFunctionTool]): The MCPFunctionTool instance invoked by the workflow node.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="MCPFunctionToolAssistant")
    type: str = Field(default="MCPFunctionToolAssistant")
    mcp_function_tool: Optional[MCPFunctionTool] = Field(default=None)

    def _construct_workflow(self) -> "MCPFunctionToolAssistant":
        agent_input_topic = InputTopic(name="agent_input_topic")
        agent_output_topic = OutputTopic(name="agent_output_topic")

        # Create a MCP function node
        mcp_function_node = (
            Node.builder()
            .name("MCPFunctionNode")
            .subscribe(agent_input_topic)
            .tool(self.mcp_function_tool)
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the MCP function node
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("MCPFunctionToolWorkflow")
            .node(mcp_function_node)
            .build()
        )

        return self


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_mcp_function_tool_direct_invocation() -> None:
    """
    Test MCPFunctionTool with direct invocation.

    This test:
    1. Initializes the MCPFunctionTool with the hello MCP server
    2. Creates a serialized input message with kwargs
    3. Calls invoke_mcp_function and verifies the output
    """
    # Configure MCP server connection
    server_params = {
        "hello": StreamableHttpConnection(
            {
                "url": "http://localhost:8000/mcp/",
                "transport": "http",
            }
        )
    }

    # Initialize the MCP function tool for the "hello" function
    mcp_tool = await (
        MCPFunctionTool.builder()
        .name("HelloMCPTool")
        .connections(server_params)
        .function_name("hello")
        .build()
    )

    # Verify the tool was initialized correctly
    assert mcp_tool.name == "HelloMCPTool"
    assert mcp_tool.function_name == "hello"
    assert mcp_tool._function_spec is not None
    assert mcp_tool._function_spec.name == "hello"

    print(f"Initialized MCPFunctionTool: {mcp_tool.name}")
    print(f"Function spec: {mcp_tool._function_spec}")

    # Create serialized input message
    # The message content should be JSON with the function arguments
    # The function call is inferred from this assistant message and its JSON content
    input_kwargs = {"name": "Graphite"}

    input_message = Message(
        role="assistant",
        content=json.dumps(input_kwargs),  # kwargs as JSON in content
    )

    print(f"Input message: {input_message}")

    # Invoke the MCP function
    results = []
    async for result in mcp_tool.function([input_message]):
        results.append(result)

    # Verify the response
    assert len(results) == 1
    response = results[0]
    print(f"MCP Response: {response}")

    # The hello function should return "Hello, Graphite!"
    assert "Hello, Graphite!" in response
    print("Test passed!")


async def test_mcp_function_tool_in_assistant() -> None:
    """
    Test MCPFunctionTool with different input values.
    """
    server_params = {
        "hello": StreamableHttpConnection(
            {
                "url": "http://localhost:8000/mcp/",
                "transport": "http",
            }
        )
    }

    mcp_tool = await (
        MCPFunctionTool.builder()
        .name("HelloMCPTool")
        .connections(server_params)
        .function_name("hello")
        .build()
    )

    mcp_assistant = MCPFunctionToolAssistant(mcp_function_tool=mcp_tool)

    # Test with different name
    input_kwargs = {"name": "Graphite"}

    input_message = Message(
        role="assistant",
        content=json.dumps(input_kwargs),
    )

    input_data = PublishToTopicEvent(
        invoke_context=get_invoke_context(),
        data=[input_message],
    )

    results = []
    async for result in mcp_assistant.invoke(input_data):
        results.append(result)

    print(f"Response: {results[0]}")
    print("Test with different input passed!")

    assert len(results) == 1
    assert "Hello, Graphite!" in results[0].data[0].content


async def test_mcp_function_tool_serialization_roundtrip() -> None:
    """
    Test MCPFunctionTool serialization and deserialization.
    """
    server_params = {
        "hello": StreamableHttpConnection(
            {
                "url": "http://localhost:8000/mcp/",
                "transport": "http",
            }
        )
    }

    original_tool = await (
        MCPFunctionTool.builder()
        .name("HelloMCPTool")
        .connections(server_params)
        .function_name("hello")
        .build()
    )

    # Serialize to dict
    tool_dict = original_tool.to_dict()
    print(f"Serialized tool: {json.dumps(tool_dict, indent=2, default=str)}")

    # Deserialize from dict
    restored_tool = await MCPFunctionTool.from_dict(tool_dict)

    assert restored_tool.name == original_tool.name
    assert restored_tool.function_name == original_tool.function_name
    print("Serialization roundtrip passed!")

    # Verify the restored tool still works
    input_kwargs = {"name": "Restored"}

    input_message = Message(
        role="assistant",
        content=json.dumps(input_kwargs),
    )

    results = []
    async for result in restored_tool.function([input_message]):
        results.append(result)

    print(f"Restored tool response: {results[0]}")
    assert "Hello, Restored!" in results[0]
    print("Restored tool invocation passed!")


async def run_all_tests() -> None:
    """Run all integration tests."""
    print("=" * 60)
    print("Running MCPFunctionTool Integration Tests")
    print("=" * 60)
    print("\nMake sure the MCP server is running:")
    print("  python tests_integration/mcp_assistant/hello_mcp_server.py\n")

    print("-" * 60)
    print("Test 1: Direct Invocation")
    print("-" * 60)
    await test_mcp_function_tool_direct_invocation()

    print("\n" + "-" * 60)
    print("Test 2: Different Input")
    print("-" * 60)
    await test_mcp_function_tool_in_assistant()

    print("\n" + "-" * 60)
    print("Test 3: Serialization Roundtrip")
    print("-" * 60)
    await test_mcp_function_tool_serialization_roundtrip()

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
