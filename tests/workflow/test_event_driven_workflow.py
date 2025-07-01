import asyncio
from collections import deque
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_async_event import OutputAsyncEvent
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions.duplicate_node_error import DuplicateNodeError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.output_topic import OutputTopic
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_expression import TopicExpr
from grafi.nodes.node import Node
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.workflow import WorkflowBuilder


class TestEventDrivenWorkflow:
    @pytest.fixture
    def sample_invoke_context(self):
        return InvokeContext(
            user_id="test_user",
            conversation_id="test_conversation",
            invoke_id="test_invoke",
            assistant_request_id="assistant_request_123",
        )

    @pytest.fixture
    def sample_messages(self):
        return [
            Message(content="Hello", role="user"),
            Message(content="Hi there!", role="assistant"),
        ]

    @pytest.fixture
    def mock_topic(self):
        topic = Mock(spec=Topic)
        topic.name = "agent_input_topic"
        topic.publish_event_handler = None
        topic.publish_data.return_value = Mock()
        topic.can_consume.return_value = True
        topic.consume.return_value = []
        topic.reset = Mock()
        topic.restore_topic = Mock()
        topic.to_dict.return_value = {"name": "agent_input_topic"}
        return topic

    @pytest.fixture
    def mock_node(self, mock_topic):
        """Create a mock OpenAI node that subscribes to agent_input_topic and publishes to agent_output_topic."""
        mock_node = Mock(spec=Node)
        mock_node.name = "OpenAINode"
        mock_node.type = "Node"
        mock_node.node_id = "openai_node_123"
        mock_node.oi_span_type = OpenInferenceSpanKindValues.CHAIN
        mock_node.tool = None  # Add required tool attribute

        # Set up subscription and publishing
        mock_node.subscribed_expressions = [TopicExpr(topic=mock_topic)]
        mock_node._subscribed_topics = {"agent_input_topic": mock_topic}
        mock_node.publish_to = [agent_output_topic]

        # Mock the invoke methods
        mock_node.invoke.return_value = [
            Message(content="Mock response", role="assistant")
        ]

        async def mock_a_invoke(*args, **kwargs):
            yield [Message(content="Mock async response", role="assistant")]

        mock_node.a_invoke.return_value = mock_a_invoke()

        # Mock other required methods
        mock_node.can_invoke.return_value = True
        mock_node.to_dict.return_value = {
            "node_id": "openai_node_123",
            "name": "OpenAINode",
            "type": "Node",
            "subscribed_expressions": [],
            "publish_to": [],
            "command": None,
        }
        return mock_node

    @pytest.fixture
    def event_driven_workflow(self):
        return EventDrivenWorkflow()

    @pytest.fixture
    def populated_workflow(self, mock_node, mock_topic):
        # Patch model_post_init to prevent automatic setup during fixture creation
        with patch.object(EventDrivenWorkflow, "model_post_init"):
            workflow = EventDrivenWorkflow.builder().node(mock_node).build()
            workflow._invoke_queue = deque()
            workflow._topics = {}
            workflow._topic_nodes = {}
        return workflow

    def test_event_driven_workflow_creation(self):
        """Test creating an EventDrivenWorkflow with default values."""
        # Patch model_post_init to prevent validation issues during basic creation test
        with patch.object(EventDrivenWorkflow, "model_post_init"):
            workflow = EventDrivenWorkflow()

            assert workflow.name == "EventDrivenWorkflow"
            assert workflow.type == "EventDrivenWorkflow"
            assert workflow.nodes == {}

    def test_builder_pattern(self, mock_node):
        """Test using the builder pattern to create EventDrivenWorkflow."""
        builder = EventDrivenWorkflow.builder()
        assert isinstance(builder, WorkflowBuilder)

        with patch.object(EventDrivenWorkflow, "model_post_init"):
            workflow = builder.node(mock_node).build()
            assert isinstance(workflow, EventDrivenWorkflow)

    def test_builder_add_node(self, mock_node):
        """Test adding a node via builder."""
        with patch.object(EventDrivenWorkflow, "model_post_init"):
            workflow = EventDrivenWorkflow.builder().node(mock_node).build()

            assert "OpenAINode" in workflow.nodes
            assert workflow.nodes["OpenAINode"] == mock_node

    def test_builder_add_duplicate_node_raises_error(self, mock_node):
        """Test that adding duplicate node raises DuplicateNodeError."""
        builder = EventDrivenWorkflow.builder().node(mock_node)

        with pytest.raises(DuplicateNodeError):
            builder.node(mock_node)

    def test_add_topics(self, mock_node, mock_topic):
        """Test _add_topics method."""
        # Mock extract_topics to return our mock topic
        with patch(
            "grafi.workflows.impl.event_driven_workflow.extract_topics",
            return_value=[mock_topic],
        ), patch.object(EventDrivenWorkflow, "model_post_init"):
            workflow = EventDrivenWorkflow()
            workflow.nodes = {"OpenAINode": mock_node}
            workflow._topics = {}
            workflow._topic_nodes = {}
            workflow._invoke_queue = deque()

            workflow._add_topics()

            assert "agent_input_topic" in workflow._topics
            assert "agent_output_topic" in workflow._topics
            assert "OpenAINode" in workflow._topic_nodes["agent_input_topic"]

    def test_add_topics_missing_agent_topics_raises_error(self, mock_node):
        """Test that missing agent input topics raises ValueError."""
        mock_topic = Mock()
        mock_topic.name = "other_topic"

        with patch(
            "grafi.workflows.impl.event_driven_workflow.extract_topics",
            return_value=[mock_topic],
        ), patch.object(EventDrivenWorkflow, "model_post_init"):
            workflow = EventDrivenWorkflow()
            workflow._topics = {}
            workflow._topic_nodes = {}
            workflow._invoke_queue = deque()
            workflow.nodes = {}

            with pytest.raises(ValueError, match="Agent input topic not found"):
                workflow._add_topics()

    def test_add_topic(self, mock_topic):
        """Test _add_topic method."""
        with patch.object(EventDrivenWorkflow, "model_post_init"):
            workflow = EventDrivenWorkflow()
            workflow._topics = {}
            workflow._topic_nodes = {}
            workflow._invoke_queue = deque()
            workflow._add_topic(mock_topic)

            assert "agent_input_topic" in workflow._topics
            assert workflow._topics["agent_input_topic"] == mock_topic
            assert mock_topic.publish_event_handler == workflow.on_event

    def test_add_topic_duplicate_ignored(self, mock_topic):
        """Test that adding the same topic twice is ignored."""
        with patch.object(EventDrivenWorkflow, "model_post_init"):
            workflow = EventDrivenWorkflow()
            workflow._topics = {}
            workflow._topic_nodes = {}
            workflow._invoke_queue = deque()
            workflow._add_topic(mock_topic)
            original_handler = mock_topic.publish_event_handler

            workflow._add_topic(mock_topic)

            assert len(workflow._topics) == 1
            assert mock_topic.publish_event_handler == original_handler

    def test_handle_function_calling_nodes(self):
        """Test _handle_function_calling_nodes method."""
        from grafi.tools.function_calls.function_call_tool import FunctionCallTool
        from grafi.tools.llms.llm import LLM

        # Create mock LLM node
        llm_node = Mock(spec=Node)
        llm_tool = Mock(spec=LLM)
        llm_node.tool = llm_tool
        llm_node.publish_to = [Topic(name="shared_topic")]
        llm_tool.add_function_specs = Mock()

        # Create mock function call node
        function_node = Mock(spec=Node)
        function_tool = Mock(spec=FunctionCallTool)
        function_node.tool = function_tool
        function_node._subscribed_topics = {"shared_topic": Mock()}
        function_tool.get_function_specs.return_value = {"test_function": {}}

        with patch.object(EventDrivenWorkflow, "model_post_init"):
            workflow = EventDrivenWorkflow()
            workflow._topics = {}
            workflow._topic_nodes = {}
            workflow._invoke_queue = deque()
            workflow.nodes = {
                "llm_node": llm_node,
                "function_node": function_node,
            }

            workflow._handle_function_calling_nodes()

            llm_tool.add_function_specs.assert_called_once_with({"test_function": {}})

    def test_publish_events(
        self, populated_workflow, sample_invoke_context, sample_messages
    ):
        """Test _publish_events method."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        mock_topic = Mock()
        mock_event = Mock()
        mock_topic.publish_data.return_value = mock_event
        mock_node.publish_to = [mock_topic]

        consumed_events = []

        with patch(
            "grafi.common.containers.container.container.event_store.record_events"
        ) as mock_record:
            populated_workflow._publish_events(
                mock_node, sample_invoke_context, sample_messages, consumed_events
            )

            mock_topic.publish_data.assert_called_once()
            mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_agen_events_with_output_topic(
        self, populated_workflow, sample_invoke_context
    ):
        """Test _publish_agen_events with OutputTopic."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        output_topic = Mock(spec=OutputTopic)
        output_topic.add_generator = Mock()
        mock_node.publish_to = [output_topic]

        async def mock_generator():
            yield [Message(content="test", role="assistant")]

        consumed_events = []

        with patch(
            "grafi.common.containers.container.container.event_store.record_events"
        ) as mock_record:
            await populated_workflow._publish_agen_events(
                mock_node, sample_invoke_context, mock_generator(), consumed_events
            )

            output_topic.add_generator.assert_called_once()
            mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_agen_events_with_regular_topic(
        self, populated_workflow, sample_invoke_context
    ):
        """Test _publish_agen_events with regular topic."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        regular_topic = Mock()
        regular_topic.publish_data.return_value = Mock()
        mock_node.publish_to = [regular_topic]

        async def mock_generator():
            yield [Message(content="test1", role="assistant")]
            yield [Message(content="test2", role="assistant")]

        consumed_events = []

        with patch(
            "grafi.common.containers.container.container.event_store.record_events"
        ) as mock_record:
            await populated_workflow._publish_agen_events(
                mock_node, sample_invoke_context, mock_generator(), consumed_events
            )

            regular_topic.publish_data.assert_called_once()
            mock_record.assert_called_once()

    def test_get_consumed_events(self, populated_workflow):
        """Test _get_consumed_events method."""
        with patch(
            "grafi.workflows.impl.event_driven_workflow.human_request_topic"
        ) as mock_human_topic, patch(
            "grafi.workflows.impl.event_driven_workflow.agent_output_topic"
        ) as mock_output_topic:
            mock_human_topic.can_consume.return_value = True
            mock_output_topic.can_consume.return_value = True

            mock_output_event = OutputTopicEvent(
                event_id="test_id",
                event_type="PublishToTopic",
                timestamp="2009-02-13T23:31:30+00:00",
                topic_name="test_topic",
                publisher_name="OpenAINode",
                publisher_type="test_type",
                offset=0,
                invoke_context=InvokeContext(
                    conversation_id="conversation_id",
                    invoke_id="invoke_id",
                    assistant_request_id="assistant_request_id",
                ),
                consumed_event_ids=["1", "2"],
                data=[
                    Message(
                        message_id="ea72df51439b42e4a43b217c9bca63f5",
                        timestamp=1737138526189505000,
                        role="user",
                        content="Hello, my name is Grafi, how are you doing?",
                        name=None,
                        functions=None,
                        function_call=None,
                    )
                ],
            )

            mock_human_topic.consume.return_value = [mock_output_event]
            mock_output_topic.consume.return_value = [mock_output_event]

            result = populated_workflow._get_consumed_events()

            assert len(result) == 2
            assert all(isinstance(event, ConsumeFromTopicEvent) for event in result)

    def test_invoke(self, populated_workflow, sample_invoke_context, sample_messages):
        """Test synchronous invoke method."""
        mock_node = populated_workflow.nodes["OpenAINode"]

        with patch.object(
            EventDrivenWorkflow, "initial_workflow"
        ) as mock_initial, patch.object(
            EventDrivenWorkflow, "get_node_input"
        ) as mock_get_input, patch.object(
            EventDrivenWorkflow, "_publish_events"
        ) as mock_publish, patch.object(
            EventDrivenWorkflow, "_get_consumed_events"
        ) as mock_get_consumed:
            # Setup mocks
            mock_consume_event = Mock(spec=ConsumeFromTopicEvent)
            mock_consume_event.data = sample_messages
            mock_consume_event.to_dict = Mock(return_value={"mock_event": "data"})

            mock_get_input.return_value = [mock_consume_event]
            mock_get_consumed.return_value = [mock_consume_event]

            # Mock the node's invoke method to return sample messages
            mock_node.invoke = Mock(return_value=sample_messages)

            # Add node to invoke queue
            populated_workflow._invoke_queue.append(mock_node)

            result = populated_workflow.invoke(sample_invoke_context, sample_messages)

            mock_initial.assert_called_once()
            mock_node.invoke.assert_called_once()
            mock_publish.assert_called_once()
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_process_all_nodes(self, populated_workflow, sample_invoke_context):
        """Test _process_all_nodes method."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        populated_workflow._invoke_queue.append(mock_node)

        with patch.object(EventDrivenWorkflow, "_invoke_node") as mock_invoke, patch(
            "grafi.workflows.impl.event_driven_workflow.agent_output_topic"
        ) as mock_output_topic:
            mock_invoke.return_value = None
            mock_output_topic.wait_for_completion = AsyncMock()

            running_tasks = set()
            executing_nodes = set()

            await populated_workflow._process_all_nodes(
                sample_invoke_context, running_tasks, executing_nodes
            )

            mock_invoke.assert_called_once()
            mock_output_topic.wait_for_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_node(self, populated_workflow, sample_invoke_context):
        """Test _invoke_node method."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        executing_nodes = set()

        with patch.object(
            EventDrivenWorkflow, "get_node_input"
        ) as mock_get_input, patch.object(
            EventDrivenWorkflow, "_publish_agen_events"
        ) as mock_publish:
            mock_get_input.return_value = [Mock(spec=ConsumeFromTopicEvent)]
            mock_publish.return_value = None

            async def mock_a_invoke(*args, **kwargs):
                yield [Message(content="Mock async response", role="assistant")]

            mock_node.a_invoke.return_value = mock_a_invoke()

            await populated_workflow._invoke_node(
                sample_invoke_context, mock_node, executing_nodes
            )

            mock_node.a_invoke.assert_called_once()
            mock_publish.assert_called_once()

    def test_get_node_input(self, populated_workflow):
        """Test get_node_input method."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        mock_topic = Mock()
        mock_event = OutputTopicEvent(
            event_id="test_id",
            event_type="PublishToTopic",
            timestamp="2009-02-13T23:31:30+00:00",
            topic_name="test_topic",
            publisher_name="OpenAINode",
            publisher_type="test_type",
            offset=0,
            invoke_context=InvokeContext(
                conversation_id="conversation_id",
                invoke_id="invoke_id",
                assistant_request_id="assistant_request_id",
            ),
            consumed_event_ids=["1", "2"],
            data=[
                Message(
                    message_id="ea72df51439b42e4a43b217c9bca63f5",
                    timestamp=1737138526189505000,
                    role="user",
                    content="Hello, my name is Grafi, how are you doing?",
                    name=None,
                    functions=None,
                    function_call=None,
                )
            ],
        )

        mock_topic.can_consume.return_value = True
        mock_topic.consume.return_value = [mock_event]
        mock_node._subscribed_topics = {"test_topic": mock_topic}

        result = populated_workflow.get_node_input(mock_node)

        assert len(result) == 1
        assert isinstance(result[0], ConsumeFromTopicEvent)

    def test_on_event_with_output_topic_event(self, populated_workflow):
        """Test on_event method with OutputTopicEvent (should be ignored)."""
        event = OutputTopicEvent(
            event_id="test_id",
            event_type="PublishToTopic",
            timestamp="2009-02-13T23:31:30+00:00",
            topic_name="test_topic",
            publisher_name="OpenAINode",
            publisher_type="test_type",
            offset=0,
            invoke_context=InvokeContext(
                conversation_id="conversation_id",
                invoke_id="invoke_id",
                assistant_request_id="assistant_request_id",
            ),
            consumed_event_ids=["1", "2"],
            data=[
                Message(
                    message_id="ea72df51439b42e4a43b217c9bca63f5",
                    timestamp=1737138526189505000,
                    role="user",
                    content="Hello, my name is Grafi, how are you doing?",
                    name=None,
                    functions=None,
                    function_call=None,
                )
            ],
        )

        initial_queue_length = len(populated_workflow._invoke_queue)
        populated_workflow.on_event(event)

        assert len(populated_workflow._invoke_queue) == initial_queue_length

    def test_on_event_unknown_topic(self, populated_workflow):
        """Test on_event with unknown topic."""
        event = Mock(spec=PublishToTopicEvent)
        event.topic_name = "unknown_topic"

        initial_queue_length = len(populated_workflow._invoke_queue)
        populated_workflow.on_event(event)

        assert len(populated_workflow._invoke_queue) == initial_queue_length

    def test_on_event_valid_publish_event(self, populated_workflow):
        """Test on_event with valid PublishToTopicEvent."""
        # Setup the workflow with topic nodes
        populated_workflow._topic_nodes = {"test_topic": ["OpenAINode"]}

        # Create a valid PublishToTopicEvent
        event = Mock(spec=PublishToTopicEvent)
        event.topic_name = "test_topic"

        # Mock the node's can_invoke method
        mock_node = populated_workflow.nodes["OpenAINode"]
        mock_node.can_invoke.return_value = True

        initial_queue_length = len(populated_workflow._invoke_queue)
        populated_workflow.on_event(event)

        # Node should be added to queue
        assert len(populated_workflow._invoke_queue) == initial_queue_length + 1
        assert populated_workflow._invoke_queue[-1] == mock_node

    def test_initial_workflow_no_existing_events(
        self, populated_workflow, sample_invoke_context, sample_messages
    ):
        """Test initial_workflow with no existing events."""
        with patch(
            "grafi.common.containers.container.container.event_store.get_agent_events"
        ) as mock_get_events, patch(
            "grafi.common.containers.container.container.event_store.record_event"
        ) as mock_record:
            mock_get_events.return_value = []

            # Add agent input topic
            input_topic = Mock()
            input_topic.publish_data.return_value = Mock()
            populated_workflow._topics["agent_input_topic"] = input_topic

            populated_workflow.initial_workflow(sample_invoke_context, sample_messages)

            input_topic.publish_data.assert_called_once()
            mock_record.assert_called_once()

    def test_initial_workflow_with_existing_events(
        self, populated_workflow, sample_invoke_context, sample_messages
    ):
        """Test initial_workflow with existing events."""
        mock_event = Mock(spec=PublishToTopicEvent)
        mock_event.topic_name = "agent_input_topic"

        with patch(
            "grafi.common.containers.container.container.event_store.get_agent_events"
        ) as mock_get_events:
            mock_get_events.return_value = [mock_event]

            # Setup topics
            mock_topic = Mock()
            mock_topic.can_consume.return_value = True
            mock_topic.restore_topic = Mock()
            populated_workflow._topics["agent_input_topic"] = mock_topic
            populated_workflow._topic_nodes["agent_input_topic"] = ["OpenAINode"]

            # Mock the node's can_invoke method
            mock_node = populated_workflow.nodes["OpenAINode"]
            mock_node.can_invoke.return_value = True

            populated_workflow.initial_workflow(sample_invoke_context, sample_messages)

            mock_topic.restore_topic.assert_called_once_with(mock_event)

    def test_to_dict(self, populated_workflow):
        """Test to_dict method."""
        result = populated_workflow.to_dict()

        assert "name" in result
        assert "type" in result
        assert "oi_span_type" in result
        assert "nodes" in result
        assert "topics" in result
        assert "topic_nodes" in result
        assert result["name"] == "EventDrivenWorkflow"
        assert result["type"] == "EventDrivenWorkflow"

    def test_record_consumed_events(self, populated_workflow):
        """Test _record_consumed_events method."""
        events = [
            OutputAsyncEvent(
                topic_name="test_topic",
                publisher_name="OpenAINode",
                publisher_type="test_type",
                offset=0,
                invoke_context=InvokeContext(
                    conversation_id="conversation_id",
                    invoke_id="invoke_id",
                    assistant_request_id="assistant_request_id",
                ),
                data=[
                    Message(
                        message_id="ea72df51439b42e4a43b217c9bca63f5",
                        timestamp=1737138526189505000,
                        role="user",
                        content="Hello, my name is Grafi, how are you doing?",
                        name=None,
                        functions=None,
                        function_call=None,
                        is_streaming=False,
                    )
                ],
            )
        ]

        with patch(
            "grafi.common.containers.container.container.event_store.record_event"
        ) as mock_record:
            populated_workflow._record_consumed_events(events)

            mock_record.assert_called_once()
            recorded_event = mock_record.call_args[0][0]
            assert isinstance(recorded_event, ConsumeFromTopicEvent)

    def test_record_consumed_events_with_streaming(self, populated_workflow):
        """Test _record_consumed_events with streaming messages."""
        events = [
            OutputAsyncEvent(
                topic_name="test_topic",
                publisher_name="OpenAINode",
                publisher_type="test_type",
                offset=0,
                invoke_context=InvokeContext(
                    conversation_id="conversation_id",
                    invoke_id="invoke_id",
                    assistant_request_id="assistant_request_id",
                ),
                data=[
                    Message(
                        message_id="ea72df51439b42e4a43b217c9bca63f5",
                        timestamp=1737138526189505000,
                        role="assistant",
                        content="Hello",
                        is_streaming=True,
                    ),
                    Message(
                        message_id="ea72df51439b42e4a43b217c9bca63f6",
                        timestamp=1737138526189505001,
                        role="assistant",
                        content=" world",
                        is_streaming=True,
                    ),
                ],
            )
        ]

        with patch(
            "grafi.common.containers.container.container.event_store.record_event"
        ) as mock_record:
            populated_workflow._record_consumed_events(events)

            # Should record one consolidated event for streaming messages
            mock_record.assert_called_once()
            recorded_event = mock_record.call_args[0][0]
            assert isinstance(recorded_event, ConsumeFromTopicEvent)
            assert recorded_event.data[0].content == "Hello world"

    def test_record_consumed_events_empty_list(self, populated_workflow):
        """Test _record_consumed_events with empty events list."""
        with patch(
            "grafi.common.containers.container.container.event_store.record_event"
        ) as mock_record:
            populated_workflow._record_consumed_events([])

            mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_invoke_node_no_input(
        self, populated_workflow, sample_invoke_context
    ):
        """Test _invoke_node when no input is available."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        executing_nodes = set()

        with patch.object(EventDrivenWorkflow, "get_node_input") as mock_get_input:
            mock_get_input.return_value = []  # No input available

            await populated_workflow._invoke_node(
                sample_invoke_context, mock_node, executing_nodes
            )

            mock_node.a_invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_invoke_node_with_exception(
        self, populated_workflow, sample_invoke_context
    ):
        """Test _invoke_node when node invoke raises exception."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        mock_node.a_invoke.side_effect = ValueError("Test error")
        executing_nodes = {"OpenAINode"}

        with patch.object(EventDrivenWorkflow, "get_node_input") as mock_get_input:
            mock_get_input.return_value = [Mock(spec=ConsumeFromTopicEvent)]

            with pytest.raises(ValueError, match="Test error"):
                await populated_workflow._invoke_node(
                    sample_invoke_context, mock_node, executing_nodes
                )

            # Node should be removed from executing set even on exception
            assert "OpenAINode" not in executing_nodes

    def test_model_post_init_calls_setup_methods(self, mock_node):
        """Test that model_post_init calls required setup methods."""
        with patch.object(
            EventDrivenWorkflow, "_add_topics"
        ) as mock_add_topics, patch.object(
            EventDrivenWorkflow, "_handle_function_calling_nodes"
        ) as mock_handle_functions:
            # Create workflow with a node - this will trigger model_post_init once
            workflow = EventDrivenWorkflow()
            workflow.nodes = {"test_node": mock_node}

            # Manually trigger model_post_init to test it
            workflow.model_post_init(None)

            # Should be called once for the manual trigger
            mock_add_topics.assert_called()
            mock_handle_functions.assert_called()

    def test_property_access(self, populated_workflow):
        """Test accessing private attributes as properties."""
        # Test that we can access the private attributes
        assert hasattr(populated_workflow, "_topics")
        assert hasattr(populated_workflow, "_topic_nodes")
        assert hasattr(populated_workflow, "_invoke_queue")

        # Test that they are properly initialized
        assert isinstance(populated_workflow._topics, dict)
        assert isinstance(populated_workflow._topic_nodes, dict)
        assert isinstance(populated_workflow._invoke_queue, deque)

    def test_workflow_inheritance(self, populated_workflow):
        """Test that EventDrivenWorkflow properly inherits from Workflow."""
        from grafi.workflows.workflow import Workflow

        assert isinstance(populated_workflow, Workflow)
        assert populated_workflow.oi_span_type == OpenInferenceSpanKindValues.AGENT

    @pytest.mark.asyncio
    async def test_a_invoke_event_streaming(
        self, populated_workflow, sample_invoke_context, sample_messages
    ):
        """Test a_invoke with actual event streaming."""
        with patch.object(
            EventDrivenWorkflow, "initial_workflow"
        ) as mock_initial, patch.object(
            EventDrivenWorkflow, "_process_all_nodes"
        ) as mock_process, patch(
            "grafi.workflows.impl.event_driven_workflow.agent_output_topic"
        ) as mock_output_topic, patch(
            "grafi.workflows.impl.event_driven_workflow.human_request_topic"
        ) as mock_human_topic:
            # Setup mocks for streaming
            mock_human_topic.can_consume.return_value = False

            # Create a mock event queue that yields an event then completes
            mock_event_queue = AsyncMock()
            test_event = OutputAsyncEvent(
                topic_name="test_topic",
                publisher_name="test_publisher",
                publisher_type="test_type",
                offset=0,
                invoke_context=sample_invoke_context,
                data=[Message(content="Test streaming message", role="assistant")],
            )

            # First call returns event, second call hangs until cancelled
            mock_event_queue.get.side_effect = [test_event, asyncio.CancelledError()]
            mock_output_topic.event_queue = mock_event_queue
            mock_output_topic.get_events.return_value = []

            async def empty_generator():
                return
                yield

            mock_output_topic.get_events.return_value = empty_generator()

            # Create a task that completes after yielding the event
            async def mock_process_task(*args):
                await asyncio.sleep(0.01)  # Small delay to allow event processing

            mock_process.side_effect = mock_process_task

            messages = []
            async for message_batch in populated_workflow.a_invoke(
                sample_invoke_context, sample_messages
            ):
                messages.extend(message_batch)
                break  # Only process first batch

            assert len(messages) == 1
            assert messages[0].content == "Test streaming message"
            mock_initial.assert_called_once()

    def test_get_node_input_multiple_topics(self, populated_workflow):
        """Test get_node_input with multiple subscribed topics."""
        mock_node = populated_workflow.nodes["OpenAINode"]

        # Create multiple topics
        topic1 = Mock()
        topic1.can_consume.return_value = True
        topic1.consume.return_value = [
            OutputTopicEvent(
                event_id="test_id_1",
                event_type="PublishToTopic",
                timestamp="2009-02-13T23:31:30+00:00",
                topic_name="topic1",
                publisher_name="TestNode",
                publisher_type="Node",
                offset=0,
                invoke_context=InvokeContext(
                    conversation_id="test_conversation",
                    invoke_id="test_invoke",
                    assistant_request_id="test_request",
                ),
                consumed_event_ids=[],
                data=[Message(content="Message from topic1", role="user")],
            )
        ]

        topic2 = Mock()
        topic2.can_consume.return_value = True
        topic2.consume.return_value = [
            OutputTopicEvent(
                event_id="test_id_2",
                event_type="PublishToTopic",
                timestamp="2009-02-13T23:31:30+00:00",
                topic_name="topic2",
                publisher_name="TestNode",
                publisher_type="Node",
                offset=0,
                invoke_context=InvokeContext(
                    conversation_id="test_conversation",
                    invoke_id="test_invoke",
                    assistant_request_id="test_request",
                ),
                consumed_event_ids=[],
                data=[Message(content="Message from topic2", role="user")],
            )
        ]

        mock_node._subscribed_topics = {"topic1": topic1, "topic2": topic2}

        result = populated_workflow.get_node_input(mock_node)

        assert len(result) == 2
        assert all(isinstance(event, ConsumeFromTopicEvent) for event in result)
        assert result[0].topic_name == "topic1"
        assert result[1].topic_name == "topic2"

    def test_initial_workflow_with_human_request_topic(
        self, populated_workflow, sample_invoke_context, sample_messages
    ):
        """Test initial_workflow with HumanRequestTopic handling."""
        from grafi.common.topics.human_request_topic import HumanRequestTopic

        mock_event = Mock(spec=PublishToTopicEvent)
        mock_event.topic_name = "human_request_topic"

        human_topic = Mock(spec=HumanRequestTopic)
        human_topic.can_consume.return_value = True
        human_topic.can_append_user_input.return_value = True
        human_topic.append_user_input.return_value = Mock()

        with patch(
            "grafi.common.containers.container.container.event_store.get_agent_events"
        ) as mock_get_events, patch(
            "grafi.common.containers.container.container.event_store.record_event"
        ) as mock_record:
            mock_get_events.return_value = [mock_event]

            # Setup workflow
            populated_workflow._topics["human_request_topic"] = human_topic
            populated_workflow._topic_nodes["human_request_topic"] = ["OpenAINode"]

            mock_node = populated_workflow.nodes["OpenAINode"]
            mock_node.can_invoke.return_value = True

            populated_workflow.initial_workflow(sample_invoke_context, sample_messages)

            human_topic.append_user_input.assert_called_once()
            assert (
                len(mock_record.call_args_list) == 1
            )  # Should record the append event
