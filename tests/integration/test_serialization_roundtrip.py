"""End-to-end serialization / deserialization integration tests.

These build real assistants, workflows, tools, and topics, round-trip them
through the JSON manifest (``to_dict`` -> ``json`` -> ``from_dict``), and assert
the restored objects behave identically. Together they cover every pickle-free
callable form:

* **reference**  -- importable module-level functions / conditions
* **component**  -- :class:`CallableComponent` subclasses (functions and conditions)
* class-discovered ``@llm_function`` methods (reconstructed, not serialized)

plus the hard-failure modes (lambdas, closures, legacy pickle manifests).
"""

import json
import uuid
from unittest.mock import patch

import pytest

from grafi.assistants.assistant import Assistant
from grafi.common.callable_component import CallableComponent
from grafi.common.callable_ref import CallableSerializationError
from grafi.common.callable_ref import serialize_callable
from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.tool_factory import ToolFactory
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_base import always_true
from grafi.topics.topic_factory import TopicFactory
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

# --------------------------------------------------------------------------- #
# Module-level building blocks. Defined at module scope so they serialize as
# import references ({"ref": "<module>:<name>"}) and resolve on deserialization.
# --------------------------------------------------------------------------- #


def shout(messages: Messages) -> str:
    """A FunctionTool function -> serializes as a reference."""
    return (messages[-1].content or "").upper()


def has_content(event: PublishToTopicEvent) -> bool:
    """A topic condition -> serializes as a reference."""
    return event.data[-1].content is not None


class Prefixer(CallableComponent):
    """A FunctionTool function as a component -> serializes as config."""

    prefix: str

    def __call__(self, messages: Messages) -> str:
        return f"{self.prefix}{messages[-1].content}"


class MinContentLength(CallableComponent):
    """A topic condition as a component -> serializes as config."""

    minimum: int

    def __call__(self, event: PublishToTopicEvent) -> bool:
        return len(event.data[-1].content or "") >= self.minimum


class GreetTool(FunctionCallTool):
    """A FunctionCallTool subclass; its method is discovered from the class and
    reconstructed on load rather than serialized."""

    name: str = "GreetTool"
    type: str = "GreetTool"

    @llm_function
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def _event(content: str) -> PublishToTopicEvent:
    return PublishToTopicEvent(
        invoke_context=_invoke_context(),
        data=[Message(role="user", content=content)],
    )


def _single_function_workflow(function: object) -> EventDrivenWorkflow:
    """Input -> FunctionTool(function) -> Output. Runs without any LLM."""
    agent_input = InputTopic(name="agent_input")
    agent_output = OutputTopic(name="agent_output")
    node = (
        Node.builder()
        .name("FunctionNode")
        .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
        .tool(FunctionTool.builder().function(function).build())
        .publish_to(agent_output)
        .build()
    )
    return EventDrivenWorkflow.builder().name("roundtrip_workflow").node(node).build()


def _build_assistant(workflow: EventDrivenWorkflow) -> Assistant:
    with patch.object(Assistant, "_construct_workflow"):
        return Assistant(name="RoundTripAssistant", workflow=workflow)


async def _roundtrip(assistant: Assistant) -> Assistant:
    """to_dict -> JSON text -> from_dict, exercising the real manifest path."""
    manifest = json.loads(json.dumps(assistant.to_dict()))
    return await Assistant.from_dict(manifest)


async def _run(assistant: Assistant, text: str) -> str:
    outputs = []
    async for event in assistant.invoke(_event(text), is_sequential=True):
        outputs.append(event)
    return outputs[0].data[0].content


# --------------------------------------------------------------------------- #
# Full assistant round-trips that also execute the restored workflow
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_function_reference_roundtrips_and_executes():
    assistant = _build_assistant(_single_function_workflow(shout))
    assert await _run(assistant, "hi there") == "HI THERE"

    manifest = assistant.to_dict()
    fn = manifest["workflow"]["nodes"]["FunctionNode"]["tool"]["function"]
    assert fn == {"ref": f"{__name__}:shout"}

    restored = await _roundtrip(assistant)
    assert await _run(restored, "hi there") == "HI THERE"


@pytest.mark.asyncio
async def test_component_function_roundtrips_and_executes():
    assistant = _build_assistant(_single_function_workflow(Prefixer(prefix=">> ")))
    assert await _run(assistant, "hello") == ">> hello"

    manifest = assistant.to_dict()
    fn = manifest["workflow"]["nodes"]["FunctionNode"]["tool"]["function"]
    assert fn == {"component": f"{__name__}:Prefixer", "config": {"prefix": ">> "}}

    restored = await _roundtrip(assistant)
    assert await _run(restored, "hello") == ">> hello"


@pytest.mark.asyncio
async def test_manifest_contains_no_pickle():
    assistant = _build_assistant(_single_function_workflow(shout))
    blob = json.dumps(assistant.to_dict())
    assert "base64" not in blob
    assert "pickle" not in blob


