import asyncio
import copy
import warnings
from typing import Any
from typing import List

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ValidationError

from grafi.common.decorators.llm_function import llm_function
from grafi.common.decorators.record_decorators import record_workflow_invoke
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.common.manifest import ManifestError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.conditions import has_text_response
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm import LLM
from grafi.tools.tool import Tool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_base import TopicType
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.workflow import Workflow
from grafi.workflows.workflow import WorkflowBuilder
from tests.wiring import answered_by
from tests.wiring import offered_to


class MockTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context, input_data):
        return [Message(role="assistant", content="mock response")]


class Other(MockTool):
    async def invoke(self, invoke_context, input_data):
        return [Message(role="assistant", content="other response")]


class _NamesItsFunctions(LLM):
    """Answers with the names of the functions it is offered."""

    def names(self) -> str:
        return ",".join(spec.name for spec in self.get_function_specs()) or "none"

    async def invoke(self, invoke_context, input_data):
        return [Message(role="assistant", content=self.names())]


class _AsksAnother(_NamesItsFunctions):
    """Answers with what it is offered, and what an LLM it calls is."""

    async def invoke(self, invoke_context, input_data):
        other = _NamesItsFunctions().names()
        return [Message(role="assistant", content=f"{self.names()}|{other}")]


@llm_function
def get_time(city: str) -> str:
    """Get the time in a city.

    Args:
        city: The city to look up.
    """
    return "noon"


@llm_function
def get_weather(city: str) -> str:
    """Get the weather in a city.

    Args:
        city: The city to look up.
    """
    return f"Sunny in {city}"


class TestEventDrivenWorkflowBuilder:
    def test_builder_returns_workflow_builder(self):
        """Test that builder() returns a WorkflowBuilder instance."""
        builder = EventDrivenWorkflow.builder()
        assert isinstance(builder, WorkflowBuilder)

    def test_builder_creates_event_driven_workflow(self):
        """Test that the builder can create an EventDrivenWorkflow with proper topics."""
        # Create a complete workflow with required topics via builder
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        workflow = EventDrivenWorkflow.builder().node(node).build()
        assert isinstance(workflow, EventDrivenWorkflow)


class TestEventDrivenWorkflowInit:
    def test_default_initialization(self):
        """Test default initialization of EventDrivenWorkflow requires topics."""
        # EventDrivenWorkflow requires input and output topics, so default initialization should fail
        with pytest.raises(
            WorkflowError,
            match="must have at least one topic of type 'agent_input_topic'",
        ):
            EventDrivenWorkflow()

    def test_initialization_with_nodes_and_topics(self):
        """Test initialization with nodes that have topic subscriptions."""
        # Create mock topics
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        # Create mock node
        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        workflow = EventDrivenWorkflow(nodes={"test_node": node})

        assert "test_input" in workflow.topics
        assert "test_output" in workflow.topics
        assert "test_input" in workflow._wire().readers
        assert workflow._wire().readers["test_input"] == ["test_node"]

    def test_initialization_missing_input_topic_raises_error(self):
        """Test that missing agent input topic raises WorkflowError."""
        output_topic = OutputTopic(name="test_output")
        mock_tool = MockTool()
        missing_topic = InputTopic(
            name="missing_input", type=TopicType.NONE_TOPIC_TYPE
        )  # Wrong type
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=missing_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        with pytest.raises(
            WorkflowError,
            match="must have at least one topic of type 'agent_input_topic'",
        ):
            EventDrivenWorkflow(nodes={"test_node": node})

    def test_initialization_missing_output_topic_raises_error(self):
        """Test that missing agent output topic raises WorkflowError."""
        input_topic = InputTopic(name="test_input")
        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(),
        )

        with pytest.raises(
            WorkflowError,
            match="must have at least one topic of type 'agent_output_topic'",
        ):
            EventDrivenWorkflow(nodes={"test_node": node})


class TestEventDrivenWorkflowTopicManagement:
    @pytest.fixture
    def workflow_with_topics(self):
        """Create a workflow with input and output topics."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        return EventDrivenWorkflow(nodes={"test_node": node})


class TestEventDrivenWorkflowEventHandling:
    @pytest.fixture
    def workflow_with_nodes(self):
        """Create a workflow with nodes for testing event handling."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        workflow = EventDrivenWorkflow(nodes={"test_node": node})
        return workflow


