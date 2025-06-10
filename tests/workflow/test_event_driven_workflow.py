from typing import List
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.output_topic import AGENT_OUTPUT_TOPIC
from grafi.common.topics.topic import AGENT_INPUT_TOPIC
from grafi.common.topics.topic import Topic
from grafi.nodes.node import Node
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class MockNode(Node):
    """
    A concrete implementation of Node for testing.
    Implements the abstract methods with dummy behavior.
    """

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.CHAIN
    name: str = "test_node"
    type: str = "test_node"
    command: Command = Field(default=None)

    def execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        return [Message(role="assistant", content="sync dummy")]

    async def a_execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        yield [Message(role="assistant", content="async dummy")]

    def get_command_input(self, node_input: List[ConsumeFromTopicEvent]) -> Messages:
        return [Message(role="assistant", content="command dummy")]


@pytest.fixture
def mock_topic():
    topic = Mock(spec=Topic)
    topic.name = "test_topic_1"
    topic.can_consume = Mock(return_value=True)
    topic.consume = Mock(return_value=[])
    topic.publish_data = Mock()
    topic.reset = Mock()
    topic.restore_topic = Mock()
    return topic


@pytest.fixture
def mock_input_topic():
    topic = Mock(spec=Topic)
    topic.name = AGENT_INPUT_TOPIC
    topic.can_consume = Mock(return_value=True)
    topic.consume = Mock(return_value=[])
    topic.publish_data = Mock()
    topic.reset = Mock()
    topic.restore_topic = Mock()
    return topic


@pytest.fixture
def mock_output_topic():
    topic = Mock(spec=Topic)
    topic.name = AGENT_OUTPUT_TOPIC
    topic.can_consume = Mock(return_value=False)
    topic.consume = Mock(return_value=[])
    topic.publish_data = Mock()
    topic.reset = Mock()
    topic.restore_topic = Mock()
    return topic


@pytest.fixture
def simple_workflow(mock_input_topic, mock_output_topic):
    workflow = EventDrivenWorkflow()
    mock_node = MockNode()
    mock_node._subscribed_topics = {AGENT_INPUT_TOPIC: mock_input_topic}
    mock_node.publish_to = [mock_output_topic]

    workflow.nodes = {"test_node": mock_node}
    workflow.topics = {
        AGENT_INPUT_TOPIC: mock_input_topic,
        AGENT_OUTPUT_TOPIC: mock_output_topic,
    }
    workflow.topic_nodes = {AGENT_INPUT_TOPIC: ["test_node"]}

    return workflow


class TestEventDrivenWorkflow:
    def test_workflow_initialization(self, simple_workflow) -> None:
        """Test if workflow is properly initialized with nodes and topics"""
        assert len(simple_workflow.nodes) == 1
        assert "test_node" in simple_workflow.nodes
        assert len(simple_workflow.topics) == 2
        assert AGENT_INPUT_TOPIC in simple_workflow.topics
        assert AGENT_OUTPUT_TOPIC in simple_workflow.topics

    @patch("grafi.common.containers.container.container")
    def test_on_event_handler(self, mock_container, simple_workflow) -> None:
        """Test event handler functionality"""
        # Create a publish event
        mock_event = MagicMock(spec=PublishToTopicEvent)
        mock_event.topic_name = AGENT_INPUT_TOPIC

        # Handle the event
        simple_workflow.on_event(mock_event)

        # Verify node was added to execution queue
        assert len(simple_workflow.execution_queue) == 1
        assert simple_workflow.execution_queue[0].name == "test_node"

    def test_builder_functionality(self, mock_input_topic, mock_output_topic) -> None:
        """Test the workflow builder functionality"""
        builder = EventDrivenWorkflow.builder()

        # Create a test node
        mock_node = MockNode()
        mock_node._subscribed_topics = {AGENT_INPUT_TOPIC: mock_input_topic}
        mock_node.publish_to = [mock_output_topic]

        # Build workflow
        workflow = builder.node(mock_node).build()

        # Verify workflow was built correctly
        assert len(workflow.nodes) == 1
        assert mock_node.name in workflow.nodes
