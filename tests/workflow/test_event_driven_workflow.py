import asyncio

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ValidationError

from grafi.common.decorators.llm_function import llm_function
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
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
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


class MockTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context, input_data):
        yield [Message(role="assistant", content="mock response")]


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

        assert "test_input" in workflow._topics
        assert "test_output" in workflow._topics
        assert "test_input" in workflow._topic_nodes
        assert workflow._topic_nodes["test_input"] == ["test_node"]

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
        await workflow._topics["test_output"].add_event(mock_event)

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
        for topic in async_workflow._topics.values():
            assert not await topic.can_consume("test_node")
        assert not async_workflow._active_runs


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
        assert set(restored._topics) == set(original._topics)
        for name, topic in original._topics.items():
            assert type(restored._topics[name]) is type(topic)
            assert restored._topics[name].type == topic.type
            assert restored._topics[name] is not topic
        assert restored._topic_nodes == original._topic_nodes

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
        topics = restored._topics
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

    def test_function_specs_are_linked_into_the_llm_again(
        self, original: EventDrivenWorkflow
    ):
        """The LLM is offered the function-call node's functions after a load,
        which its manifest does not hold."""
        assert [
            spec.name for spec in original.nodes["llm_node"].tool.get_function_specs()
        ] == ["get_weather"]
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
        assert llm.get_function_specs() == function_tool.get_function_specs()
        assert [spec.name for spec in llm.get_function_specs()] == ["get_weather"]
        command = restored.nodes["function_node"].command
        assert isinstance(command, FunctionCallCommand)
        assert command.offered == {"function_call": frozenset({"get_weather"})}

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
        assert [spec.name for spec in llm_node.tool.get_function_specs()] == [
            "get_weather"
        ]
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
    assert workflow._topic_nodes["a"] == ["n"]


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