class TestEventDrivenWorkflowOutputEvents:
    @pytest.fixture
    async def workflow_with_output_topics(self):
        """Create a workflow with various output topics."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        workflow = EventDrivenWorkflow(nodes={"test_node": node})

        # Add some mock events to output topics
        mock_event = PublishToTopicEvent(
            name="test_output",
            publisher_name="test_publisher",
            publisher_type="test_type",
            invoke_context=InvokeContext(
                conversation_id="test", invoke_id="test", assistant_request_id="test"
            ),
            data=[Message(role="assistant", content="test output")],
            consumed_event_ids=[],
            offset=0,
        )
        await workflow.topics["test_output"].add_event(mock_event)

        return workflow


class TestEventDrivenWorkflowInvoke:
    @pytest.fixture
    def simple_workflow(self):
        """Create a simple workflow for invoke testing."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        return EventDrivenWorkflow(nodes={"test_node": node})


class TestEventDrivenWorkflowAsyncInvoke:
    @pytest.fixture
    def async_workflow(self):
        """Create a workflow for async testing."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        return EventDrivenWorkflow(nodes={"test_node": node})

    def test_invoke_method_exists(self, async_workflow):
        """Test that invoke method exists and is async."""
        assert hasattr(async_workflow, "invoke")
        assert callable(async_workflow.invoke)

    @pytest.mark.asyncio
    async def test_invoke_basic_flow(self, async_workflow):
        """Test basic async invoke flow."""
        # This test verifies that the invoke method can be called
        # and properly sets up the async machinery

        invoke_context = InvokeContext(
            conversation_id="test", invoke_id="test", assistant_request_id="test"
        )
        input_messages = [Message(role="user", content="test input")]

        # The autouse fixture binds an in-memory store, so no real event store
        # is needed here.
        try:
            # Run async invoke with timeout to avoid hanging
            results = []
            async with asyncio.timeout(0.5):
                async for msg in async_workflow.invoke(
                    PublishToTopicEvent(
                        invoke_context=invoke_context, data=input_messages
                    )
                ):
                    results.append(msg)
        except asyncio.TimeoutError:
            # Expected - the workflow will wait for output
            pass

    @pytest.mark.asyncio
    async def test_invoke_keeps_runtime_state_out_of_the_definition(
        self, async_workflow: EventDrivenWorkflow
    ) -> None:
        """Each invocation keeps its events in its own run: the definition's
        topics stay empty, and no run stays registered."""
        from tests_integration.async_execution.support import input_event

        async with asyncio.timeout(5):
            for content in ("a", "b"):
                outputs = [o async for o in async_workflow.invoke(input_event(content))]
                assert [o.data[0].content for o in outputs] == ["mock response"]
        for topic in async_workflow.topics.values():
            assert not await topic.can_consume("test_node")
        assert not async_workflow._active_runs

    @pytest.mark.asyncio
    async def test_nodes_changed_after_the_build_are_wired_as_a_run_starts(
        self, async_workflow: EventDrivenWorkflow
    ) -> None:
        """A node added, removed, replaced or given another tool runs wired."""
        from tests_integration.async_execution.support import input_event

        async def answers() -> List[str]:
            outputs = [o async for o in async_workflow.invoke(input_event("a"))]
            return sorted(o.data[0].content for o in outputs)

        nodes = async_workflow.nodes
        node = nodes["test_node"]
        nodes["extra"] = node.model_copy(update={"name": "extra", "tool": Other()})
        assert await answers() == ["mock response", "other response"]
        del nodes["extra"]
        assert await answers() == ["mock response"]
        nodes["test_node"] = node.model_copy(update={"tool": Other()})
        assert await answers() == ["other response"]
        nodes["test_node"].tool = MockTool()
        assert await answers() == ["mock response"]

    @pytest.mark.asyncio
    async def test_a_deep_copy_runs_on_its_own_nodes(
        self, async_workflow: EventDrivenWorkflow
    ) -> None:
        from tests_integration.async_execution.support import input_event

        copied = async_workflow.model_copy(deep=True)

        assert copied.nodes["test_node"] is not async_workflow.nodes["test_node"]
        outputs = [o async for o in copied.invoke(input_event("a"))]
        assert [o.data[0].content for o in outputs] == ["mock response"]

    @pytest.mark.asyncio
    async def test_a_copy_made_during_a_run_has_no_runs(
        self, async_workflow: EventDrivenWorkflow
    ) -> None:
        from tests_integration.async_execution.support import input_event

        outputs = async_workflow.invoke(input_event("a"))
        async with asyncio.timeout(5):
            first = await anext(outputs)
            deep, shallow = async_workflow.model_copy(deep=True), copy.copy(
                async_workflow
            )
            assert not deep._active_runs and not shallow._active_runs
            assert [first, *[o async for o in outputs]][0].data[0].content == (
                "mock response"
            )

    @pytest.mark.asyncio
    async def test_an_llm_shared_by_two_workflows_is_offered_each_ones_functions(
        self,
    ) -> None:
        """A workflow wires its nodes in its own steps, so a tool it shares
        with another holds none of it."""
        llm = _NamesItsFunctions()
        weather, plain = _llm_workflow(llm, get_weather), _llm_workflow(llm)

        assert await _answer(weather) == "get_weather"
        assert await _answer(plain) == "none"
        assert await _answer(weather) == "get_weather"
        assert llm.get_function_specs() == []  # Outside a step: its own only.

    @pytest.mark.asyncio
    async def test_another_llm_run_in_a_step_is_offered_only_its_own(self) -> None:
        """A step's wiring is its node's tool's: an LLM that tool calls, such
        as a summarizer, is not offered the node's functions."""
        assert await _answer(_llm_workflow(_AsksAnother(), get_weather)) == (
            "get_weather|none"
        )

    @pytest.mark.asyncio
    async def test_an_llm_handing_its_call_to_another_passes_its_functions_on(
        self,
    ) -> None:
        class Delegates(_NamesItsFunctions):
            primary: _NamesItsFunctions = _NamesItsFunctions()

            async def invoke(self, invoke_context, input_data):
                inner = self.primary.model_copy(
                    update={"function_specs": self.get_function_specs()}
                )
                return await inner.invoke(invoke_context, input_data)

        assert await _answer(_llm_workflow(Delegates(), get_weather)) == "get_weather"

    @pytest.mark.asyncio
    async def test_a_copy_of_the_nodes_llm_is_offered_its_functions(self) -> None:
        """As one made to change a setting for one call."""

        class TunesACopy(_NamesItsFunctions):
            async def invoke(self, invoke_context, input_data):
                tuned = self.model_copy(update={"chat_params": {"temperature": 0}})
                return [Message(role="assistant", content=tuned.names())]

        assert await _answer(_llm_workflow(TunesACopy(), get_weather)) == "get_weather"

    @pytest.mark.asyncio
    async def test_a_run_inside_a_step_wires_its_own_nodes(self) -> None:
        """As an agent called from a step: its LLM is offered its own
        workflow's functions, not the calling node's."""
        inner = _llm_workflow(_NamesItsFunctions())

        class Outer(_NamesItsFunctions):
            async def invoke(self, invoke_context, input_data):
                answer = f"{self.names()}|{await _answer(inner)}"
                return [Message(role="assistant", content=answer)]

        assert await _answer(_llm_workflow(Outer(), get_weather)) == "get_weather|none"

    @pytest.mark.asyncio
    async def test_a_run_in_flight_keeps_the_nodes_it_started_with(self) -> None:
        from tests_integration.async_execution.support import input_event

        started, release = asyncio.Event(), asyncio.Event()

        class Waits(MockTool):
            async def invoke(self, invoke_context, input_data):
                started.set()
                await release.wait()
                return await super().invoke(invoke_context, input_data)

        mid = Topic(name="mid")
        workflow = (
            EventDrivenWorkflow.builder()
            .node(
                Node.builder()
                .name("a")
                .subscribe(InputTopic(name="in"))
                .tool(Waits())
                .publish_to(mid)
                .build()
            )
            .node(
                Node.builder()
                .name("b")
                .subscribe(mid)
                .tool(MockTool())
                .publish_to(OutputTopic(name="out"))
                .build()
            )
            .build()
        )
        async with asyncio.timeout(5):
            outputs = workflow.invoke(input_event("x"))
            first = asyncio.ensure_future(anext(outputs))
            await started.wait()
            b = workflow.nodes["b"]
            workflow.nodes["b"] = b.model_copy(update={"tool": Other()})
            release.set()

            assert (await first).data[0].content == "mock response"
            assert [o async for o in outputs] == []
            [after] = [o async for o in workflow.invoke(input_event("y"))]
        assert after.data[0].content == "other response"

    @pytest.mark.asyncio
    async def test_a_node_copied_with_other_subscriptions_is_refused(
        self, async_workflow: EventDrivenWorkflow
    ) -> None:
        from tests_integration.async_execution.support import input_event

        node = async_workflow.nodes["test_node"]
        other = [TopicExpr(topic=InputTopic(name="other_input"))]
        async_workflow.nodes["test_node"] = node.model_copy(
            update={"subscribed_expressions": other}
        )

        with pytest.raises(WorkflowError, match="build a new node"):
            async for _ in async_workflow.invoke(input_event("a")):
                pass

    @pytest.mark.asyncio
    async def test_a_stop_while_a_run_is_made_stops_it(
        self, async_workflow: EventDrivenWorkflow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests_integration.async_execution.support import input_event

        wire = async_workflow._wire

        def wire_and_stop() -> Any:
            wired = wire()
            async_workflow.stop()  # As from another thread, while it wires.
            return wired

        monkeypatch.setattr(async_workflow, "_wire", wire_and_stop)
        outputs = [o async for o in async_workflow.invoke(input_event("a"))]

        assert outputs == []

    @pytest.mark.asyncio
    async def test_a_refused_change_once_undone_runs(
        self, async_workflow: EventDrivenWorkflow
    ) -> None:
        from tests_integration.async_execution.support import input_event

        node = async_workflow.nodes.pop("test_node")
        with pytest.raises(WorkflowError, match="agent_input_topic"):
            async for _ in async_workflow.invoke(input_event("a")):
                pass
        async_workflow.nodes["test_node"] = node

        outputs = [o async for o in async_workflow.invoke(input_event("a"))]
        assert [o.data[0].content for o in outputs] == ["mock response"]


def test_a_recorded_invoke_override_is_refused() -> None:
    """An EventDrivenWorkflow records each run itself: decorating its invoke
    would record each twice."""
    with pytest.raises(TypeError, match="leave it undecorated"):

        class Recorded(EventDrivenWorkflow):
            @record_workflow_invoke
            async def invoke(  # type: ignore[override]
                self,
                input_data: Any,
                is_sequential: bool = False,
                *,
                stream: bool = False,
            ) -> Any:
                async for output in super().invoke(input_data, is_sequential):
                    yield output


def _llm_workflow(llm: LLM, *functions: Any) -> EventDrivenWorkflow:
    """``llm`` answering the input, calling ``functions``, each answered by a
    function-call node of its own."""
    calls = Topic(name="calls")
    builder = EventDrivenWorkflow.builder().node(
        Node.builder()
        .name("llm")
        .subscribe(InputTopic(name="agent_input"))
        .tool(llm)
        .publish_to(calls, when=has_tool_call)
        .publish_to(OutputTopic(name="agent_output"), when=has_text_response)
        .build()
    )
    for function in functions:
        builder = builder.node(
            Node.builder()
            .name(function.__name__)
            .subscribe(calls)
            .tool(FunctionCallTool.builder().function(function).build())
            .publish_to(Topic(name="results"))
            .build()
        )
    return builder.build()


async def _answer(workflow: EventDrivenWorkflow) -> str:
    from tests_integration.async_execution.support import input_event

    [output] = [o async for o in workflow.invoke(input_event("a"))]
    return output.data[0].content


class TestEventDrivenWorkflowDump:
    def test_dump_includes_topics(self):
        """A workflow saves its topics, which its nodes name."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        workflow = EventDrivenWorkflow(nodes={"test_node": node})

        result = workflow.model_dump(mode="json")

        assert result["class"] == (
            "grafi.workflows.impl.event_driven_workflow:EventDrivenWorkflow"
        )
        assert result["workflow_id"] == workflow.workflow_id
        assert result["topics"] == {
            "test_input": input_topic.model_dump(mode="json"),
            "test_output": output_topic.model_dump(mode="json"),
        }
        assert result["topics"]["test_input"]["class"] == (
            "grafi.topics.topic_impl.input_topic:InputTopic"
        )
        assert result["nodes"] == {"test_node": node.model_dump(mode="json")}
        # Nodes name their topics.
        node_data = result["nodes"]["test_node"]
        assert node_data["subscribed_expressions"] == [{"topic": "test_input"}]
        assert node_data["publisher_router"]["routes"][0]["topic"] == "test_output"


class TestEventDrivenWorkflowStopFlag:
    @pytest.fixture
    def stoppable_workflow(self):
        """Create a workflow to test stop functionality."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
        )

        return EventDrivenWorkflow(nodes={"test_node": node})

    def test_stop_sets_flag(self, stoppable_workflow):
        """Test that stop() sets the stop flag."""
        assert not stoppable_workflow._stop_requested
        stoppable_workflow.stop()
        assert stoppable_workflow._stop_requested

    def test_reset_stop_flag(self, stoppable_workflow):
        """Test that reset_stop_flag() clears the flag."""
        stoppable_workflow.stop()
        assert stoppable_workflow._stop_requested
        stoppable_workflow.reset_stop_flag()
        assert not stoppable_workflow._stop_requested


