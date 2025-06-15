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
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.topics.output_topic import OutputTopic
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_expression import TopicExpr
from grafi.nodes.impl.llm_function_call_node import LLMFunctionCallNode
from grafi.nodes.impl.llm_node import LLMNode
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflowBuilder


class TestEventDrivenWorkflow:
    @pytest.fixture
    def sample_execution_context(self):
        return ExecutionContext(
            user_id="test_user",
            conversation_id="test_conversation",
            execution_id="test_execution",
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
        mock_node = Mock(spec=LLMNode)
        mock_node.name = "OpenAINode"
        mock_node.type = "LLMNode"
        mock_node.node_id = "openai_node_123"
        mock_node.oi_span_type = OpenInferenceSpanKindValues.CHAIN

        # Set up subscription and publishing
        mock_node.subscribed_expressions = [TopicExpr(topic=mock_topic)]
        mock_node._subscribed_topics = {"agent_input_topic": mock_topic}
        mock_node.publish_to = [agent_output_topic]

        # Mock the execution methods
        mock_node.execute.return_value = [
            Message(content="Mock response", role="assistant")
        ]

        async def mock_a_execute(*args, **kwargs):
            yield [Message(content="Mock async response", role="assistant")]

        mock_node.a_execute.return_value = mock_a_execute()

        # Mock other required methods
        mock_node.can_execute.return_value = True
        mock_node.get_command_input.return_value = []
        mock_node.to_dict.return_value = {
            "node_id": "openai_node_123",
            "name": "OpenAINode",
            "type": "LLMNode",
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
        workflow = EventDrivenWorkflow.builder().node(mock_node).build()
        return workflow

    def test_event_driven_workflow_creation(self):
        """Test creating an EventDrivenWorkflow with default values."""
        workflow = EventDrivenWorkflow()

        assert workflow.name == "EventDrivenWorkflow"
        assert workflow.type == "EventDrivenWorkflow"
        assert workflow.nodes == {}
        assert workflow.topics == {}
        assert workflow.topic_nodes == {}
        assert isinstance(workflow.execution_queue, deque)

    def test_builder_pattern(self, mock_node):
        """Test using the builder pattern to create EventDrivenWorkflow."""
        builder = EventDrivenWorkflow.builder()
        assert isinstance(builder, EventDrivenWorkflowBuilder)

        workflow = builder.node(mock_node).build()
        assert isinstance(workflow, EventDrivenWorkflow)

    def test_builder_add_node(self, mock_node):
        """Test adding a node via builder."""
        workflow = EventDrivenWorkflow.builder().node(mock_node).build()

        assert "OpenAINode" in workflow.nodes
        assert workflow.nodes["OpenAINode"] == mock_node

    def test_builder_add_duplicate_node_raises_error(self, mock_node):
        """Test that adding duplicate node raises DuplicateNodeError."""
        builder = EventDrivenWorkflow.builder().node(mock_node)

        with pytest.raises(DuplicateNodeError):
            builder.node(mock_node)

    def test_add_topics(self, event_driven_workflow, mock_node, mock_topic):
        """Test _add_topics method."""
        # Mock extract_topics to return our mock topic
        with patch(
            "grafi.workflows.impl.event_driven_workflow.extract_topics",
            return_value=[mock_topic],
        ):
            event_driven_workflow.nodes = {"OpenAINode": mock_node}

            event_driven_workflow._add_topics()

            assert "agent_input_topic" in event_driven_workflow.topics
            assert "agent_output_topic" in event_driven_workflow.topics
            assert (
                "OpenAINode" in event_driven_workflow.topic_nodes["agent_input_topic"]
            )

    def test_add_topics_missing_agent_topics_raises_error(
        self, event_driven_workflow, mock_node
    ):
        """Test that missing agent input/output topics raises ValueError."""
        mock_topic = Mock()
        mock_topic.name = "other_topic"

        with patch(
            "grafi.workflows.impl.event_driven_workflow.extract_topics",
            return_value=[mock_topic],
        ):
            event_driven_workflow.nodes = {}

            with pytest.raises(ValueError, match="Agent input output topic not found"):
                event_driven_workflow._add_topics()

    def test_add_topic(self, event_driven_workflow, mock_topic):
        """Test _add_topic method."""
        event_driven_workflow._add_topic(mock_topic)

        assert "agent_input_topic" in event_driven_workflow.topics
        assert event_driven_workflow.topics["agent_input_topic"] == mock_topic
        assert mock_topic.publish_event_handler == event_driven_workflow.on_event

    def test_add_topic_duplicate_ignored(self, event_driven_workflow, mock_topic):
        """Test that adding the same topic twice is ignored."""
        event_driven_workflow._add_topic(mock_topic)
        original_handler = mock_topic.publish_event_handler

        event_driven_workflow._add_topic(mock_topic)

        assert len(event_driven_workflow.topics) == 1
        assert mock_topic.publish_event_handler == original_handler

    def test_handle_function_calling_nodes(self, event_driven_workflow):
        """Test _handle_function_calling_nodes method."""
        # Create mock LLM node
        llm_node = Mock(spec=LLMNode)
        llm_node.publish_to = [Topic(name="shared_topic")]
        llm_node.add_function_spec = Mock()

        # Create mock function call node
        function_node = Mock(spec=LLMFunctionCallNode)
        function_node._subscribed_topics = ["shared_topic"]
        function_node.get_function_specs.return_value = {"test_function": {}}

        event_driven_workflow.nodes = {
            "llm_node": llm_node,
            "function_node": function_node,
        }

        event_driven_workflow._handle_function_calling_nodes()

        llm_node.add_function_spec.assert_called_once_with({"test_function": {}})

    def test_publish_events(
        self, populated_workflow, sample_execution_context, sample_messages
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
                mock_node, sample_execution_context, sample_messages, consumed_events
            )

            mock_topic.publish_data.assert_called_once()
            mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_agen_events_with_output_topic(
        self, populated_workflow, sample_execution_context
    ):
        """Test _publish_agen_events with OutputTopic."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        output_topic = Mock(spec=OutputTopic)
        mock_node.publish_to = [output_topic]

        async def mock_generator():
            yield [Message(content="test", role="assistant")]

        consumed_events = []

        with patch(
            "grafi.common.containers.container.container.event_store.record_events"
        ) as mock_record:
            await populated_workflow._publish_agen_events(
                mock_node, sample_execution_context, mock_generator(), consumed_events
            )

            output_topic.add_generator.assert_called_once()
            mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_agen_events_with_regular_topic(
        self, populated_workflow, sample_execution_context
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
                mock_node, sample_execution_context, mock_generator(), consumed_events
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
                execution_context=ExecutionContext(
                    conversation_id="conversation_id",
                    execution_id="execution_id",
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

    def test_execute(
        self, populated_workflow, sample_execution_context, sample_messages
    ):
        """Test synchronous execute method."""
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

            # Mock the node's execute method to return sample messages
            mock_node.execute = Mock(return_value=sample_messages)

            # Add node to execution queue
            populated_workflow.execution_queue.append(mock_node)

            result = populated_workflow.execute(
                sample_execution_context, sample_messages
            )

            mock_initial.assert_called_once()
            mock_node.execute.assert_called_once()
            mock_publish.assert_called_once()
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_a_execute(
        self, populated_workflow, sample_execution_context, sample_messages
    ):
        """Test asynchronous a_execute method."""
        with patch.object(
            EventDrivenWorkflow, "initial_workflow"
        ) as mock_initial, patch.object(
            EventDrivenWorkflow, "_process_all_nodes"
        ) as mock_process, patch.object(
            EventDrivenWorkflow, "_record_consumed_events"
        ) as mock_record, patch(
            "grafi.workflows.impl.event_driven_workflow.agent_output_topic"
        ) as mock_output_topic:
            # Mock the generator
            async def mock_get_events():
                yield Mock(
                    spec=OutputAsyncEvent,
                    data=[Message(content="test", role="assistant")],
                )

            mock_output_topic.get_events.return_value = mock_get_events()
            mock_output_topic.is_empty.return_value = True
            mock_process.return_value = mock_record

            results = []
            async for result in populated_workflow.a_execute(
                sample_execution_context, sample_messages
            ):
                results.append(result)

            mock_initial.assert_called_once()
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_process_all_nodes(
        self, populated_workflow, sample_execution_context
    ):
        """Test _process_all_nodes method."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        populated_workflow.execution_queue.append(mock_node)

        with patch.object(EventDrivenWorkflow, "_execute_node") as mock_execute, patch(
            "grafi.workflows.impl.event_driven_workflow.agent_output_topic"
        ) as mock_output_topic:
            mock_execute.return_value = None
            mock_output_topic.wait_for_completion = AsyncMock()

            running_tasks = set()
            executing_nodes = set()

            await populated_workflow._process_all_nodes(
                sample_execution_context, running_tasks, executing_nodes
            )

            mock_execute.assert_called_once()
            mock_output_topic.wait_for_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_node(self, populated_workflow, sample_execution_context):
        """Test _execute_node method."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        executing_nodes = set()

        with patch.object(
            EventDrivenWorkflow, "get_node_input"
        ) as mock_get_input, patch.object(
            EventDrivenWorkflow, "_publish_agen_events"
        ) as mock_publish:
            mock_get_input.return_value = [Mock(spec=ConsumeFromTopicEvent)]
            mock_publish.return_value = None

            await populated_workflow._execute_node(
                sample_execution_context, mock_node, executing_nodes
            )

            mock_node.a_execute.assert_called_once()
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
            execution_context=ExecutionContext(
                conversation_id="conversation_id",
                execution_id="execution_id",
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
            execution_context=ExecutionContext(
                conversation_id="conversation_id",
                execution_id="execution_id",
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

        initial_queue_length = len(populated_workflow.execution_queue)
        populated_workflow.on_event(event)

        assert len(populated_workflow.execution_queue) == initial_queue_length

    def test_on_event_unknown_topic(self, populated_workflow):
        """Test on_event with unknown topic."""
        event = Mock(spec=PublishToTopicEvent)
        event.topic_name = "unknown_topic"

        initial_queue_length = len(populated_workflow.execution_queue)
        populated_workflow.on_event(event)

        assert len(populated_workflow.execution_queue) == initial_queue_length

    def test_initial_workflow_no_existing_events(
        self, populated_workflow, sample_execution_context, sample_messages
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
            populated_workflow.topics["agent_input_topic"] = input_topic

            populated_workflow.initial_workflow(
                sample_execution_context, sample_messages
            )

            input_topic.publish_data.assert_called_once()
            mock_record.assert_called_once()

    def test_initial_workflow_with_existing_events(
        self, populated_workflow, sample_execution_context, sample_messages
    ):
        """Test initial_workflow with existing events."""
        mock_event = Mock(spec=PublishToTopicEvent)
        mock_event.topic_name = "agent_input_topic"

        with patch(
            "grafi.common.containers.container.container.event_store.get_agent_events"
        ) as mock_get_events:
            mock_get_events.return_value = [mock_event]

            # Mock topic restoration
            mock_topic = populated_workflow.topics["agent_input_topic"]
            mock_topic.can_consume.return_value = True

            populated_workflow.initial_workflow(
                sample_execution_context, sample_messages
            )

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
            OutputTopicEvent(
                event_id="test_id",
                event_type="PublishToTopic",
                timestamp="2009-02-13T23:31:30+00:00",
                topic_name="test_topic",
                publisher_name="OpenAINode",
                publisher_type="test_type",
                offset=0,
                execution_context=ExecutionContext(
                    conversation_id="conversation_id",
                    execution_id="execution_id",
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
        ]

        with patch(
            "grafi.common.containers.container.container.event_store.record_event"
        ) as mock_record:
            populated_workflow._record_consumed_events(events)

            mock_record.assert_called_once()
            recorded_event = mock_record.call_args[0][0]
            assert isinstance(recorded_event, ConsumeFromTopicEvent)

    def test_record_consumed_events_empty_list(self, populated_workflow):
        """Test _record_consumed_events with empty events list."""
        with patch(
            "grafi.common.containers.container.container.event_store.record_event"
        ) as mock_record:
            populated_workflow._record_consumed_events([])

            mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_node_no_input(
        self, populated_workflow, sample_execution_context
    ):
        """Test _execute_node when no input is available."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        executing_nodes = set()

        with patch.object(EventDrivenWorkflow, "get_node_input") as mock_get_input:
            mock_get_input.return_value = []  # No input available

            await populated_workflow._execute_node(
                sample_execution_context, mock_node, executing_nodes
            )

            mock_node.a_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_node_with_exception(
        self, populated_workflow, sample_execution_context
    ):
        """Test _execute_node when node execution raises exception."""
        mock_node = populated_workflow.nodes["OpenAINode"]
        mock_node.a_execute.side_effect = ValueError("Test error")
        executing_nodes = {"OpenAINode"}

        with patch.object(EventDrivenWorkflow, "get_node_input") as mock_get_input:
            mock_get_input.return_value = [Mock(spec=ConsumeFromTopicEvent)]

            with pytest.raises(ValueError, match="Test error"):
                await populated_workflow._execute_node(
                    sample_execution_context, mock_node, executing_nodes
                )

            # Node should be removed from executing set even on exception
            assert "OpenAINode" not in executing_nodes
