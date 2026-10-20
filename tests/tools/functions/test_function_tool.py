import json
import threading
import uuid
from typing import Optional

import pytest
from pydantic import BaseModel
from pydantic_core import PydanticSerializationError

from grafi.common.callable_component import CallableComponent
from grafi.common.callable_ref import CallableSerializationError
from grafi.common.exceptions import FunctionToolException
from grafi.common.import_ref import UntrustedImportError
from grafi.common.manifest import ManifestError
from grafi.common.manifest import env_secret
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.runtime import Delta
from grafi.runtime import deltas_to
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.tool import Tool


class DummyOutput(BaseModel):
    value: int


def dummy_function(messages: Messages):
    return DummyOutput(value=42)


async def async_dummy_function(messages: Messages):
    return DummyOutput(value=99)


async def async_generator_function(messages: Messages):
    for i in range(3):
        yield DummyOutput(value=i)


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
async def test_invoke_with_async_generator_function(invoke_context):
    tool = FunctionTool.builder().function(async_generator_function).build()
    input_messages = [Message(role="user", content="test")]
    messages = []
    async for msg in tool.invoke(invoke_context, input_messages):
        messages.extend(msg)
    assert len(messages) == 3
    for i, msg in enumerate(messages):
        assert isinstance(msg, Message)
        assert msg.role == "assistant"
        content = json.loads(msg.content)
        assert content["value"] == i


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
    assert "Function failed" in str(exc_info.value)
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


FUNCTION_TOOL = "grafi.tools.functions.function_tool:FunctionTool"


def test_dump(function_tool):
    d = function_tool.model_dump(mode="json")
    assert d == {
        "class": FUNCTION_TOOL,
        "tool_id": function_tool.tool_id,
        "name": "FunctionTool",
        "type": "FunctionTool",
        "oi_span_type": "TOOL",
        "role": "assistant",
        # A module-level function serializes as an import reference, not a
        # pickle blob.
        "function": {"ref": f"{__name__}:dummy_function"},
    }
    # A python-mode dump keeps the function itself.
    assert function_tool.model_dump()["function"] is dummy_function