class TestEventDrivenWorkflowSerialization:
    @pytest.fixture
    def original(self) -> EventDrivenWorkflow:
        """A ReAct-shaped workflow: an LLM node whose calls a function-call node
        answers."""
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        function_call = Topic(name="function_call")
        function_result = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("llm_node")
            .tool(OpenAITool.builder().name("llm").model("gpt-4o-mini").build())
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result)
                .build()
            )
            .publish_to(function_call, when=has_tool_call)
            .publish_to(agent_output, when=has_text_response)
            .build()
        )
        function_node = (
            Node.builder()
            .name("function_node")
            .tool(
                FunctionCallTool.builder().name("weather").function(get_weather).build()
            )
            .subscribe(function_call)
            .publish_to(function_result)
            .build()
        )
        mock_node = (
            Node.builder()
            .name("mock_node")
            .tool(MockTool(name="mock"))
            .subscribe(agent_input)
            .publish_to(agent_output)
            .build()
        )
        return (
            EventDrivenWorkflow.builder()
            .name("serializable_workflow")
            .node(llm_node)
            .node(function_node)
            .node(mock_node)
            .build()
        )

    @pytest.mark.parametrize("loader", [Workflow, EventDrivenWorkflow])
    def test_round_trip(self, original: EventDrivenWorkflow, loader):
        """Test serialization and deserialization roundtrip."""
        data = original.model_dump(mode="json")
        assert set(data["topics"]) == {
            "agent_input",
            "agent_output",
            "function_call",
            "function_result",
        }

        restored = loader.model_validate(data)

        # Verify structure matches
        assert type(restored) is EventDrivenWorkflow
        assert restored.workflow_id == original.workflow_id
        assert restored.name == "serializable_workflow"
        assert restored.type == original.type
        assert restored.oi_span_type == original.oi_span_type
        assert list(restored.nodes) == list(original.nodes)

        # Verify topics: same names and classes, new instances
        assert set(restored.topics) == set(original.topics)
        for name, topic in original.topics.items():
            assert type(restored.topics[name]) is type(topic)
            assert restored.topics[name].type == topic.type
            assert restored.topics[name] is not topic
        assert restored._wire().readers == original._wire().readers

        # Verify nodes: ids and tool classes kept
        for name, node in original.nodes.items():
            assert restored.nodes[name].node_id == node.node_id
            assert type(restored.nodes[name].tool) is type(node.tool)
            assert restored.nodes[name].tool.tool_id == node.tool.tool_id

        # Saving it again gives the same data
        assert restored.model_dump(mode="json") == data

    def test_nodes_share_the_workflows_topics(self, original: EventDrivenWorkflow):
        """Every node naming a topic refers to the one topic instance."""
        restored = Workflow.model_validate(original.model_dump(mode="json"))
        topics = restored.topics
        llm_node = restored.nodes["llm_node"]
        function_node = restored.nodes["function_node"]
        mock_node = restored.nodes["mock_node"]

        assert llm_node.publish_to == [topics["function_call"], topics["agent_output"]]
        assert llm_node.publish_to[0] is topics["function_call"]
        assert function_node.subscribed_topics[0] is topics["function_call"]
        assert function_node.publish_to[0] is topics["function_result"]
        assert llm_node._subscribed_topics["function_result"] is (
            topics["function_result"]
        )
        assert llm_node._subscribed_topics["agent_input"] is (
            mock_node._subscribed_topics["agent_input"]
        )
        assert mock_node.publish_to[0] is topics["agent_output"]
        assert llm_node.publisher_router.routes[0].when is has_tool_call
        assert llm_node.publisher_router.routes[1].when is has_text_response

    def test_a_loaded_workflow_wires_its_function_calls(
        self, original: EventDrivenWorkflow
    ):
        """The LLM is offered the function-call node's functions after a load,
        which its manifest does not hold."""
        assert offered_to(original, "llm_node") == ["get_weather"]
        data = original.model_dump(mode="json")
        assert "function_specs" not in data["nodes"]["llm_node"]["tool"]
        function_tool_data = data["nodes"]["function_node"]["tool"]
        assert function_tool_data["functions"] == {
            "get_weather": {"ref": f"{__name__}:get_weather"}
        }

        restored = Workflow.model_validate(data)

        llm = restored.nodes["llm_node"].tool
        function_tool = restored.nodes["function_node"].tool
        assert isinstance(llm, OpenAITool)
        assert isinstance(function_tool, FunctionCallTool)
        assert function_tool.functions["get_weather"] is get_weather
        assert offered_to(restored, "llm_node") == ["get_weather"]
        assert answered_by(restored, "function_node") == {
            "function_call": frozenset({"get_weather"})
        }

    def test_a_function_call_node_given_another_tool_offers_its_functions(
        self, original: EventDrivenWorkflow
    ):
        """The workflow is wired again as each run starts, or is asked."""
        original.nodes["function_node"].tool = (
            FunctionCallTool.builder().name("time").function(get_time).build()
        )

        assert offered_to(original, "llm_node") == ["get_time"]
        assert answered_by(original, "function_node") == {
            "function_call": frozenset({"get_time"})
        }

    def test_specs_given_to_an_llm_are_offered_beside_the_wired_ones(
        self, original: EventDrivenWorkflow
    ):
        """And saved with it, as configuration; a function-call node does not
        answer them, the app does."""
        llm = original.nodes["llm_node"].tool
        assert isinstance(llm, OpenAITool)
        llm.add_function_specs([get_time._function_spec])  # type: ignore[attr-defined]

        assert offered_to(original, "llm_node") == ["get_weather", "get_time"]
        assert [spec.name for spec in llm.get_function_specs()] == ["get_time"]
        assert answered_by(original, "function_node") == {
            "function_call": frozenset({"get_time", "get_weather"})
        }
        data = original.model_dump(mode="json")
        assert [
            s["name"] for s in data["nodes"]["llm_node"]["tool"]["function_specs"]
        ] == ["get_time"]
        restored = Workflow.model_validate(data)
        assert offered_to(restored, "llm_node") == ["get_weather", "get_time"]

    def test_a_given_spec_of_a_wired_function_is_warned_of_as_the_workflow_is_built(
        self, original: EventDrivenWorkflow
    ):
        llm = original.nodes["llm_node"].tool
        assert isinstance(llm, OpenAITool)
        llm.add_function_specs([get_weather._function_spec])  # type: ignore[attr-defined]

        with pytest.warns(UserWarning, match="specs for \\['get_weather'\\]"):
            type(original)(**dict(original))

    def test_a_wired_function_wins_over_a_given_spec_of_its_name(
        self, original: EventDrivenWorkflow
    ):
        """The function-call node answers the call, against its function's own
        spec, so that is the one offered."""
        llm = original.nodes["llm_node"].tool
        assert isinstance(llm, OpenAITool)
        stale = get_weather._function_spec.model_copy(  # type: ignore[attr-defined]
            update={"description": "stale"}
        )
        llm.add_function_specs([stale])

        with pytest.warns(UserWarning, match="specs for \\['get_weather'\\]"):
            [spec] = original.offered_to("llm_node")
        assert spec.description != "stale"
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # Where the specs are set, not at runs.
            original._wire()

    def test_a_node_naming_an_unknown_topic_fails(self, original: EventDrivenWorkflow):
        data = original.model_dump(mode="json")
        del data["topics"]["function_result"]

        with pytest.raises(ValidationError, match="Unknown topic 'function_result'"):
            Workflow.model_validate(data)

    def test_a_topic_keyed_by_another_name_fails(self, original: EventDrivenWorkflow):
        data = original.model_dump(mode="json")
        data["topics"]["function_result"]["name"] = "renamed"

        with pytest.raises(ManifestError, match="'renamed' is keyed as"):
            Workflow.model_validate(data)

    def test_workflow_manifest_round_trip(self, original: EventDrivenWorkflow):
        manifest = original.to_manifest()

        assert manifest["apiVersion"] == "grafi/v2"
        assert manifest["kind"] == "Workflow"
        assert manifest["spec"] == original.model_dump(mode="json")

        restored = Workflow.from_manifest(manifest)

        assert type(restored) is EventDrivenWorkflow
        assert restored.workflow_id == original.workflow_id
        assert restored.to_manifest() == manifest

    def test_workflow_manifest_of_another_kind_fails(
        self, original: EventDrivenWorkflow
    ):
        manifest = {**original.to_manifest(), "kind": "Assistant"}

        with pytest.raises(
            ManifestError,
            match="The manifest's kind is 'Assistant', but its spec is of kind "
            "'Workflow'.",
        ):
            Workflow.from_manifest(manifest)

    def test_python_dump_round_trips(self, original: EventDrivenWorkflow):
        """A python-mode dump holds values -- classes, functions, topics in
        full -- and loads back in this process, its nodes sharing its topics."""
        data = original.model_dump()

        assert data["class"] is EventDrivenWorkflow
        assert data["topics"]["agent_input"]["class"] is InputTopic
        function_tool = data["nodes"]["function_node"]["tool"]
        assert function_tool["class"] is FunctionCallTool
        assert function_tool["functions"] == {"get_weather": get_weather}
        routes = data["nodes"]["llm_node"]["publisher_router"]["routes"]
        assert routes[0]["topic"]["name"] == "function_call"
        assert routes[0]["when"] is has_tool_call

        restored = Workflow.model_validate(data)

        assert type(restored) is EventDrivenWorkflow
        assert restored.workflow_id == original.workflow_id
        topics = restored.topics
        assert set(topics) == set(original.topics)
        llm_node = restored.nodes["llm_node"]
        assert llm_node.publish_to[0] is topics["function_call"]
        assert restored.nodes["function_node"].subscribed_topics[0] is (
            topics["function_call"]
        )
        assert restored.nodes["mock_node"].subscribed_topics[0] is (
            topics["agent_input"]
        )
        assert offered_to(restored, "llm_node") == ["get_weather"]
        assert restored.model_dump() == data
        assert restored.model_dump(mode="json") == original.model_dump(mode="json")

    def test_constructing_from_a_json_dump_without_its_class(
        self, original: EventDrivenWorkflow
    ):
        """The topics a dump holds resolve its nodes' topic names when the
        workflow is constructed from it too."""
        data = original.model_dump(mode="json")
        del data["class"]

        restored = EventDrivenWorkflow(**data)

        assert restored.workflow_id == original.workflow_id
        topics = restored.topics
        assert restored.nodes["llm_node"].publish_to[0] is topics["function_call"]
        assert restored.model_dump(mode="json") == original.model_dump(mode="json")

    def test_constructing_from_a_dump_of_another_class_fails(
        self, original: EventDrivenWorkflow
    ):
        data = {**original.model_dump(mode="json"), "class": "grafi.nodes.node:Node"}

        with pytest.raises(ManifestError, match="load it with"):
            EventDrivenWorkflow(**data)

    def test_topics_are_a_copy_left_out_of_the_repr(
        self, original: EventDrivenWorkflow
    ):
        topics = original.topics
        topics.clear()

        assert set(original.topics) == {
            "agent_input",
            "agent_output",
            "function_call",
            "function_result",
        }
        assert "topics=" not in repr(original)


