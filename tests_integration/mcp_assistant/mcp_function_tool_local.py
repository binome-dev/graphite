"""
Integration test for MCPFunctionTool.

This test directly invokes the MCPFunctionTool without using an LLM.
It tests the tool with serialized input and verifies the MCP response.

Prerequisites:
- Start the MCP server first: python tests_integration/mcp_assistant/hello_mcp_server.py
"""

import asyncio
import json

from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

from grafi.common.models.mcp_connections import StreamableHttpConnection
from grafi.common.models.message import Message
from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool


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
    # The message should have tool_calls to indicate it's a function call
    input_kwargs = {"name": "Graphite"}

    tool_call = ChatCompletionMessageToolCall(
        id="call_test_123",
        type="function",
        function=Function(name="hello", arguments=json.dumps(input_kwargs)),
    )

    input_message = Message(
        role="assistant",
        content=json.dumps(input_kwargs),  # kwargs as JSON in content
        tool_calls=[tool_call],
    )

    print(f"Input message: {input_message}")

    # Invoke the MCP function
    results = []
    async for result in mcp_tool.invoke_mcp_function([input_message]):
        results.append(result)

    # Verify the response
    assert len(results) == 1
    response = results[0]
    print(f"MCP Response: {response}")

    # The hello function should return "Hello, Graphite!"
    assert "Hello, Graphite!" in response
    print("Test passed!")


async def test_mcp_function_tool_with_different_input() -> None:
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

    # Test with different name
    input_kwargs = {"name": "World"}

    tool_call = ChatCompletionMessageToolCall(
        id="call_test_456",
        type="function",
        function=Function(name="hello", arguments=json.dumps(input_kwargs)),
    )

    input_message = Message(
        role="assistant",
        content=json.dumps(input_kwargs),
        tool_calls=[tool_call],
    )

    results = []
    async for result in mcp_tool.invoke_mcp_function([input_message]):
        results.append(result)

    assert len(results) == 1
    assert "Hello, World!" in results[0]
    print(f"Response: {results[0]}")
    print("Test with different input passed!")


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
    tool_call = ChatCompletionMessageToolCall(
        id="call_test_789",
        type="function",
        function=Function(name="hello", arguments=json.dumps(input_kwargs)),
    )

    input_message = Message(
        role="assistant",
        content=json.dumps(input_kwargs),
        tool_calls=[tool_call],
    )

    results = []
    async for result in restored_tool.invoke_mcp_function([input_message]):
        results.append(result)

    assert "Hello, Restored!" in results[0]
    print(f"Restored tool response: {results[0]}")
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
    await test_mcp_function_tool_with_different_input()

    print("\n" + "-" * 60)
    print("Test 3: Serialization Roundtrip")
    print("-" * 60)
    await test_mcp_function_tool_serialization_roundtrip()

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