def test_load_from_a_manifest_naming_the_class():
    """Test loading from a dictionary with a function reference."""
    data = {
        "class": FUNCTION_TOOL,
        "tool_id": "test-id",
        "name": "TestFunction",
        "oi_span_type": "TOOL",
        "role": "tool",
        "function": {"ref": f"{__name__}:dummy_function"},
    }

    tool = Tool.model_validate(data)

    assert isinstance(tool, FunctionTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "TestFunction"
    assert tool.role == "tool"
    assert tool.function is dummy_function


@pytest.mark.asyncio
async def test_round_trip(invoke_context):
    original = (
        FunctionTool.builder()
        .name("Generator")
        .role("tool")
        .function(async_generator_function)
        .build()
    )
    data = original.model_dump(mode="json")

    restored = Tool.model_validate(data)

    assert type(restored) is FunctionTool
    assert restored.tool_id == original.tool_id
    assert restored.name == "Generator"
    assert restored.role == "tool"
    assert restored.function is async_generator_function
    assert restored == original
    assert restored.model_dump(mode="json") == data
    # The function still works.
    outputs = await _outputs(restored, invoke_context)
    assert [[m.content for m in batch] for batch in outputs] == [
        ['{"value":0}'],
        ['{"value":1}'],
        ['{"value":2}'],
    ]


def test_a_function_that_cannot_be_referenced_is_not_saved():
    tool = FunctionTool.builder().function(lambda messages: "hi").build()

    with pytest.raises(PydanticSerializationError, match="Cannot serialize callable"):
        tool.model_dump(mode="json")


def test_a_function_from_an_untrusted_module_is_not_loaded():
    data = {"class": FUNCTION_TOOL, "function": {"ref": "os:getcwd"}}

    with pytest.raises(UntrustedImportError):
        Tool.model_validate(data)


def test_a_function_that_is_not_found_is_not_loaded():
    data = {"class": FUNCTION_TOOL, "function": {"ref": f"{__name__}:no_such"}}

    with pytest.raises(CallableSerializationError, match="Cannot import"):
        Tool.model_validate(data)


class Greeter(CallableComponent):
    """A function configured by its fields, one of them a secret."""

    greeting: str = "hello"
    token: Optional[str] = env_secret("GREETER_TOKEN")

    def __call__(self, messages: Messages) -> str:
        return f"{self.greeting}, {len(messages)}"


@pytest.mark.asyncio
async def test_a_callable_component_is_saved_as_its_class_and_fields(
    monkeypatch, invoke_context
):
    monkeypatch.setenv("GREETER_TOKEN", "the-token")
    original = FunctionTool.builder().function(Greeter(greeting="hi")).build()

    data = original.model_dump(mode="json")

    assert data["function"] == {
        "class": f"{__name__}:Greeter",
        "greeting": "hi",
        "token": {"env": "GREETER_TOKEN"},
    }
    assert "the-token" not in json.dumps(data)
    restored = Tool.model_validate(data)
    assert type(restored.function) is Greeter
    assert restored.function.greeting == "hi"
    assert restored.function.token == "the-token"
    assert restored == original
    outputs = await _outputs(restored, invoke_context)
    assert [[m.content for m in batch] for batch in outputs] == [["hi, 1"]]


def test_a_callable_component_saved_before_grafi_v2_loads():
    data = {
        "class": FUNCTION_TOOL,
        "function": {
            "component": f"{__name__}:Greeter",
            "config": {"greeting": "hey"},
        },
    }

    tool = Tool.model_validate(data)

    assert type(tool.function) is Greeter
    assert tool.function.greeting == "hey"
    assert tool.model_dump(mode="json")["function"]["class"] == f"{__name__}:Greeter"


def test_a_callable_component_holding_a_secret_is_never_saved(monkeypatch):
    monkeypatch.setenv("GREETER_TOKEN", "the-token")
    tool = FunctionTool.builder().function(Greeter(token="another")).build()

    with pytest.raises(ManifestError, match="Greeter.token"):
        tool.to_manifest()


def test_a_function_named_by_a_bare_string_is_not_loaded():
    data = {"class": FUNCTION_TOOL, "function": f"{__name__}:dummy_function"}

    with pytest.raises(CallableSerializationError, match='saved as {"ref"'):
        Tool.model_validate(data)


def test_a_grafi_function_that_is_not_a_condition_is_not_loaded():
    data = {
        "class": FUNCTION_TOOL,
        "function": {"ref": "grafi.common.manifest:import_path"},
    }

    with pytest.raises(UntrustedImportError, match="grafi.nodes.conditions"):
        Tool.model_validate(data)


async def _outputs(tool: FunctionTool, context: InvokeContext) -> list[Messages]:
    return [batch async for batch in tool.invoke(context, [Message(role="user")])]


@pytest.mark.asyncio
async def test_a_generator_streams_its_text_and_outputs_it_whole(invoke_context):
    def words(messages: Messages):  # Sync: it runs in a worker thread.
        yield "Hello, "
        yield "world"

    received: list[Delta] = []
    with deltas_to(received.append, "node"):
        [[message]] = await _outputs(FunctionTool(function=words), invoke_context)
    assert [delta.content for delta in received] == ["Hello, ", "world"]
    assert received[0].node_name == "node"
    assert message.content == "Hello, world"


@pytest.mark.asyncio
async def test_a_generator_yielding_values_outputs_them_and_only_streams_text(
    invoke_context,
):
    async def progress(messages: Messages):
        yield "working..."
        yield {"answer": 42}

    received: list[Delta] = []
    with deltas_to(received.append):
        [[message]] = await _outputs(FunctionTool(function=progress), invoke_context)
    assert [delta.content for delta in received] == ["working..."]
    assert json.loads(message.content) == {"answer": 42}


@pytest.mark.asyncio
async def test_messages_pass_as_they_are_and_none_outputs_nothing(invoke_context):
    reply = Message(role="tool", content="as is")
    assert await _outputs(FunctionTool(function=lambda _: reply), invoke_context) == [
        [reply]
    ]
    assert await _outputs(FunctionTool(function=lambda _: None), invoke_context) == []


@pytest.mark.asyncio
async def test_a_sync_function_runs_off_the_event_loop(invoke_context):
    loop_thread = threading.get_ident()
    ran_in: list[int] = []

    def blocking(messages: Messages) -> str:
        ran_in.append(threading.get_ident())
        return "done"

    [[message]] = await _outputs(FunctionTool(function=blocking), invoke_context)
    assert message.content == "done" and ran_in != [loop_thread]
