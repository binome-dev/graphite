"""Tests for the spans the record decorators make, through the OpenTelemetry SDK:
their OpenInference attributes, nesting, failures and masking."""

import json
from types import SimpleNamespace

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from grafi.common.decorators.record_decorators import record_node_invoke
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.event_stores import EventStoreInMemory
from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services

_CONTEXT = InvokeContext(
    conversation_id="conversation", invoke_id="invoke", assistant_request_id="request"
)


class _EchoTool:
    tool_id = "echo-tool"
    name = "Echo"
    type = "FunctionTool"
    oi_span_type = SimpleNamespace(value="TOOL")

    @record_tool_invoke
    async def invoke(self, invoke_context, input_data):
        if input_data[0].content == "fail":
            raise ValueError("cannot echo")
        yield [Message(role="assistant", content=f"echo {input_data[0].content}")]


class _EchoNode:
    """Runs the tool inside its own span, publishing nothing."""

    node_id = "echo-node"
    name = "EchoNode"
    type = "Node"
    oi_span_type = SimpleNamespace(value="CHAIN")
    _subscribed_topics: dict = {}
    publish_to: list = []

    @record_node_invoke
    async def invoke(self, invoke_context, input_data):
        messages = [message for event in input_data for message in event.data]
        async for _ in _EchoTool().invoke(invoke_context, messages):
            pass
        return
        yield  # pragma: no cover - makes this an async generator


async def _run(component, content: str = "hi") -> None:
    async for _ in component.invoke(_CONTEXT, [Message(role="user", content=content)]):
        pass


async def _run_node(content: str = "hi") -> None:
    data = [Message(role="user", content=content)]
    consumed = [ConsumeFromTopicEvent(invoke_context=_CONTEXT, data=data)]
    async for _ in _EchoNode().invoke(_CONTEXT, consumed):
        pass


@pytest.fixture
def traced(monkeypatch):
    """Services tracing to an in-memory exporter, and that exporter."""
    for setting in ("OPENINFERENCE_HIDE_INPUTS", "OPENINFERENCE_HIDE_OUTPUTS"):
        monkeypatch.delenv(setting, raising=False)
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    services = ExecutionServices(
        event_store=EventStoreInMemory(), tracer=provider.get_tracer("grafi")
    )
    with bind_services(services):
        yield services, exporter


@pytest.mark.asyncio
async def test_a_span_carries_openinference_attributes(traced):
    _, exporter = traced
    await _run(_EchoTool())

    [span] = exporter.get_finished_spans()
    attributes = span.attributes
    assert span.name == "Echo.invoke"
    assert attributes["openinference.span.kind"] == "TOOL"
    assert attributes["session.id"] == "conversation"
    assert attributes["id"] == "echo-tool"
    assert attributes["invoke_id"] == "invoke"
    assert json.loads(attributes["input.value"])[0]["content"] == "hi"
    assert json.loads(attributes["output.value"])[0]["content"] == "echo hi"
    assert attributes["input.mime_type"] == "application/json"
    assert attributes["output.mime_type"] == "application/json"
    assert span.status.status_code is StatusCode.UNSET


@pytest.mark.asyncio
async def test_a_span_is_the_parent_of_the_spans_inside_it(traced):
    _, exporter = traced
    await _run_node()

    tool, node = exporter.get_finished_spans()
    assert node.attributes["openinference.span.kind"] == "CHAIN"
    assert tool.parent.span_id == node.context.span_id
    assert tool.context.trace_id == node.context.trace_id


@pytest.mark.asyncio
async def test_a_failure_marks_its_span_with_the_failed_events_error_id(traced):
    services, exporter = traced
    with pytest.raises(ValueError):
        await _run(_EchoTool(), "fail")

    [span] = exporter.get_finished_spans()
    [failed] = [
        event
        for event in await services.event_store.get_events()
        if isinstance(event, ToolFailedEvent)
    ]
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "cannot echo"
    assert span.attributes["error.type"] == "ValueError"
    assert span.attributes["error_id"] == failed.error_details["error_id"]
    assert [event.name for event in span.events] == ["exception"]
    assert "traceback" not in json.loads(span.attributes["error.details"])


@pytest.mark.asyncio
async def test_openinference_settings_hide_payloads(traced, monkeypatch):
    _, exporter = traced
    monkeypatch.setenv("OPENINFERENCE_HIDE_INPUTS", "true")
    await _run(_EchoTool())

    [span] = exporter.get_finished_spans()
    assert span.attributes["input.value"] == "__REDACTED__"
    assert "input.mime_type" not in span.attributes
    assert json.loads(span.attributes["output.value"])[0]["content"] == "echo hi"


@pytest.mark.asyncio
async def test_a_tracer_provider_set_globally_traces_the_default_services(
    monkeypatch,
):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)  # As setup_tracing.

    with bind_services(ExecutionServices()):
        await _run(_EchoTool())

    assert [span.name for span in exporter.get_finished_spans()] == ["Echo.invoke"]
