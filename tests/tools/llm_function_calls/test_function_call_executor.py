"""The function-call tool answers every call it is given with one tool message,
its content text; and how a node's command is chosen for a tool, and which calls
it passes the tool."""

import asyncio
import json
import threading
import time
from typing import Any
from typing import Callable
from typing import List
from typing import Optional

import pytest
from pydantic import BaseModel
from pydantic import Field

from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import FunctionCallException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.conditions import has_text_response
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.node import Node
from grafi.runtime import Delta
from grafi.runtime import current_services
from grafi.runtime import deltas_to
from grafi.tools.command import Command
from grafi.tools.command import use_command
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.impl.agent_calling_tool import AgentCallingTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm_command import LLMCommand
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests_integration.async_execution.support import input_event

CONTEXT = InvokeContext(conversation_id="c", invoke_id="i", assistant_request_id="r")


def _calls(*calls: tuple) -> Message:
    """An assistant message calling ``(id, name, arguments)`` for each call."""
    return Message(
        role="assistant",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
            for call_id, name, arguments in calls
        ],
    )


async def _results(tool: FunctionCallTool, messages: Messages) -> List[Message]:
    return [m async for batch in tool.invoke(CONTEXT, messages) for m in batch]


class Weather(BaseModel):
    city: str
    celsius: int


class WeatherTool(FunctionCallTool):
    @llm_function
    def forecast(self, city: str) -> str:
        """Tomorrow's weather."""
        return f"sunny in {city}"

    @llm_function
    async def report(self, city: str) -> Weather:
        """Today's weather."""
        return Weather(city=city, celsius=21)


@pytest.mark.asyncio
async def test_every_call_of_every_message_gets_one_result_in_order():
    results = await _results(
        WeatherTool(),
        [
            _calls(
                ("a", "forecast", {"city": "Paris"}), ("b", "report", {"city": "Oslo"})
            ),
            _calls(("c", "forecast", {"city": "Rome"})),
        ],
    )
    assert [(m.role, m.tool_call_id) for m in results] == [
        ("tool", "a"),
        ("tool", "b"),
        ("tool", "c"),
    ]
    assert results[0].content == "sunny in Paris"
    assert json.loads(results[1].content) == {"city": "Oslo", "celsius": 21}


@pytest.mark.asyncio
async def test_without_tool_calls_the_tool_yields_nothing():
    assert [
        m async for m in WeatherTool().invoke(CONTEXT, [Message(role="user")])
    ] == []


@pytest.mark.parametrize(
    ("returned", "content"),
    [(42, "42"), ({"a": [1, 2]}, '{"a":[1,2]}'), (None, "null"), ("text", "text")],
)
@pytest.mark.asyncio
async def test_a_result_is_always_text(returned: Any, content: str):
    tool = FunctionCallTool.builder().function(lambda: returned).build()
    name = tool.function_specs[0].name
    [result] = await _results(tool, [_calls(("a", name, {}))])
    assert result.content == content


@pytest.mark.asyncio
async def test_a_plain_function_needs_no_self():
    def add(x: int, y: int) -> int:
        """Add two numbers."""
        return x + y

    tool = FunctionCallTool.builder().function(add).build()
    [result] = await _results(tool, [_calls(("a", "add", {"x": 2, "y": 3}))])
    assert result.content == "5"


@pytest.mark.asyncio
async def test_a_function_taking_self_is_passed_the_tool():
    def whoami(self) -> str:
        """The tool's name."""
        return self.name

    tool = FunctionCallTool.builder().name("named").function(whoami).build()
    [result] = await _results(tool, [_calls(("a", "whoami", {}))])
    assert result.content == "named"


