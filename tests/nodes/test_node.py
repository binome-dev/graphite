import json
from typing import Dict
from typing import List
from typing import Optional
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from grafi.common.events.component_events import NodeRespondEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.nodes.conditions import always_true
from grafi.nodes.node import Node
from grafi.nodes.node_base import NodeBase
from grafi.nodes.node_base import NodeBaseBuilder
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.tools.command import Command
from grafi.tools.command import use_command
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.tool import Tool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.expressions.topic_expression import CombinedExpr
from grafi.topics.expressions.topic_expression import LogicalOp
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType


class MockTool(Tool):
    """Mock Tool for testing purposes."""

    # Defaults as fields, not a custom __init__, which loading would call too.
    name: Optional[str] = "mock_tool"
    type: Optional[str] = "MockTool"
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context: InvokeContext, input_data: Messages):
        return [
            Message(role="assistant", content=f"Mock async response from {self.name}")
        ]


class CustomCommand(Command):
    """Passes the tool only the last message it consumed."""

    async def get_tool_input(self, invoke_context, input_data) -> Messages:
        return input_data[-1].data[-1:]


@use_command(CustomCommand)
class CustomCommandTool(MockTool):
    """A tool whose class names the command a node runs it through."""


class MockTopic(TopicBase):
    """Mock Topic for testing purposes."""

    def __init__(self, name: str = "mock_topic", **kwargs):
        super().__init__(name=name, **kwargs)

    def publish_data(
        self, invoke_context, publisher_name, publisher_type, data, consumed_event_ids
    ):
        pass

    async def can_consume(self, consumer_name: str) -> bool:
        return True

    async def consume(self, consumer_name: str) -> List:
        return []


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
                name="test_topic",
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
        assert basic_node.command is None

    def test_node_creation_with_tool(self, node_with_tool: Node, mock_tool: MockTool):
        """Test Node creation with a tool."""
        assert node_with_tool.name == "test_node_with_tool"
        assert node_with_tool.tool is mock_tool
        assert node_with_tool.command is not None
        assert isinstance(node_with_tool.command, Command)

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

        assert node.command is not None
        assert isinstance(node.command, Command)
        assert node.command.tool is mock_tool

    def test_model_post_init_no_command_without_tool(self):
        """Test that model_post_init doesn't create command without tool."""
        node = Node(name="test_node")
        assert node.command is None

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
        assert node.command is not None
        assert isinstance(node.command, Command)

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
    @pytest.mark.asyncio
    async def test_invoke_with_tool(
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
        messages = []
        async for message_batch in node_with_tool.invoke(
            invoke_context, sample_consumed_events
        ):
            messages.append(message_batch)

        # Verify we get results
        assert isinstance(messages, list)

    @patch("grafi.nodes.node.record_node_invoke")
    @pytest.mark.asyncio
    async def test_invoke_without_tool_raises_error(
        self,
        mock_decorator,
        basic_node: Node,
        invoke_context: InvokeContext,
        sample_consumed_events: List[ConsumeFromTopicEvent],
    ):
        """Test invoking a Node without a tool raises an error."""
        mock_decorator.side_effect = lambda func: func

        # Node without tool should not have a command
        assert basic_node.command is None

        # A node without a tool raises a clear NodeExecutionError rather than an
        # opaque AttributeError from calling .invoke() on None.
        from grafi.common.exceptions import NodeExecutionError

        with pytest.raises(NodeExecutionError, match="without a tool"):
            async for _ in basic_node.invoke(invoke_context, sample_consumed_events):
                pass

    # Test can_invoke Method
    @pytest.mark.asyncio
    async def test_can_invoke_no_subscriptions(self, basic_node: Node):
        """Test can_invoke returns True when no subscriptions are defined."""
        assert await basic_node.can_invoke() is True

    @pytest.mark.asyncio
    async def test_can_invoke_with_subscriptions_all_satisfied(
        self, mock_topic: MockTopic
    ):
        """Test can_invoke returns True when all subscription expressions are satisfied."""
        topic_expr = TopicExpr(topic=mock_topic)
        node = Node(
            name="test_node",
            subscribed_expressions=[topic_expr],
        )

        # Patch the method at the class level to work with Pydantic models
        with patch.object(
            MockTopic, "can_consume", new_callable=AsyncMock
        ) as mock_can_consume:
            mock_can_consume.return_value = True
            with patch(
                "grafi.topics.expressions.topic_expression.evaluate_subscription",
                return_value=True,
            ):
                assert await node.can_invoke() is True

    # Test model_dump
    def test_dump_basic_node(self, basic_node: Node):
        """Test model_dump for a basic Node."""
        result = basic_node.model_dump(mode="json")

        assert result["class"] == "grafi.nodes.node:Node"
        assert result["node_id"] == basic_node.node_id
        assert result["name"] == "test_node"
        assert result["tool"] is None
        assert result["subscribed_expressions"] == []
        assert result["publisher_router"]["routes"] == []
        # The command follows from the tool's class, so it is not saved.
        assert "command" not in result

    def test_dump_node_with_tool(self, node_with_tool: Node, mock_tool: MockTool):
        """Test model_dump for a Node with a tool: the tool's JSON, with its class."""
        result = node_with_tool.model_dump(mode="json")

        assert result["subscribed_expressions"] == []
        assert result["publisher_router"]["routes"] == []
        assert result["tool"] == mock_tool.model_dump(mode="json")
        assert result["tool"]["class"] == f"{__name__}:MockTool"
        assert result["tool"]["name"] == "test_tool"
        assert "command" not in result

    def test_dump_node_with_subscriptions(self, node_with_subscriptions: Node):
        """Test model_dump for a Node with subscriptions: topics by name."""
        result = node_with_subscriptions.model_dump(mode="json")

        assert result["subscribed_expressions"] == [{"topic": "test_topic"}]
        assert result["publisher_router"]["routes"] == []

    def test_dump_node_with_publish_to(self, mock_topic: MockTopic):
        """Test model_dump for a Node with publish_to topics."""
        node = Node(
            name="test_node",
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=mock_topic)]),
        )
        result = node.model_dump(mode="json")

        assert result["subscribed_expressions"] == []
        assert result["publisher_router"]["routes"] == [
            {
                "topic": "test_topic",
                "when": {"ref": "grafi.nodes.conditions:always_true"},
            }
        ]

    def test_dump_complete_node(self, mock_tool: MockTool, mock_topic: MockTopic):
        """Test model_dump for a Node with all features."""
        topic_expr = TopicExpr(topic=mock_topic)

        node = Node(
            name="complete_node",
            tool=mock_tool,
            subscribed_expressions=[topic_expr],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=mock_topic)]),
        )

        result = node.model_dump(mode="json")

        assert list(result) == [
            "class",
            "node_id",
            "name",
            "type",
            "tool",
            "oi_span_type",
            "subscribed_expressions",
            "publisher_router",
        ]
        assert result["subscribed_expressions"] == [{"topic": "test_topic"}]
        assert result["publisher_router"]["routes"][0]["topic"] == "test_topic"
        assert result["tool"]["class"] == f"{__name__}:MockTool"

    # Test Property Access
    def test_command_property_getter(self, node_with_tool: Node):
        """Test the command property getter."""
        assert node_with_tool.command is node_with_tool.command

    def test_a_command_follows_from_the_tools_class(self):
        """A node runs its tool through the command the tool's class names,
        so a saved node loads with it; a command cannot be set apart."""
        node = Node(name="custom", tool=CustomCommandTool())
        assert type(node.command) is CustomCommand
        assert node.command.tool is node.tool

        restored = Node.model_validate(node.model_dump(mode="json"))
        assert type(restored.command) is CustomCommand

        with pytest.raises((AttributeError, ValueError)):
            node.command = Command(tool=MockTool())

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
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=mock_topic)]),
        )

        sample_events = [
            ConsumeFromTopicEvent(
                event_id="event_1",
                name="test_topic",
                consumer_name="async_workflow_node",
                consumer_type="Node",
                offset=0,
                invoke_context=invoke_context,
                data=[Message(role="user", content="Test async input")],
            )
        ]

        with patch("grafi.nodes.node.record_node_invoke") as mock_decorator:
            mock_decorator.side_effect = lambda func: func

            messages = []
            async for message_batch in node.invoke(invoke_context, sample_events):
                messages.extend(message_batch)

            assert isinstance(messages, list)

    # Test Edge Cases
    @pytest.mark.asyncio
    async def test_node_with_empty_subscribed_expressions_list(self):
        """Test Node with empty subscribed_expressions list."""
        node = Node(name="test_node", subscribed_expressions=[])
        assert await node.can_invoke() is True
        assert node._subscribed_topics == {}

    def test_node_with_empty_publish_to_list(self):
        """Test Node with empty publish_to list."""
        node = Node(name="test_node", publisher_router=PublisherRouter())
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
        assert node.command is None

    def test_node_serialization_compatibility(
        self, mock_tool: MockTool, mock_topic: MockTopic
    ):
        """Test that Node serialization is compatible with JSON."""
        topic_expr = TopicExpr(topic=mock_topic)

        node = Node(
            name="serialization_test_node",
            tool=mock_tool,
            subscribed_expressions=[topic_expr],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=mock_topic)]),
        )

        node_dict = node.model_dump(mode="json")

        # Verify structure is JSON-serializable without help
        import json

        json_str = json.dumps(node_dict)

        # Verify we can load it back
        loaded_dict = json.loads(json_str)
        assert loaded_dict == node_dict
        restored = Node.model_validate(
            loaded_dict, context={"topics": {"test_topic": mock_topic}}
        )
        assert restored.model_dump(mode="json") == node_dict

    # Test Command Factory Method Integration
    def test_command_factory_integration(self, mock_tool: MockTool):
        """Test that Command.for_tool is called correctly during node creation."""
        with patch(
            "grafi.tools.command.Command.for_tool",
            return_value=Command(tool=mock_tool),
        ) as mock_factory:
            node = Node(name="test_node", tool=mock_tool)

            assert node.command is not None
            mock_factory.assert_called_once_with(mock_tool)

    def test_tool_command_consistency(self, mock_tool: MockTool):
        """Test that the tool in the command matches the node's tool."""
        node = Node(name="test_node", tool=mock_tool)

        assert node.tool is mock_tool
        assert node.command.tool is mock_tool


