import json
import uuid

import pytest
from pydantic import BaseModel

from grafi.common.exceptions import FunctionToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.functions.function_tool import FunctionTool


class DummyOutput(BaseModel):
    value: int


def dummy_function(messages: Messages):
    return DummyOutput(value=42)


async def async_dummy_function(messages: Messages):
    return DummyOutput(value=99)


def list_output_function(messages: Messages):
    return [DummyOutput(value=1), DummyOutput(value=2)]


def string_output_function(messages: Messages):
    return "plain string response"


def dict_output_function(messages: Messages):
    return {"key": "value", "number": 123}


def error_function(messages: Messages):
    raise ValueError("Intentional error")


@pytest.fixture
def invoke_context():
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


@pytest.fixture
def function_tool():
    builder = FunctionTool.builder()
    tool = builder.function(dummy_function).build()
    return tool


@pytest.mark.asyncio
async def test_invoke_returns_message(function_tool, invoke_context):
    input_messages = [Message(role="user", content="test")]
    agen = function_tool.invoke(invoke_context, input_messages)
    messages = []
    async for msg in agen:
        messages.extend(msg)
    assert isinstance(messages[0], Message)
    assert messages[0].role == "assistant"
    assert "42" in messages[0].content


@pytest.mark.asyncio
async def test_invoke_with_async_function(invoke_context):
    tool = FunctionTool.builder().function(async_dummy_function).build()
    input_messages = [Message(role="user", content="test")]
    messages = []
    async for msg in tool.invoke(invoke_context, input_messages):
        messages.extend(msg)
    assert isinstance(messages[0], Message)
    assert "99" in messages[0].content


@pytest.mark.asyncio
async def test_invoke_with_list_output(invoke_context):
    tool = FunctionTool.builder().function(list_output_function).build()
    input_messages = [Message(role="user", content="test")]
    messages = []
    async for msg in tool.invoke(invoke_context, input_messages):
        messages.extend(msg)
    assert isinstance(messages[0], Message)
    content = json.loads(messages[0].content)
    assert len(content) == 2
    assert content[0]["value"] == 1
    assert content[1]["value"] == 2


@pytest.mark.asyncio
async def test_invoke_with_string_output(invoke_context):
    tool = FunctionTool.builder().function(string_output_function).build()
    input_messages = [Message(role="user", content="test")]
    messages = []
    async for msg in tool.invoke(invoke_context, input_messages):
        messages.extend(msg)
    assert messages[0].content == "plain string response"


@pytest.mark.asyncio
async def test_invoke_with_dict_output(invoke_context):
    tool = FunctionTool.builder().function(dict_output_function).build()
    input_messages = [Message(role="user", content="test")]
    messages = []
    async for msg in tool.invoke(invoke_context, input_messages):
        messages.extend(msg)
    content = json.loads(messages[0].content)
    assert content["key"] == "value"
    assert content["number"] == 123


@pytest.mark.asyncio
async def test_invoke_raises_function_tool_exception(invoke_context):
    tool = FunctionTool.builder().function(error_function).build()
    input_messages = [Message(role="user", content="test")]
    with pytest.raises(FunctionToolException) as exc_info:
        async for _ in tool.invoke(invoke_context, input_messages):
            pass
    assert "Async function execution failed" in str(exc_info.value)
    assert exc_info.value.tool_name == "FunctionTool"


def test_builder_with_custom_role():
    tool = (
        FunctionTool.builder()
        .function(dummy_function)
        .role("tool")
        .name("CustomTool")
        .build()
    )
    assert tool.role == "tool"
    assert tool.name == "CustomTool"


def test_to_dict(function_tool):
    d = function_tool.to_dict()
    assert d["name"] == "FunctionTool"
    assert d["type"] == "FunctionTool"
    assert d["role"] == "assistant"
    assert d["base_class"] == "FunctionTool"
    # Function is now serialized as base64-encoded cloudpickle
    assert "function" in d
    assert isinstance(d["function"], str)
    assert len(d["function"]) > 0


@pytest.mark.asyncio
async def test_from_dict():
    """Test deserialization from dictionary."""
    import base64

    import cloudpickle

    def test_function(messages):
        return DummyOutput(value=100)

    # Encode the function
    encoded_func = base64.b64encode(cloudpickle.dumps(test_function)).decode("utf-8")

    data = {
        "class": "FunctionTool",
        "tool_id": "test-id",
        "name": "TestFunction",
        "type": "FunctionTool",
        "oi_span_type": "TOOL",
        "role": "tool",
        "function": encoded_func,
    }

    tool = await FunctionTool.from_dict(data)

    assert isinstance(tool, FunctionTool)
    assert tool.name == "TestFunction"
    assert tool.role == "tool"
    assert tool.function is not None


@pytest.mark.asyncio
async def test_from_dict_roundtrip(function_tool, invoke_context):
    """Test that serialization and deserialization are consistent."""
    # Serialize to dict
    data = function_tool.to_dict()

    # Deserialize back
    restored = await FunctionTool.from_dict(data)

    # Verify key properties match
    assert restored.name == function_tool.name
    assert restored.role == function_tool.role
    assert restored.function is not None

    # Verify the function still works
    input_messages = [Message(role="user", content="test")]
    messages = []
    async for msg in restored.invoke(invoke_context, input_messages):
        messages.extend(msg)
    assert isinstance(messages[0], Message)
    assert "42" in messages[0].content