@pytest.mark.asyncio
async def test_arguments_are_validated_and_coerced_by_the_signature():
    class Point(BaseModel):
        x: int

    def shift(point: Point, by: int = 1) -> int:
        """Shift a point."""
        assert isinstance(point, Point)
        return point.x + by

    tool = FunctionCallTool.builder().function(shift).build()
    good, bad = await _results(
        tool,
        [
            _calls(
                ("a", "shift", {"point": {"x": "2"}, "by": "3"}),
                ("b", "shift", {"point": "not a point"}),
            )
        ],
    )
    assert good.content == "5"
    assert bad.content.startswith("Error: ValidationError")


@pytest.mark.asyncio
async def test_a_parameter_typed_invoke_context_is_passed_it_and_hidden_from_the_llm():
    def who(ctx: InvokeContext, greeting: str) -> str:
        """Greet the conversation."""
        return f"{greeting} {ctx.conversation_id}"

    tool = FunctionCallTool.builder().function(who).build()
    assert list(tool.function_specs[0].parameters.properties) == ["greeting"]
    [result] = await _results(tool, [_calls(("a", "who", {"greeting": "hi"}))])
    assert result.content == "hi c"


@pytest.mark.asyncio
async def test_errors_are_answered_so_the_llm_can_recover():
    def boom() -> None:
        """Fails."""
        raise ValueError("no luck")

    tool = FunctionCallTool.builder().function(boom).build()
    unknown, failed = await _results(
        tool, [_calls(("a", "missing", {}), ("b", "boom", {}))]
    )
    [malformed] = await _results(
        tool,
        [
            Message.model_validate(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "c",
                            "type": "function",
                            "function": {"name": "boom", "arguments": "{not json"},
                        }
                    ],
                }
            )
        ],
    )
    assert unknown.content == "Error: LookupError: No function 'missing'"
    assert failed.content == "Error: ValueError: no luck"
    assert malformed.content.startswith("Error: JSONDecodeError")


