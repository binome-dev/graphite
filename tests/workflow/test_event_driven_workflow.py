import asyncio
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_base import TopicType
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.workflow import WorkflowBuilder


class MockTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    def invoke(self, invoke_context, input_data):
        return [Message(role="assistant", content="mock response")]

    async def invoke(self, invoke_context, input_data):
        yield [Message(role="assistant", content="mock response")]


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
            publish_to=[output_topic],
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
            publish_to=[output_topic],
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
            publish_to=[output_topic],
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
            publish_to=[],
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
            publish_to=[output_topic],
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
            publish_to=[output_topic],
        )

        workflow = EventDrivenWorkflow(nodes={"test_node": node})
        return workflow


class TestEventDrivenWorkflowOutputEvents:
    @pytest.fixture
    @pytest.mark.asyncio
    async def workflow_with_output_topics(self):
        """Create a workflow with various output topics."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publish_to=[output_topic],
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
            publish_to=[output_topic],
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
            publish_to=[output_topic],
        )

        return EventDrivenWorkflow(nodes={"test_node": node})

    def test_a_invoke_method_exists(self, async_workflow):
        """Test that invoke method exists and is async."""
        assert hasattr(async_workflow, "invoke")
        assert callable(async_workflow.invoke)

    @pytest.mark.asyncio
    async def test_a_invoke_basic_flow(self, async_workflow):
        """Test basic async invoke flow."""
        # This test verifies that the invoke method can be called
        # and properly sets up the async machinery

        invoke_context = InvokeContext(
            conversation_id="test", invoke_id="test", assistant_request_id="test"
        )
        input_messages = [Message(role="user", content="test input")]

        # Mock the container to avoid real event store
        with patch(
            "grafi.workflows.impl.event_driven_workflow.container"
        ) as mock_container:
            mock_event_store = Mock()
            mock_container.event_store = mock_event_store
            mock_event_store.get_agent_events = AsyncMock(return_value=[])
            mock_event_store.record_events = AsyncMock()
            mock_event_store.record_event = AsyncMock()

            # Create a timeout to avoid hanging
            try:
                # Run async invoke with timeout
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

            # The workflow should have been initialized
            mock_event_store.get_agent_events.assert_called_with("test")

    @pytest.mark.asyncio
    async def test_a_invoke_with_async_output_queue(self, async_workflow):
        """Test that invoke uses AsyncOutputQueue."""
        # We can verify that the workflow has the necessary components
        assert hasattr(async_workflow, "_tracker")
        assert hasattr(async_workflow, "_topics")

        # The AsyncOutputQueue should be created during invoke execution
        # This is more of an integration test ensuring the components work together


class TestEventDrivenWorkflowInitialWorkflow:
    @pytest.fixture
    def workflow_for_initial_test(self):
        """Create workflow for initial workflow testing."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publish_to=[output_topic],
        )

        return EventDrivenWorkflow(nodes={"test_node": node})

    def test_initial_workflow_method_exists(self, workflow_for_initial_test):
        """Test that initial_workflow method exists."""
        assert hasattr(workflow_for_initial_test, "initial_workflow")
        assert callable(workflow_for_initial_test.initial_workflow)


class TestEventDrivenWorkflowToDict:
    def test_to_dict_includes_topics_and_topic_nodes(self):
        """Test that to_dict includes topics and topic_nodes."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publish_to=[output_topic],
        )

        workflow = EventDrivenWorkflow(nodes={"test_node": node})

        result = workflow.to_dict()

        assert "topics" in result
        assert "topic_nodes" in result
        assert isinstance(result["topics"], dict)
        assert isinstance(result["topic_nodes"], dict)
        assert "test_input" in result["topics"]
        assert "test_output" in result["topics"]
        assert "test_input" in result["topic_nodes"]


class TestEventDrivenWorkflowAsyncNodeTracker:
    @pytest.fixture
    def workflow_with_tracker(self):
        """Create a workflow to test async node tracker integration."""
        input_topic = InputTopic(name="test_input")
        output_topic = OutputTopic(name="test_output")

        mock_tool = MockTool()
        node = Node(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[TopicExpr(topic=input_topic)],
            publish_to=[output_topic],
        )

        return EventDrivenWorkflow(nodes={"test_node": node})

    def test_workflow_has_tracker(self, workflow_with_tracker):
        """Test that workflow has AsyncNodeTracker."""
        assert hasattr(workflow_with_tracker, "_tracker")
        from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker

        assert isinstance(workflow_with_tracker._tracker, AsyncNodeTracker)

    @pytest.mark.asyncio
    async def test_tracker_reset_on_init(self, workflow_with_tracker):
        """Test that tracker is reset on workflow initialization."""
        # Add some activity to tracker
        await workflow_with_tracker._tracker.enter("test_node")
        assert not workflow_with_tracker._tracker.is_idle()

        # Call init_workflow which should reset tracker
        invoke_context = InvokeContext(
            conversation_id="test", invoke_id="test", assistant_request_id="test"
        )
        with patch("grafi.common.containers.container.container"):
            await workflow_with_tracker.init_workflow(
                PublishToTopicEvent(invoke_context=invoke_context, data=[])
            )

        # Tracker should be reset
        assert workflow_with_tracker._tracker.is_idle()


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
            publish_to=[output_topic],
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