def test_a_topic_named_twice_in_a_subscription_lists_its_reader_once() -> None:
    from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
    from grafi.topics.topic_impl.topic import Topic

    a, b = InputTopic(name="a"), Topic(name="b")
    subscription = (
        SubscriptionBuilder()
        .subscribed_to(a)
        .or_()
        .subscribed_to(a)
        .and_()
        .subscribed_to(b)
        .build()
    )
    node = Node(
        name="n",
        tool=MockTool(),
        subscribed_expressions=[subscription],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=OutputTopic(name="out"))]
        ),
    )
    workflow = EventDrivenWorkflow(nodes={"n": node})
    assert workflow._wire().readers["a"] == ["n"]


def test_a_topic_with_a_custom_event_queue_is_rejected() -> None:
    from grafi.common.exceptions import WorkflowError
    from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue

    class CustomQueue(InMemTopicEventQueue):
        pass

    node = Node(
        name="n",
        tool=MockTool(),
        subscribed_expressions=[TopicExpr(topic=InputTopic(name="input"))],
        publisher_router=PublisherRouter(
            routes=[
                PublishRoute(topic=OutputTopic(name="out", event_queue=CustomQueue()))
            ]
        ),
    )
    with pytest.raises(WorkflowError, match="custom event_queue"):
        EventDrivenWorkflow(nodes={"n": node})


