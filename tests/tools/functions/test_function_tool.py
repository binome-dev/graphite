import uuid

import pytest
from pydantic import BaseModel

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.functions.function_tool import FunctionTool


class DummyOutput(BaseModel):
    value: int


def dummy_function(messages: Messages):
    return DummyOutput(value=42)


@pytest.fixture
def function_tool():
    builder = FunctionTool.builder()
    tool = builder.function(dummy_function).build()
    return tool


@pytest.mark.asyncio
async def test_invoke_returns_message(function_tool):
    context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )
    input_messages = [Message(role="user", content="test")]
    agen = function_tool.invoke(context, input_messages)
    messages = []
    async for msg in agen:
        messages.extend(msg)
    assert isinstance(messages[0], Message)
    assert messages[0].role == "assistant"
    assert "42" in messages[0].content


def test_to_dict(function_tool):
    d = function_tool.to_dict()
    assert d["name"] == "FunctionTool"
    assert d["type"] == "FunctionTool"
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
        "function": encoded_func,
    }

    tool = await FunctionTool.from_dict(data)

    assert isinstance(tool, FunctionTool)
    assert tool.name == "TestFunction"
    assert tool.function is not None


@pytest.mark.asyncio
async def test_from_dict_roundtrip(function_tool):
    """Test that serialization and deserialization are consistent."""
    # Serialize to dict
    data = function_tool.to_dict()

    # Deserialize back
    restored = await FunctionTool.from_dict(data)

    # Verify key properties match
    assert restored.name == function_tool.name
    assert restored.function is not None

    # Verify the function still works
    context = InvokeContext(
        conversation_id="test_conv",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )
    input_messages = [Message(role="user", content="test")]
    messages = []
    async for msg in restored.invoke(context, input_messages):
        messages.extend(msg)
    assert isinstance(messages[0], Message)
    assert "42" in messages[0].content