# --------------------------------------------------------------------------- #
# Topic condition forms (reference / component / default)
# --------------------------------------------------------------------------- #


async def _condition_roundtrip(topic: Topic) -> Topic:
    data = json.loads(json.dumps(topic.to_dict()))
    return await TopicFactory.from_dict(data)


@pytest.mark.asyncio
async def test_default_condition_is_a_reference():
    topic = Topic(name="t")
    assert topic.to_dict()["condition"] == {
        "ref": f"{always_true.__module__}:always_true"
    }
    restored = await _condition_roundtrip(topic)
    assert restored.condition(_event("x")) is True


@pytest.mark.asyncio
async def test_module_function_condition_roundtrips():
    topic = Topic(name="t", condition=has_content)
    assert topic.to_dict()["condition"] == {"ref": f"{__name__}:has_content"}
    restored = await _condition_roundtrip(topic)
    assert restored.condition is has_content
    assert restored.condition(_event("x")) is True


@pytest.mark.asyncio
async def test_component_condition_roundtrips():
    topic = Topic(name="t", condition=MinContentLength(minimum=3))
    assert topic.to_dict()["condition"] == {
        "component": f"{__name__}:MinContentLength",
        "config": {"minimum": 3},
    }
    restored = await _condition_roundtrip(topic)
    assert restored.condition(_event("yes")) is True
    assert restored.condition(_event("no")) is False


# -- default condition (omitted / empty falls back to always_true) ----------


@pytest.mark.asyncio
async def test_condition_omitted_defaults_to_always_true():
    topic = await TopicFactory.from_dict({"name": "t", "type": "Topic"})
    assert topic.condition is always_true
    assert topic.condition(_event("anything")) is True


@pytest.mark.asyncio
async def test_condition_empty_string_defaults_to_always_true():
    topic = await TopicFactory.from_dict(
        {"name": "t", "type": "Topic", "condition": ""}
    )
    assert topic.condition is always_true


# --------------------------------------------------------------------------- #
# FunctionCallTool subclass: methods reconstructed from the class, not serialized
# --------------------------------------------------------------------------- #


@pytest.fixture
def greet_tool_registered():
    ToolFactory.register_tool_class("GreetTool", GreetTool)
    yield
    ToolFactory.unregister_tool_class("GreetTool")


@pytest.mark.asyncio
async def test_function_call_subclass_method_reconstructed(greet_tool_registered):
    tool = GreetTool()
    data = tool.to_dict()
    # The @llm_function method is intrinsic to the class -> not serialized...
    assert data["functions"] == {}
    # ...but its spec is preserved so the LLM still sees it.
    assert [s["name"] for s in data["function_specs"]] == ["greet"]

    restored = await ToolFactory.from_dict(json.loads(json.dumps(data)))
    assert isinstance(restored, GreetTool)
    assert "greet" in restored.functions
    assert restored.functions["greet"](restored, "Ada") == "Hello, Ada!"


# --------------------------------------------------------------------------- #
# Hard-failure modes (no silent pickle fallback)
# --------------------------------------------------------------------------- #


def test_unserializable_closure_raises():
    def make_adder(n):
        def adder(messages):
            return n

        return adder

    tool = FunctionTool.builder().function(make_adder(1)).build()
    with pytest.raises(CallableSerializationError, match="without pickle"):
        tool.to_dict()


@pytest.mark.asyncio
async def test_legacy_pickle_manifest_is_rejected():
    """A manifest with the old base64 pickle payload fails with a clear error."""
    legacy = {
        "class": "FunctionTool",
        "name": "Legacy",
        "type": "FunctionTool",
        "oi_span_type": "TOOL",
        "role": "assistant",
        "function": "gASVbase64legacyblob",
    }
    with pytest.raises(CallableSerializationError, match="pickle payload"):
        await FunctionTool.from_dict(legacy)


def test_serialize_callable_forms_directly():
    """Spot-check the two forms at the helper level."""
    assert serialize_callable(shout) == {"ref": f"{__name__}:shout"}
    assert serialize_callable(Prefixer(prefix="x")) == {
        "component": f"{__name__}:Prefixer",
        "config": {"prefix": "x"},
    }
    # A lambda is neither a reference nor a component -> rejected (no pickle).
    with pytest.raises(CallableSerializationError, match="without pickle"):
        serialize_callable(lambda e: True)


# --------------------------------------------------------------------------- #
# Manifest written to disk and reloaded (generate_manifest path)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generated_manifest_file_roundtrips(tmp_path):
    assistant = _build_assistant(_single_function_workflow(shout))
    assistant.generate_manifest(output_dir=str(tmp_path))

    manifest_path = tmp_path / "RoundTripAssistant_manifest.json"
    assert manifest_path.exists()

    restored = await Assistant.from_dict(json.loads(manifest_path.read_text()))
    assert await _run(restored, "from disk") == "FROM DISK"