@pytest.mark.asyncio
async def test_on_error_raise_fails_with_a_function_call_exception():
    def boom() -> None:
        """Fails."""
        raise ValueError("no luck")

    tool = FunctionCallTool.builder().function(boom).on_error("raise").build()
    with pytest.raises(FunctionCallException) as raised:
        await _results(tool, [_calls(("a", "boom", {}))])
    assert raised.value.function_name == "boom"
    assert isinstance(raised.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_on_error_raise_cancels_the_other_calls():
    cancelled = asyncio.Event()

    async def slow() -> str:
        """Slow."""
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "never"

    def boom() -> None:
        """Fails."""
        raise ValueError("no luck")

    tool = (
        FunctionCallTool.builder()
        .function(slow)
        .function(boom)
        .on_error("raise")
        .build()
    )
    with pytest.raises(FunctionCallException):
        async with asyncio.timeout(5):
            await _results(tool, [_calls(("a", "slow", {}), ("b", "boom", {}))])
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_calls_run_concurrently_and_sync_functions_off_the_loop():
    loop_thread = threading.get_ident()
    threads: List[int] = []

    def blocking(n: int) -> int:
        """Blocks."""
        threads.append(threading.get_ident())
        time.sleep(0.2)
        return n

    tool = FunctionCallTool.builder().function(blocking).build()
    started = time.monotonic()
    results = await _results(
        tool, [_calls(*((str(n), "blocking", {"n": n}) for n in range(3)))]
    )
    assert [m.content for m in results] == ["0", "1", "2"]
    assert time.monotonic() - started < 0.5  # Not 3 x 0.2 one after another.
    assert loop_thread not in threads


@pytest.mark.asyncio
async def test_a_generator_streams_deltas_for_its_call_and_answers_its_text():
    async def spell(word: str):
        """Spell a word."""
        for letter in word:
            yield letter

    tool = FunctionCallTool.builder().function(spell).build()
    received: List[Delta] = []
    with deltas_to(received.append, "node"):
        [result] = await _results(tool, [_calls(("a", "spell", {"word": "hey"}))])
    assert result.content == "hey"
    assert received == [Delta(letter, "node", tool_call_id="a") for letter in "hey"]


def test_a_subclass_inherits_its_bases_functions_and_may_override_them():
    class Base(FunctionCallTool):
        @llm_function
        def ping(self) -> str:
            """Ping."""
            return "base"

        @llm_function
        def pong(self) -> str:
            """Pong."""
            return "base"

    class Child(Base):
        @llm_function
        def ping(self) -> str:
            """Ping, overridden."""
            return "child"

    class Grandchild(Child):
        pass

    assert sorted(spec.name for spec in Grandchild().function_specs) == ["ping", "pong"]
    assert Grandchild().functions["ping"] is Child.__dict__["ping"]


@pytest.mark.asyncio
async def test_an_undecorated_override_is_the_one_called():
    class Base(FunctionCallTool):
        @llm_function
        def ping(self) -> str:
            """Ping."""
            return "base"

    class Child(Base):
        def ping(self) -> str:
            return "child"

    [result] = await _results(Child(), [_calls(("a", "ping", {}))])
    assert result.content == "child"


def extra() -> str:
    """Extra."""
    return "extra"


@pytest.mark.asyncio
async def test_the_builder_adds_functions_beside_the_classs_own():
    tool = WeatherTool.builder().function(extra).build()
    assert [spec.name for spec in tool.function_specs] == [
        "forecast",
        "report",
        "extra",
    ]
    forecast, added = await _results(
        tool, [_calls(("a", "forecast", {"city": "Lyon"}), ("b", "extra", {}))]
    )
    assert (forecast.content, added.content) == ("sunny in Lyon", "extra")
    assert list(tool.to_dict()["functions"]) == ["extra"]


def test_an_agent_calling_tool_rebuilt_from_its_fields_keeps_one_spec():
    tool = (
        AgentCallingTool.builder()
        .agent_name("helper")
        .agent_description("Helps.")
        .argument_description("The question.")
        .agent_call(lambda context, message: {"content": "ok"})
        .build()
    )
    rebuilt = AgentCallingTool(**dict(tool))  # Its specs already hold its own.
    assert [spec.name for spec in rebuilt.function_specs] == ["helper"]


class _CustomCommand(Command):
    pass


@use_command(_CustomCommand)
class _CustomTool(FunctionCallTool):
    pass


class _CustomToolChild(_CustomTool):
    pass


def test_a_tool_runs_through_the_command_its_class_names_or_inherits():
    assert type(Command.for_tool(_CustomToolChild())) is _CustomCommand
    assert type(Command.for_tool(WeatherTool())) is FunctionCallCommand
    assert type(Command.for_tool(OpenAITool(api_key="k"))) is LLMCommand


@pytest.mark.asyncio
async def test_the_command_passes_its_tool_only_its_own_pending_calls():
    call = _calls(
        ("a", "forecast", {"city": "Paris"}),
        ("b", "forecast", {"city": "Oslo"}),
        ("c", "search", {"q": "x"}),  # Another tool's.
    )
    answered = Message(role="tool", tool_call_id="a", content="sunny")
    consumed = [ConsumeFromTopicEvent(invoke_context=CONTEXT, data=[call, answered])]

    [pending] = await FunctionCallCommand(tool=WeatherTool()).get_tool_input(
        CONTEXT, consumed
    )
    assert [c.id for c in pending.tool_calls] == ["b"]


def fa(n: int) -> str:
    """A."""
    return f"A:{n}"


def fb(n: int) -> str:
    """B."""
    return f"B:{n}"


class ScriptedLLM(LLM):
    """Calls the functions it is given, then answers."""

    calls: List[tuple] = Field(default_factory=list)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        answered = any(message.role == "tool" for message in input_data)
        yield [
            (
                Message(role="assistant", content="done")
                if answered
                else _calls(*self.calls)
            )
        ]


def _calling(*names: str) -> Callable[[PublishToTopicEvent], bool]:
    def calls(event: PublishToTopicEvent) -> bool:
        return any(
            call.function.name in names for call in event.data[-1].tool_calls or []
        )

    return calls


async def _answers(workflow: EventDrivenWorkflow) -> List[tuple]:
    """Each tool result the run stored, as (call id, content)."""
    event = input_event()
    async with asyncio.timeout(5):
        [_ async for _ in workflow.invoke(event)]
    history = await current_services().event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    return sorted(
        (message.tool_call_id, message.content)
        for record in history
        if isinstance(record, PublishToTopicEvent) and record.name == "results"
        for message in record.data
    )


def _workflow(llm: Node, *function_nodes: Node) -> EventDrivenWorkflow:
    builder = EventDrivenWorkflow.builder().node(llm)
    for node in function_nodes:
        builder.node(node)
    return builder.build()


def _llm_node(calls: List[tuple], *routes: tuple) -> Node:
    results = Topic(name="results")
    builder = (
        Node.builder()
        .name("llm")
        .subscribe(
            SubscriptionBuilder()
            .subscribed_to(InputTopic(name="agent_input_topic"))
            .or_()
            .subscribed_to(results)
            .build()
        )
        .tool(ScriptedLLM(calls=calls))
        .publish_to(OutputTopic(name="agent_output_topic"), when=has_text_response)
    )
    for topic, when in routes:
        builder.publish_to(topic, when=when)
    return builder.build()


def _answering(name: str, function: Callable, calls: Topic) -> Node:
    return (
        Node.builder()
        .name(name)
        .subscribe(calls)
        .tool(FunctionCallTool.builder().function(function).build())
        .publish_to(Topic(name="results"))
        .build()
    )


@pytest.mark.asyncio
async def test_parallel_calls_routed_to_different_nodes_are_each_answered_once():
    ta, tb = Topic(name="ta"), Topic(name="tb")
    llm = _llm_node(
        [("c1", "fa", {"n": 1}), ("c2", "fb", {"n": 2})],
        (ta, _calling("fa")),
        (tb, _calling("fb")),
    )
    workflow = _workflow(llm, _answering("a", fa, ta), _answering("b", fb, tb))
    assert await _answers(workflow) == [("c1", "A:1"), ("c2", "B:2")]


@pytest.mark.asyncio
async def test_a_call_to_a_function_the_llm_was_not_offered_gets_one_error():
    calls = Topic(name="calls")
    llm = _llm_node(
        [("c1", "fa", {"n": 1}), ("c2", "invented", {})], (calls, has_tool_call)
    )
    workflow = _workflow(llm, _answering("a", fa, calls), _answering("b", fb, calls))
    assert await _answers(workflow) == [
        ("c1", "A:1"),
        ("c2", "Error: LookupError: No function 'invented'"),
    ]
    first, second = (workflow.nodes[name]._command for name in ("a", "b"))
    assert first.offered == {"calls": {"fa", "fb"}} and second.offered == {}


@pytest.mark.parametrize("shared_first", [False, True])
@pytest.mark.asyncio
async def test_a_node_reading_two_llms_calls_answers_each_call_once(shared_first):
    # LLM "a" publishes to ta, LLM "b" to tb; f answers fa from ta, g answers
    # fb from ta and tb. Whichever node comes first, a's call to fa gets one
    # answer, f's: b's offer never makes g answer a's calls.
    ta, tb, results = Topic(name="ta"), Topic(name="tb"), Topic(name="results")
    a = (
        Node.builder()
        .name("a")
        .subscribe(
            SubscriptionBuilder()
            .subscribed_to(InputTopic(name="agent_input_topic"))
            .or_()
            .subscribed_to(results)
            .build()
        )
        .tool(ScriptedLLM(calls=[("c1", "fa", {"n": 1})]))
        .publish_to(ta, when=has_tool_call)
        .publish_to(OutputTopic(name="agent_output_topic"), when=has_text_response)
        .build()
    )
    b = (
        Node.builder()
        .name("b")
        .subscribe(Topic(name="never_published"))
        .tool(ScriptedLLM())
        .publish_to(tb)
        .build()
    )
    f = _answering("f", fa, ta)
    g = (
        Node.builder()
        .name("g")
        .subscribe(
            SubscriptionBuilder().subscribed_to(ta).or_().subscribed_to(tb).build()
        )
        .tool(FunctionCallTool.builder().function(fb).build())
        .publish_to(results)
        .build()
    )
    workflow = _workflow(a, b, *((g, f) if shared_first else (f, g)))
    assert await _answers(workflow) == [("c1", "A:1")]


@pytest.mark.parametrize("shared_first", [False, True])
@pytest.mark.asyncio
async def test_a_topic_two_llms_call_on_knows_what_both_were_offered(shared_first):
    # LLM "a" calls fa on ta and fb on shared; LLM "b" also calls on shared.
    # g, reading shared, answers fb, and never a's fa, which f answers.
    ta, shared, results = Topic(name="ta"), Topic(name="shared"), Topic(name="results")
    a = (
        Node.builder()
        .name("a")
        .subscribe(
            SubscriptionBuilder()
            .subscribed_to(InputTopic(name="agent_input_topic"))
            .or_()
            .subscribed_to(results)
            .build()
        )
        .tool(ScriptedLLM(calls=[("c1", "fa", {"n": 1}), ("c2", "fb", {"n": 2})]))
        .publish_to(ta, when=_calling("fa"))
        .publish_to(shared, when=_calling("fb"))
        .publish_to(OutputTopic(name="agent_output_topic"), when=has_text_response)
        .build()
    )
    b = (
        Node.builder()
        .name("b")
        .subscribe(Topic(name="never_published"))
        .tool(ScriptedLLM())
        .publish_to(shared)
        .build()
    )
    f, g = _answering("f", fa, ta), _answering("g", fb, shared)
    workflow = _workflow(a, b, *((g, f) if shared_first else (f, g)))
    assert await _answers(workflow) == [("c1", "A:1"), ("c2", "B:2")]


@pytest.mark.asyncio
async def test_a_message_reaching_a_node_on_two_topics_is_answered_once():
    # Both routes match, so the node reading both topics gets two copies.
    t1, t2, results = Topic(name="t1"), Topic(name="t2"), Topic(name="results")
    llm = _llm_node(
        [("c1", "fa", {"n": 1}), ("c2", "invented", {})],
        (t1, has_tool_call),
        (t2, has_tool_call),
    )
    a = (
        Node.builder()
        .name("a")
        .subscribe(
            SubscriptionBuilder().subscribed_to(t1).or_().subscribed_to(t2).build()
        )
        .tool(FunctionCallTool.builder().function(fa).build())
        .publish_to(results)
        .build()
    )
    assert await _answers(_workflow(llm, a)) == [
        ("c1", "A:1"),
        ("c2", "Error: LookupError: No function 'invented'"),
    ]


@pytest.mark.asyncio
async def test_a_parameter_typed_optional_invoke_context_is_passed_it():
    def who(ctx: Optional[InvokeContext] = None) -> str:
        """Who."""
        assert ctx is not None
        return ctx.conversation_id

    tool = FunctionCallTool.builder().function(who).build()
    assert tool.function_specs[0].parameters.properties == {}
    [result] = await _results(tool, [_calls(("a", "who", {}))])
    assert result.content == "c"


@pytest.mark.asyncio
async def test_the_builder_replaces_a_function_of_the_same_name():
    def forecast(city: str) -> str:
        """Tomorrow's weather, from elsewhere."""
        return f"rain in {city}"

    tool = WeatherTool.builder().function(forecast).build()
    assert [spec.name for spec in tool.function_specs] == ["report", "forecast"]
    assert tool.function_specs[1].description == "Tomorrow's weather, from elsewhere."
    [result] = await _results(tool, [_calls(("a", "forecast", {"city": "Rome"}))])
    assert result.content == "rain in Rome"
