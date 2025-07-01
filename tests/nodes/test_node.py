from typing import List
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.command import Command
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_expression import TopicExpr
from grafi.nodes.node import Node
from grafi.nodes.node_base import NodeBaseBuilder
from grafi.tools.tool import Tool


class MockTool(Tool):
    """Mock Tool for testing purposes."""

    def __init__(self, name: str = "mock_tool", **kwargs):
        super().__init__(
            name=name,
            type="MockTool",
            oi_span_type=OpenInferenceSpanKindValues.TOOL,
            **kwargs,
        )

    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        return [Message(role="assistant", content=f"Mock response from {self.name}")]

    async def a_invoke(self, invoke_context: InvokeContext, input_data: Messages):
        yield [
            Message(role="assistant", content=f"Mock async response from {self.name}")
        ]


class MockTopic(TopicBase):
    """Mock Topic for testing purposes."""

    def __init__(self, name: str = "mock_topic", **kwargs):
        super().__init__(name=name, **kwargs)

    def publish_data(
        self, invoke_context, publisher_name, publisher_type, data, consumed_event_ids
    ):
        pass

    def can_consume(self, consumer_name: str) -> bool:
        return True

    def consume(self, consumer_name: str) -> List:
        return []

    def to_dict(self):
        return {"name": self.name, "type": "MockTopic"}