class TestNodeIdRoundTrip:
    """node_id must survive a builder set and a dump/load round-trip."""

    def test_builder_sets_node_id(self):
        node = Node.builder().node_id("fixed-id").name("n").type("Node").build()
        assert node.node_id == "fixed-id"

    def test_model_validate_preserves_node_id(self):
        from grafi.tools.llms.impl.openai_tool import OpenAITool

        original = Node(
            name="n",
            type="Node",
            tool=OpenAITool.builder().name("llm").model("gpt-4o-mini").build(),
        )
        data = original.model_dump(mode="json")
        assert data["node_id"] == original.node_id

        restored = Node.model_validate(data)
        # Recovered node keeps its identity instead of getting a fresh uuid.
        assert restored.node_id == original.node_id


def _is_final(event: PublishToTopicEvent) -> bool:
    """A routing predicate, saved by reference."""
    return not any(message.tool_calls for message in event.data)


class ExtendedNode(Node):
    """A user's node with a field of its own."""

    priority: int = 0


class TestNodeSerialization:
    """A node is saved with its tool, subscriptions and routes, and loads back
    in the context of its workflow's topics."""

    @pytest.fixture
    def topics(self) -> Dict[str, TopicBase]:
        return {
            "agent_input": InputTopic(name="agent_input"),
            "approval": InWorkflowInputTopic(name="approval"),
            "agent_output": OutputTopic(name="agent_output"),
            "trace": Topic(name="trace"),
        }

    @pytest.fixture
    def node(self, topics: Dict[str, TopicBase]) -> Node:
        tool = MockTool(name="restorable_tool")
        subscription = (
            SubscriptionBuilder()
            .subscribed_to(topics["agent_input"])
            .or_()
            .subscribed_to(topics["approval"])
            .build()
        )
        return (
            Node.builder()
            .name("complete_node")
            .type("CustomType")
            .oi_span_type(OpenInferenceSpanKindValues.TOOL)
            .tool(tool)
            .subscribe(subscription)
            .subscribe(topics["trace"])
            .publish_to(topics["agent_output"], when=_is_final)
            .publish_to(topics["trace"])
            .build()
        )

    def test_dump(self, node: Node):
        data = node.model_dump(mode="json")

        assert data["class"] == "grafi.nodes.node:Node"
        assert data["subscribed_expressions"] == [
            {
                "op": "OR",
                "left": {"topic": "agent_input"},
                "right": {"topic": "approval"},
            },
            {"topic": "trace"},
        ]
        assert data["publisher_router"] == {
            "routes": [
                {"topic": "agent_output", "when": {"ref": f"{__name__}:_is_final"}},
                {
                    "topic": "trace",
                    "when": {"ref": "grafi.nodes.conditions:always_true"},
                },
            ]
        }
        assert data["oi_span_type"] == "TOOL"
        assert "command" not in data

    def test_round_trip(self, node: Node, topics: Dict[str, TopicBase]):
        data = node.model_dump(mode="json")

        restored = Node.model_validate(data, context={"topics": topics})

        assert type(restored) is Node
        assert restored.node_id == node.node_id
        assert restored.name == "complete_node"
        assert restored.type == "CustomType"
        assert restored.oi_span_type == OpenInferenceSpanKindValues.TOOL
        # The tool loads as its own class, with its fields
        assert type(restored.tool) is MockTool
        assert restored.tool is not node.tool
        assert restored.tool.tool_id == node.tool.tool_id
        assert restored.tool.name == "restorable_tool"
        assert restored.tool.type == "MockTool"
        # ... and the command is made for it again
        assert type(restored.command) is Command
        assert restored.command.tool is restored.tool
        # Subscriptions and routes refer to the context's topic instances
        expr = restored.subscribed_expressions[0]
        assert isinstance(expr, CombinedExpr)
        assert expr.op == LogicalOp.OR
        assert expr.left.topic is topics["agent_input"]
        assert expr.right.topic is topics["approval"]
        assert restored.subscribed_expressions[1].topic is topics["trace"]
        assert restored._subscribed_topics == {
            name: topics[name] for name in ("agent_input", "approval", "trace")
        }
        assert restored.publish_to == [topics["agent_output"], topics["trace"]]
        routes = restored.publisher_router.routes
        assert routes[0].when is _is_final
        assert routes[1].when is always_true
        # Saving it again gives the same data
        assert restored.model_dump(mode="json") == data

    def test_python_dump_round_trips(self, node: Node, topics: Dict[str, TopicBase]):
        """A python-mode dump holds values: classes, functions and topics
        themselves, in full; it loads back in this process."""
        data = node.model_dump()

        assert data["class"] is Node
        assert data["tool"]["class"] is MockTool
        assert data["subscribed_expressions"][1] == {
            "topic": {
                "class": Topic,
                "name": "trace",
                "type": TopicType.DEFAULT_TOPIC_TYPE,
            }
        }
        assert data["publisher_router"]["routes"][0]["when"] is _is_final

        restored = Node.model_validate(data, context={"topics": topics})

        assert type(restored) is Node
        assert restored.node_id == node.node_id
        assert type(restored.tool) is MockTool
        assert restored.tool.tool_id == node.tool.tool_id
        assert type(restored.command) is Command
        assert restored.subscribed_topics == node.subscribed_topics
        assert restored.subscribed_expressions[1].topic is topics["trace"]
        assert restored.publish_to == [topics["agent_output"], topics["trace"]]
        assert [route.when for route in restored.publisher_router.routes] == [
            _is_final,
            always_true,
        ]
        assert restored.model_dump() == data
        assert restored.model_dump(mode="json") == node.model_dump(mode="json")

    def test_round_trip_through_node_base(
        self, node: Node, topics: Dict[str, TopicBase]
    ):
        """The saved class picks the node class when loading through the base."""
        restored = NodeBase.model_validate(
            node.model_dump(mode="json"), context={"topics": topics}
        )

        assert type(restored) is Node
        assert restored.node_id == node.node_id

    def test_llm_node_gets_its_tools_command(self, topics: Dict[str, TopicBase]):
        """The command follows from the tool's class, not from the manifest."""
        from grafi.tools.llms.impl.openai_tool import OpenAITool
        from grafi.tools.llms.llm_command import LLMCommand

        node = (
            Node.builder()
            .name("llm_node")
            .tool(OpenAITool.builder().name("llm").model("gpt-4o-mini").build())
            .subscribe(topics["agent_input"])
            .publish_to(topics["agent_output"])
            .build()
        )
        data = node.model_dump(mode="json")
        assert "command" not in data
        assert data["tool"]["class"] == "grafi.tools.llms.impl.openai_tool:OpenAITool"
        assert data["tool"]["model"] == "gpt-4o-mini"

        restored = Node.model_validate(data, context={"topics": topics})

        assert type(restored.tool) is OpenAITool
        assert restored.tool.model == "gpt-4o-mini"
        assert type(restored.command) is LLMCommand

    def test_node_without_tool_round_trips(self, topics: Dict[str, TopicBase]):
        node = (
            Node.builder()
            .name("toolless")
            .subscribe(topics["agent_input"])
            .publish_to(topics["agent_output"])
            .build()
        )
        data = node.model_dump(mode="json")
        assert data["tool"] is None

        restored = Node.model_validate(data, context={"topics": topics})

        assert restored.tool is None
        assert restored.command is None
        assert restored.node_id == node.node_id
        assert restored.subscribed_topics == [topics["agent_input"]]
        assert restored.publish_to == [topics["agent_output"]]
        assert restored.model_dump(mode="json") == data

    def test_node_subclass_loads_as_itself(self, topics: Dict[str, TopicBase]):
        node = ExtendedNode(
            name="extended",
            priority=5,
            subscribed_expressions=[TopicExpr(topic=topics["agent_input"])],
        )
        data = node.model_dump(mode="json")
        assert data["class"] == f"{__name__}:ExtendedNode"
        assert data["priority"] == 5

        for base in (Node, NodeBase):
            restored = base.model_validate(data, context={"topics": topics})
            assert type(restored) is ExtendedNode
            assert restored.priority == 5
            assert restored.node_id == node.node_id

    def test_unknown_topic_fails_loudly(self, node: Node, topics: Dict[str, TopicBase]):
        data = node.model_dump(mode="json")
        missing = {name: topic for name, topic in topics.items() if name != "trace"}

        with pytest.raises(ValidationError, match="Unknown topic 'trace'"):
            Node.model_validate(data, context={"topics": missing})

    def test_loading_topics_needs_context(self, node: Node):
        with pytest.raises(ValidationError, match="Unknown topic"):
            Node.model_validate(node.model_dump(mode="json"))

    def test_lambda_route_cannot_be_saved(self, topics: Dict[str, TopicBase]):
        node = (
            Node.builder()
            .name("lambda_node")
            .subscribe(topics["agent_input"])
            .publish_to(topics["agent_output"], when=lambda event: True)
            .build()
        )

        with pytest.raises(PydanticSerializationError, match="without pickle"):
            node.model_dump(mode="json")

    def test_node_manifest(self):
        node = Node(name="lonely", tool=MockTool(name="t"))

        manifest = node.to_manifest()

        assert manifest["apiVersion"] == "grafi/v2"
        assert manifest["kind"] == "Node"
        assert manifest["spec"] == node.model_dump(mode="json")
        restored = Node.from_manifest(manifest)
        assert restored.node_id == node.node_id
        assert type(restored.tool) is MockTool


