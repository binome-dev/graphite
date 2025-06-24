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


def test_invoke_returns_message(function_tool):
    context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )
    input_messages = [Message(role="user", content="test")]
    result = function_tool.invoke(context, input_messages)
    assert isinstance(result, list)
    assert isinstance(result[0], Message)
    assert result[0].role == "function"
    assert "42" in result[0].content


@pytest.mark.asyncio
async def test_a_invoke_returns_message(function_tool):
    context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )
    input_messages = [Message(role="user", content="test")]
    agen = function_tool.a_invoke(context, input_messages)
    messages = []
    async for msg in agen:
        messages.extend(msg)
    assert isinstance(messages[0], Message)
    assert messages[0].role == "function"
    assert "42" in messages[0].content


def test_to_dict(function_tool):
    d = function_tool.to_dict()
    assert d["name"] == "FunctionTool"
    assert d["type"] == "FunctionTool"
    assert d["function"] == "dummy_function"