class TestNode:
    """Test suite for the Node class."""

    @pytest.fixture
    def invoke_context(self) -> InvokeContext:
        """Fixture providing a mock InvokeContext."""
        return InvokeContext(
            conversation_id="test_conversation",
            invoke_id="test_invoke",
            assistant_request_id="test_request",
        )

    @pytest.fixture
    def mock_tool(self) -> MockTool:
        """Fixture providing a mock Tool."""
        return MockTool(name="test_tool")

    @pytest.fixture
    def mock_topic(self) -> MockTopic:
        """Fixture providing a mock Topic."""
        return MockTopic(name="test_topic")

    @pytest.fixture
    def sample_messages(self) -> Messages:
        """Fixture providing sample messages."""
        return [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ]

    @pytest.fixture
    def sample_consumed_events(
        self, invoke_context: InvokeContext, sample_messages: Messages
    ) -> List[ConsumeFromTopicEvent]:
        """Fixture providing sample consumed events."""
        return [
            ConsumeFromTopicEvent(
                event_id="event_1",
                topic_name="test_topic",
                consumer_name="test_node",
                consumer_type="Node",
                offset=0,
                invoke_context=invoke_context,
                data=sample_messages,
            )
        ]

    @pytest.fixture
    def basic_node(self) -> Node:
        """Fixture providing a basic Node instance."""
        return Node(name="test_node")

    @pytest.fixture
    def node_with_tool(self, mock_tool: MockTool) -> Node:
        """Fixture providing a Node instance with a tool."""
        return Node(name="test_node_with_tool", tool=mock_tool)

    @pytest.fixture
    def node_with_subscriptions(self, mock_topic: MockTopic) -> Node:
        """Fixture providing a Node instance with subscriptions."""
        topic_expr = TopicExpr(topic=mock_topic)
        return Node(
            name="test_node_with_subscriptions",
            subscribed_expressions=[topic_expr],
        )

    # Test Node Creation and Initialization
    def test_node_creation_basic(self, basic_node: Node):
        """Test basic Node creation."""
        assert basic_node.name == "test_node"
        assert basic_node.type == "Node"
        assert basic_node.tool is None
        assert basic_node.subscribed_expressions == []
        assert basic_node.publish_to == []
        assert basic_node._subscribed_topics == {}
        assert basic_node._command is None

    def test_node_creation_with_tool(self, node_with_tool: Node, mock_tool: MockTool):
        """Test Node creation with a tool."""
        assert node_with_tool.name == "test_node_with_tool"
        assert node_with_tool.tool is mock_tool
        assert node_with_tool._command is not None
        assert isinstance(node_with_tool._command, Command)

    def test_node_creation_with_subscriptions(self, node_with_subscriptions: Node):
        """Test Node creation with subscriptions."""
        assert node_with_subscriptions.name == "test_node_with_subscriptions"
        assert len(node_with_subscriptions.subscribed_expressions) == 1
        assert len(node_with_subscriptions._subscribed_topics) == 1
        assert "test_topic" in node_with_subscriptions._subscribed_topics

    def test_model_post_init_sets_up_subscribed_topics(self, mock_topic: MockTopic):
        """Test that model_post_init properly sets up subscribed topics."""
        topic_expr = TopicExpr(topic=mock_topic)
        node = Node(
            name="test_node",
            subscribed_expressions=[topic_expr],
        )

        assert "test_topic" in node._subscribed_topics
        assert node._subscribed_topics["test_topic"] is mock_topic

    def test_model_post_init_creates_command_for_tool(self, mock_tool: MockTool):
        """Test that model_post_init creates a command when tool is provided."""
        node = Node(name="test_node", tool=mock_tool)

        assert node._command is not None
        assert isinstance(node._command, Command)
        assert node._command.tool is mock_tool

    def test_model_post_init_no_command_without_tool(self):
        """Test that model_post_init doesn't create command without tool."""
        node = Node(name="test_node")
        assert node._command is None

    def test_model_post_init_multiple_expressions_same_topic(
        self, mock_topic: MockTopic
    ):
        """Test model_post_init with multiple expressions referencing the same topic."""
        expr1 = TopicExpr(topic=mock_topic)
        expr2 = TopicExpr(topic=mock_topic)

        node = Node(
            name="test_node",
            subscribed_expressions=[expr1, expr2],
        )

        # Should still only have one entry in _subscribed_topics
        assert len(node._subscribed_topics) == 1
        assert "test_topic" in node._subscribed_topics

    # Test Builder Pattern
    def test_builder_returns_correct_type(self):
        """Test that Node.builder() returns the correct builder type."""
        builder = Node.builder()
        assert isinstance(builder, NodeBaseBuilder)

    def test_builder_creates_node(self):
        """Test that the builder can create a Node."""
        node = Node.builder().name("built_node").build()
        assert isinstance(node, Node)
        assert node.name == "built_node"

    def test_builder_with_tool(self, mock_tool: MockTool):
        """Test building a Node with a tool."""
        node = Node.builder().name("built_node").tool(mock_tool).build()

        assert node.tool is mock_tool
        assert node._command is not None
        assert isinstance(node._command, Command)

    def test_builder_with_subscriptions(self, mock_topic: MockTopic):
        """Test building a Node with subscriptions."""
        node = Node.builder().name("built_node").subscribe(mock_topic).build()
        assert len(node.subscribed_expressions) == 1
        assert "test_topic" in node._subscribed_topics

    def test_builder_with_publish_to(self, mock_topic: MockTopic):
        """Test building a Node with publish_to topics."""
        node = Node.builder().name("built_node").publish_to(mock_topic).build()
        assert len(node.publish_to) == 1
        assert node.publish_to[0] is mock_topic

    def test_builder_chaining(self, mock_tool: MockTool, mock_topic: MockTopic):
        """Test builder method chaining."""
        node = (
            Node.builder()
            .name("chained_node")
            .tool(mock_tool)
            .subscribe(mock_topic)
            .publish_to(mock_topic)
            .build()
        )

        assert node.name == "chained_node"
        assert node.tool is mock_tool
        assert len(node.subscribed_expressions) == 1
        assert len(node.publish_to) == 1

    # Test Invoke Method
    @patch("grafi.nodes.node.record_node_invoke")
    def test_invoke_with_tool(
        self,
        mock_decorator,
        node_with_tool: Node,
        invoke_context: InvokeContext,
        sample_consumed_events: List[ConsumeFromTopicEvent],
    ):
        """Test invoking a Node with a tool."""
        # Mock the decorator to return the original function
        mock_decorator.side_effect = lambda func: func

        # The actual Command has invoke method, so we test it directly
        result = node_with_tool.invoke(invoke_context, sample_consumed_events)

        # Verify we get a result (the actual implementation should work)
        assert isinstance(result, list)

    @patch("grafi.nodes.node.record_node_invoke")
    def test_invoke_without_tool_raises_error(
        self,
        mock_decorator,
        basic_node: Node,
        invoke_context: InvokeContext,
        sample_consumed_events: List[ConsumeFromTopicEvent],
    ):
        """Test invoking a Node without a tool raises an error."""
        mock_decorator.side_effect = lambda func: func

        # Node without tool should not have a command
        assert basic_node._command is None

        with pytest.raises(AttributeError):
            basic_node.invoke(invoke_context, sample_consumed_events)

    # Test Async Invoke Method
    @patch("grafi.nodes.node.record_node_a_invoke")
    @pytest.mark.asyncio
    async def test_a_invoke_with_tool(
        self,
        mock_decorator,
        node_with_tool: Node,
        invoke_context: InvokeContext,
        sample_consumed_events: List[ConsumeFromTopicEvent],
    ):
        """Test async invoking a Node with a tool."""
        mock_decorator.side_effect = lambda func: func

        messages = []
        async for message_batch in node_with_tool.a_invoke(
            invoke_context, sample_consumed_events
        ):
            messages.extend(message_batch)

        # Verify we get results
        assert isinstance(messages, list)

    @patch("grafi.nodes.node.record_node_a_invoke")
    @pytest.mark.asyncio
    async def test_a_invoke_without_tool_raises_error(
        self,
        mock_decorator,
        basic_node: Node,
        invoke_context: InvokeContext,
        sample_consumed_events: List[ConsumeFromTopicEvent],
    ):
        """Test async invoking a Node without a tool raises an error."""
        mock_decorator.side_effect = lambda func: func

        with pytest.raises(AttributeError):
            async for _ in basic_node.a_invoke(invoke_context, sample_consumed_events):
                pass

    # Test can_invoke Method
    def test_can_invoke_no_subscriptions(self, basic_node: Node):
        """Test can_invoke returns True when no subscriptions are defined."""
        assert basic_node.can_invoke() is True

    def test_can_invoke_with_subscriptions_all_satisfied(self, mock_topic: MockTopic):
        """Test can_invoke returns True when all subscription expressions are satisfied."""
        topic_expr = TopicExpr(topic=mock_topic)
        node = Node(
            name="test_node",
            subscribed_expressions=[topic_expr],
        )

        # The MockTopic already has can_consume method that returns True
        with patch(
            "grafi.common.topics.topic_expression.evaluate_subscription",
            return_value=True,
        ):
            assert node.can_invoke() is True

    def test_can_invoke_with_subscriptions_not_satisfied(self, mock_topic: MockTopic):
        """Test can_invoke returns False when subscription expressions are not satisfied."""
        topic_expr = TopicExpr(topic=mock_topic)
        node = Node(
            name="test_node",
            subscribed_expressions=[topic_expr],
        )

        # Mock evaluate_subscription to return False
        with patch(
            "grafi.nodes.node.evaluate_subscription",
            return_value=False,
        ):
            assert node.can_invoke() is False

    def test_can_invoke_with_multiple_subscriptions(self):
        """Test can_invoke with multiple subscription expressions."""
        topic1 = MockTopic(name="topic1")
        topic2 = MockTopic(name="topic2")

        expr1 = TopicExpr(topic=topic1)
        expr2 = TopicExpr(topic=topic2)

        node = Node(
            name="test_node",
            subscribed_expressions=[expr1, expr2],
        )

        # Both expressions evaluate to True - should return True
        with patch(
            "grafi.nodes.node.evaluate_subscription",
            return_value=True,
        ):
            assert node.can_invoke() is True

    # Test to_dict Method
    def test_to_dict_basic_node(self, basic_node: Node):
        """Test to_dict for a basic Node."""
        result = basic_node.to_dict()

        assert "node_id" in result
        assert result["subscribed_expressions"] == []
        assert result["publish_to"] == []
        assert result["command"] is None

    def test_to_dict_node_with_tool(self, node_with_tool: Node):
        """Test to_dict for a Node with a tool."""
        result = node_with_tool.to_dict()

        assert "node_id" in result
        assert result["subscribed_expressions"] == []
        assert result["publish_to"] == []
        assert result["command"] is not None  # Command should have to_dict method

    def test_to_dict_node_with_subscriptions(self, node_with_subscriptions: Node):
        """Test to_dict for a Node with subscriptions."""
        result = node_with_subscriptions.to_dict()

        assert "node_id" in result
        assert len(result["subscribed_expressions"]) == 1
        assert result["publish_to"] == []

    def test_to_dict_node_with_publish_to(self, mock_topic: MockTopic):
        """Test to_dict for a Node with publish_to topics."""
        node = Node(name="test_node", publish_to=[mock_topic])
        result = node.to_dict()

        assert "node_id" in result
        assert result["subscribed_expressions"] == []
        assert len(result["publish_to"]) == 1
        assert result["publish_to"][0] == {"name": "test_topic", "type": "MockTopic"}

    def test_to_dict_complete_node(self, mock_tool: MockTool, mock_topic: MockTopic):
        """Test to_dict for a Node with all features."""
        topic_expr = TopicExpr(topic=mock_topic)

        node = Node(
            name="complete_node",
            tool=mock_tool,
            subscribed_expressions=[topic_expr],
            publish_to=[mock_topic],
        )

        result = node.to_dict()

        assert "node_id" in result
        assert len(result["subscribed_expressions"]) == 1
        assert len(result["publish_to"]) == 1
        assert result["publish_to"][0] == {"name": "test_topic", "type": "MockTopic"}
        assert result["command"] is not None

    # Test Property Access
    def test_command_property_getter(self, node_with_tool: Node):
        """Test the command property getter."""
        assert node_with_tool.command is node_with_tool._command

    def test_command_property_setter(self, basic_node: Node, mock_tool: MockTool):
        """Test the command property setter."""
        command = Command(tool=mock_tool)
        basic_node.command = command
        assert basic_node._command is command
        assert basic_node.command is command

    def test_command_property_none_initially(self, basic_node: Node):
        """Test that command property is None initially for nodes without tools."""
        assert basic_node.command is None

    # Test Error Handling
    def test_node_with_invalid_tool_type(self):
        """Test Node creation with invalid tool type."""
        with pytest.raises((TypeError, ValueError)):
            Node(name="test_node", tool="invalid_tool")

    def test_node_with_invalid_subscription_type(self):
        """Test Node creation with invalid subscription type."""
        with pytest.raises((TypeError, ValueError)):
            Node(name="test_node", subscribed_expressions=["invalid_expression"])

    @pytest.mark.asyncio
    async def test_full_async_workflow_simulation(
        self, mock_tool: MockTool, mock_topic: MockTopic, invoke_context: InvokeContext
    ):
        """Test a full async workflow simulation with a Node."""
        topic_expr = TopicExpr(topic=mock_topic)

        node = Node(
            name="async_workflow_node",
            tool=mock_tool,
            subscribed_expressions=[topic_expr],
            publish_to=[mock_topic],
        )

        sample_events = [
            ConsumeFromTopicEvent(
                event_id="event_1",
                topic_name="test_topic",
                consumer_name="async_workflow_node",
                consumer_type="Node",
                offset=0,
                invoke_context=invoke_context,
                data=[Message(role="user", content="Test async input")],
            )
        ]

        with patch("grafi.nodes.node.record_node_a_invoke") as mock_decorator:
            mock_decorator.side_effect = lambda func: func

            messages = []
            async for message_batch in node.a_invoke(invoke_context, sample_events):
                messages.extend(message_batch)

            assert isinstance(messages, list)

    # Test Edge Cases
    def test_node_with_empty_subscribed_expressions_list(self):
        """Test Node with empty subscribed_expressions list."""
        node = Node(name="test_node", subscribed_expressions=[])
        assert node.can_invoke() is True
        assert node._subscribed_topics == {}

    def test_node_with_empty_publish_to_list(self):
        """Test Node with empty publish_to list."""
        node = Node(name="test_node", publish_to=[])
        assert len(node.publish_to) == 0

    def test_node_id_generation(self):
        """Test that node_id is generated automatically."""
        node1 = Node(name="test_node1")
        node2 = Node(name="test_node2")

        assert node1.node_id != node2.node_id
        assert len(node1.node_id) > 0
        assert len(node2.node_id) > 0

    def test_node_with_custom_node_id(self):
        """Test Node creation with custom node_id."""
        custom_id = "custom_test_id"
        node = Node(name="test_node", node_id=custom_id)
        assert node.node_id == custom_id

    def test_node_inheritance_structure(self):
        """Test that Node properly inherits from NodeBase."""
        from grafi.nodes.node_base import NodeBase

        node = Node(name="test_node")
        assert isinstance(node, NodeBase)

    def test_node_default_values(self):
        """Test Node default field values."""
        node = Node()

        assert node.name == "Node"
        assert node.type == "Node"
        assert node.tool is None
        assert node.oi_span_type == OpenInferenceSpanKindValues.CHAIN
        assert node.subscribed_expressions == []
        assert node.publish_to == []
        assert node._subscribed_topics == {}
        assert node._command is None

    def test_node_serialization_compatibility(
        self, mock_tool: MockTool, mock_topic: MockTopic
    ):
        """Test that Node serialization is compatible with JSON."""
        topic_expr = TopicExpr(topic=mock_topic)

        node = Node(
            name="serialization_test_node",
            tool=mock_tool,
            subscribed_expressions=[topic_expr],
            publish_to=[mock_topic],
        )

        node_dict = node.to_dict()

        # Verify structure is JSON-serializable
        import json

        json_str = json.dumps(node_dict, default=str)
        assert isinstance(json_str, str)
        assert len(json_str) > 0

        # Verify we can load it back
        loaded_dict = json.loads(json_str)
        assert isinstance(loaded_dict, dict)
        assert "node_id" in loaded_dict

    # Test Command Factory Method Integration
    def test_command_factory_integration(self, mock_tool: MockTool):
        """Test that Command.for_tool is called correctly during node creation."""
        with patch(
            "grafi.common.models.command.Command.for_tool",
            return_value=Command(tool=mock_tool),
        ) as mock_factory:
            node = Node(name="test_node", tool=mock_tool)

            assert node._command is not None
            mock_factory.assert_called_once_with(mock_tool)

    def test_tool_command_consistency(self, mock_tool: MockTool):
        """Test that the tool in the command matches the node's tool."""
        node = Node(name="test_node", tool=mock_tool)

        assert node.tool is mock_tool
        assert node._command.tool is mock_tool