async def _progress(messages: Messages):
    yield "working..."  # Only streams.
    yield {"step": 1}
    yield {"step": 2}


@pytest.mark.asyncio
async def test_a_node_publishes_and_records_all_its_tools_output_at_once(
    event_store, invoke_context: InvokeContext
):
    """A tool's output is one batch: the node publishes it as one event, and
    its respond event records that event, with every value the function
    yielded (not only the last batch, as when tools yielded several)."""
    topic = Topic(name="out")
    node = Node(
        name="progress",
        tool=FunctionTool(function=_progress),
        publisher_router=PublisherRouter(routes=[PublishRoute(topic=topic)]),
    )
    consumed = [
        ConsumeFromTopicEvent(
            name="in",
            consumer_name="progress",
            consumer_type="Node",
            offset=0,
            invoke_context=invoke_context,
            data=[Message(role="user", content="go")],
        )
    ]

    [published] = [event async for event in node.invoke(invoke_context, consumed)]

    assert [json.loads(m.content) for m in published.data] == [
        {"step": 1},
        {"step": 2},
    ]
    [respond] = [
        event
        for event in await event_store.get_events()
        if isinstance(event, NodeRespondEvent)
    ]
    assert respond.output_data == published


@pytest.mark.asyncio
async def test_a_node_whose_tool_outputs_nothing_publishes_nothing(
    event_store, invoke_context: InvokeContext
):
    node = Node(name="quiet", tool=FunctionTool(function=_nothing))

    assert [event async for event in node.invoke(invoke_context, [])] == []
    [respond] = [
        event
        for event in await event_store.get_events()
        if isinstance(event, NodeRespondEvent)
    ]
    assert respond.output_data is None


def _nothing(messages: Messages) -> None:
    return None


class _Saying(Tool):
    """Says its word."""

    word: str = ""
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context, input_data):
        return [Message(role="assistant", content=self.word)]


@pytest.mark.asyncio
async def test_a_node_copied_with_another_tool_runs_that_tool() -> None:
    """Its command is made from the tool it has, not copied from the original."""
    node = Node(name="speaker", tool=_Saying(word="old"))
    copy = node.model_copy(update={"tool": _Saying(word="new")})
    context = InvokeContext(
        conversation_id="c", invoke_id="i", assistant_request_id="r"
    )

    [published] = [event async for event in copy.invoke(context, [])]

    assert [message.content for message in published.data] == ["new"]
    assert copy.command is not None and copy.command.tool is copy.tool
    assert node.command is not None and node.command.tool is node.tool


def test_a_nodes_command_cannot_be_set() -> None:
    node = Node(name="speaker", tool=_Saying(word="w"))

    with pytest.raises(AttributeError, match="names it with @use_command"):
        node.command = None  # type: ignore[assignment]