def test_a_node_keyed_by_another_name_is_rejected() -> None:
    # Regression: a run identifies nodes by name, so a node registered under
    # another key would be re-queued forever.
    from grafi.common.exceptions import WorkflowError

    node = Node(
        name="p",
        tool=MockTool(),
        subscribed_expressions=[TopicExpr(topic=InputTopic(name="input"))],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=OutputTopic(name="out"))]
        ),
    )
    with pytest.raises(WorkflowError, match="registered under the key 'key'"):
        EventDrivenWorkflow(nodes={"key": node})


@llm_function
def get_token(user: str) -> str:
    """Look up a user's session token id."""
    return user


def _named_workflow(
    node_name: str, topic_name: str, function: Any = get_token
) -> EventDrivenWorkflow:
    return (
        EventDrivenWorkflow.builder()
        .node(
            Node.builder()
            .name(node_name)
            .subscribe(InputTopic(name="agent_input_topic"))
            .tool(FunctionCallTool.builder().function(function).build())
            .publish_to(Topic(name=topic_name))
            .build()
        )
        .node(
            Node.builder()
            .name("Answer")
            .subscribe(Topic(name=topic_name))
            .tool(MockTool())
            .publish_to(OutputTopic(name="agent_output_topic"))
            .build()
        )
        .build()
    )


