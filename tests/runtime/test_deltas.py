"""Deltas reach a caller streaming the run, from any task or thread of a step,
and only that caller; they are never published or stored."""

import asyncio
import threading
from typing import Any
from typing import List

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.runtime import Delta
from grafi.runtime import current_services
from grafi.runtime import deltas_for
from grafi.runtime import deltas_to
from grafi.runtime import emit_delta
from grafi.runtime import streaming
from grafi.tools.tool import Tool
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests_integration.async_execution.support import input_event


def test_without_a_receiver_emitting_does_nothing() -> None:
    assert not streaming()
    emit_delta("lost")  # No error, and no one gets it.


def test_a_binding_holds_for_its_block_and_none_unbinds() -> None:
    received: List[Delta] = []
    with deltas_to(received.append, "outer"):
        assert streaming()
        emit_delta("a")
        emit_delta("")  # Nothing to stream.
        with deltas_to(None):
            assert not streaming()
            emit_delta("dropped")
        with deltas_for("call"):  # As the function answering a call emits.
            emit_delta("b")
        emit_delta("c")
    assert not streaming()
    assert received == [
        Delta("a", "outer"),
        Delta("b", "outer", tool_call_id="call"),
        Delta("c", "outer"),
    ]


@pytest.mark.asyncio
async def test_deltas_from_a_worker_thread_arrive_on_the_loop() -> None:
    loop_thread = threading.get_ident()
    arrived_in: List[int] = []
    received: List[Delta] = []

    def receive(delta: Delta) -> None:
        arrived_in.append(threading.get_ident())
        received.append(delta)

    with deltas_to(receive):
        await asyncio.to_thread(emit_delta, "from a thread")
    await asyncio.sleep(0)  # Its callback runs on the loop.
    assert received == [Delta("from a thread")]
    assert arrived_in == [loop_thread]


class Speaker(Tool):
    """Streams its words, then outputs them, and records whether it streamed."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    words: List[str] = Field(default_factory=lambda: ["hello", " world"])
    streamed: List[bool] = Field(default_factory=list)
    inner: Any = Field(default=None, exclude=True)  # A workflow to run inside.

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.streamed.append(streaming())
        if self.inner is not None:  # As a tool calling another agent does.
            async for _ in self.inner.invoke(input_event()):
                pass
        for word in self.words:
            emit_delta(word)
        yield [Message(role="assistant", content="".join(self.words))]


def _workflow(tool: Tool, name: str = "speaker") -> EventDrivenWorkflow:
    node = (
        Node.builder()
        .name(name)
        .subscribe(InputTopic(name="agent_input_topic"))
        .tool(tool)
        .publish_to(OutputTopic(name="agent_output_topic"))
        .build()
    )
    return EventDrivenWorkflow.builder().node(node).build()


@pytest.mark.asyncio
async def test_a_streaming_caller_gets_the_deltas_and_then_the_stored_output() -> None:
    tool, event = Speaker(), input_event()
    async with asyncio.timeout(5):
        items = [item async for item in _workflow(tool).invoke(event, stream=True)]
    assert items[:2] == [Delta("hello", "speaker", 1), Delta(" world", "speaker", 1)]
    [output] = items[2:]
    assert output.data[0].content == "hello world"
    assert tool.streamed == [True]
    history = await current_services().event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    outputs = [
        record.data[0].content
        for record in history
        if isinstance(record, TopicEvent) and record.name == "agent_output_topic"
    ]
    assert outputs == ["hello world", "hello world"]  # Published, acknowledged.


@pytest.mark.asyncio
async def test_a_caller_not_streaming_gets_outputs_only() -> None:
    tool = Speaker()
    async with asyncio.timeout(5):
        items = [item async for item in _workflow(tool).invoke(input_event())]
    assert [item.data[0].content for item in items] == ["hello world"]
    assert tool.streamed == [False]  # So an LLM does not ask for a stream.


@pytest.mark.asyncio
async def test_a_run_inside_a_step_streams_to_its_own_caller_only() -> None:
    inner = Speaker(words=["inner"])
    outer = Speaker(words=["outer"], inner=_workflow(inner, "inner_node"))
    async with asyncio.timeout(5):
        items = [
            item
            async for item in _workflow(outer).invoke(input_event(), stream=True)
            if isinstance(item, Delta)
        ]
    assert items == [Delta("outer", "speaker", 1)]
    assert inner.streamed == [False]


def spell(word: str) -> Any:
    """Spell a word."""
    yield from word


@pytest.mark.asyncio
async def test_a_function_calls_deltas_name_its_node_step_and_call() -> None:
    from grafi.tools.function_calls.function_call_tool import FunctionCallTool

    tool = FunctionCallTool.builder().function(spell).build()
    call = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "spell", "arguments": '{"word": "hi"}'},
                }
            ],
        }
    )
    event = input_event()
    event.data = [call]
    async with asyncio.timeout(5):
        items = [
            item
            async for item in _workflow(tool, "functions").invoke(event, stream=True)
        ]
    assert items[:2] == [
        Delta("h", "functions", 1, "c1"),
        Delta("i", "functions", 1, "c1"),
    ]
    [answer] = items[2].data
    assert (answer.tool_call_id, answer.content) == ("c1", "hi")