@pytest.mark.parametrize(
    "node_name, topic_name",
    [("RefreshToken", "results"), ("Lookup", "session_token")],
)
def test_names_you_choose_are_never_taken_for_secrets(
    node_name: str, topic_name: str
) -> None:
    """A node, topic or function named like a secret holds none: the names
    key what a workflow saves, and each component checks its own values."""
    workflow = _named_workflow(node_name, topic_name)

    manifest = workflow.to_manifest()

    assert "get_token" in manifest["spec"]["nodes"][node_name]["tool"]["functions"]
    loaded = EventDrivenWorkflow.from_manifest(manifest)
    assert set(loaded.nodes) == {node_name, "Answer"}
    assert topic_name in loaded.topics


class Pipeline(Workflow):
    """A workflow of another kind, which runs nothing itself."""


def test_any_workflow_saves_and_loads_its_topics() -> None:
    nodes = _named_workflow("Lookup", "results", function=get_weather).nodes
    workflow = Pipeline(nodes=nodes)

    manifest = workflow.to_manifest()

    assert set(manifest["spec"]["topics"]) == {
        "agent_input_topic",
        "results",
        "agent_output_topic",
    }
    loaded = Workflow.from_manifest(manifest)
    assert type(loaded) is Pipeline
    assert loaded.to_manifest() == manifest
    for node in loaded.nodes.values():
        for topic in [*node.subscribed_topics, *node.publish_to]:
            assert topic is loaded.topics[topic.name]
