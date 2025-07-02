from typing import List

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
from grafi.common.topics.topic_expression import SubExpr
from grafi.common.topics.topic_expression import TopicExpr
from grafi.nodes.node_base import NodeBase
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


class ConcreteNodeBase(NodeBase):
    """Concrete implementation of NodeBase for testing."""

    def invoke(
        self, invoke_context: InvokeContext, node_input: List[ConsumeFromTopicEvent]
    ) -> Messages:
        return [Message(role="assistant", content="Concrete node response")]

    async def a_invoke(
        self, invoke_context: InvokeContext, node_input: List[ConsumeFromTopicEvent]
    ):
        yield [Message(role="assistant", content="Concrete async node response")]


class TestNodeBase:
    """Test suite for the NodeBase class."""

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
                consumer_type="NodeBase",
                offset=0,
                invoke_context=invoke_context,
                data=sample_messages,
            )
        ]

    @pytest.fixture
    def basic_node_base(self) -> ConcreteNodeBase:
        """Fixture providing a basic NodeBase instance."""
        return ConcreteNodeBase(name="test_node_base")

    @pytest.fixture
    def node_base_with_tool(self, mock_tool: MockTool) -> ConcreteNodeBase:
        """Fixture providing a NodeBase instance with a tool."""
        return ConcreteNodeBase(name="test_node_base_with_tool", tool=mock_tool)

    @pytest.fixture
    def node_base_with_subscriptions(self, mock_topic: MockTopic) -> ConcreteNodeBase:
        """Fixture providing a NodeBase instance with subscriptions."""
        topic_expr = TopicExpr(topic=mock_topic)
        return ConcreteNodeBase(
            name="test_node_base_with_subscriptions",
            subscribed_expressions=[topic_expr],
        )

    # Test NodeBase Creation and Initialization
    def test_node_base_creation_basic(self, basic_node_base: ConcreteNodeBase):
        """Test basic NodeBase creation with default values."""
        assert basic_node_base.name == "test_node_base"
        assert basic_node_base.type == "Node"
        assert basic_node_base.tool is None
        assert basic_node_base.oi_span_type == OpenInferenceSpanKindValues.CHAIN
        assert basic_node_base.subscribed_expressions == []
        assert basic_node_base.publish_to == []
        assert basic_node_base._subscribed_topics == {}
        assert basic_node_base._command is None

    def test_node_base_creation_with_custom_values(
        self, mock_tool: MockTool, mock_topic: MockTopic
    ):
        """Test NodeBase creation with custom values."""
        custom_node_id = "custom_node_id"
        topic_expr = TopicExpr(topic=mock_topic)

        node = ConcreteNodeBase(
            node_id=custom_node_id,
            name="custom_node",
            type="CustomNode",
            tool=mock_tool,
            oi_span_type=OpenInferenceSpanKindValues.AGENT,
            subscribed_expressions=[topic_expr],
            publish_to=[mock_topic],
        )

        assert node.node_id == custom_node_id
        assert node.name == "custom_node"
        assert node.type == "CustomNode"
        assert node.tool is mock_tool
        assert node.oi_span_type == OpenInferenceSpanKindValues.AGENT
        assert len(node.subscribed_expressions) == 1
        assert len(node.publish_to) == 1

    def test_node_base_default_id_generation(self):
        """Test that default node_id is generated automatically."""
        node1 = ConcreteNodeBase(name="node1")
        node2 = ConcreteNodeBase(name="node2")

        assert node1.node_id != node2.node_id
        assert len(node1.node_id) > 0
        assert len(node2.node_id) > 0

    def test_node_base_default_values(self):
        """Test NodeBase default field values."""
        node = ConcreteNodeBase()

        assert node.name == "Node"
        assert node.type == "Node"
        assert node.tool is None
        assert node.oi_span_type == OpenInferenceSpanKindValues.CHAIN
        assert node.subscribed_expressions == []
        assert node.publish_to == []

    # Test Command Property
    def test_command_property_getter(self, basic_node_base: ConcreteNodeBase):
        """Test the command property getter."""
        # Initially should be None
        assert basic_node_base.command is None
        assert basic_node_base._command is None

    def test_command_property_setter(
        self, basic_node_base: ConcreteNodeBase, mock_tool: MockTool
    ):
        """Test the command property setter."""
        command = Command(tool=mock_tool)
        basic_node_base.command = command

        assert basic_node_base._command is command
        assert basic_node_base.command is command

    def test_command_property_round_trip(
        self, basic_node_base: ConcreteNodeBase, mock_tool: MockTool
    ):
        """Test setting and getting the command property."""
        command = Command(tool=mock_tool)

        # Set command
        basic_node_base.command = command

        # Get command
        retrieved_command = basic_node_base.command

        assert retrieved_command is command
        assert basic_node_base._command is command

    # Test Abstract Methods
    def test_concrete_invoke_method(
        self,
        basic_node_base: ConcreteNodeBase,
        invoke_context: InvokeContext,
        sample_consumed_events: List[ConsumeFromTopicEvent],
    ):
        """Test that the concrete implementation of invoke method works."""
        result = basic_node_base.invoke(invoke_context, sample_consumed_events)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].content == "Concrete node response"

    @pytest.mark.asyncio
    async def test_concrete_a_invoke_method(
        self,
        basic_node_base: ConcreteNodeBase,
        invoke_context: InvokeContext,
        sample_consumed_events: List[ConsumeFromTopicEvent],
    ):
        """Test that the concrete implementation of a_invoke method works."""
        messages = []
        async for message_batch in basic_node_base.a_invoke(
            invoke_context, sample_consumed_events
        ):
            messages.extend(message_batch)

        assert len(messages) == 1
        assert messages[0].content == "Concrete async node response"

    def test_abstract_invoke_not_implemented_in_base_class(
        self,
        invoke_context: InvokeContext,
        sample_consumed_events: List[ConsumeFromTopicEvent],
    ):
        """Test that NodeBase raises NotImplementedError for invoke method."""
        base_node = NodeBase(name="abstract_node")

        with pytest.raises(
            NotImplementedError, match="Subclasses must implement this method"
        ):
            base_node.invoke(invoke_context, sample_consumed_events)

    @pytest.mark.asyncio
    async def test_abstract_a_invoke_not_implemented_in_base_class(
        self,
        invoke_context: InvokeContext,
        sample_consumed_events: List[ConsumeFromTopicEvent],
    ):
        """Test that NodeBase raises NotImplementedError for a_invoke method."""
        base_node = NodeBase(name="abstract_node")

        with pytest.raises(
            NotImplementedError, match="Subclasses must implement this method"
        ):
            async for _ in base_node.a_invoke(invoke_context, sample_consumed_events):
                pass

    # Test Model Configuration
    def test_model_config_arbitrary_types_allowed(self, mock_tool: MockTool):
        """Test that arbitrary types are allowed in the model configuration."""
        # This should not raise a validation error
        node = ConcreteNodeBase(name="test_node", tool=mock_tool)
        assert node.tool is mock_tool

    def test_private_attributes_initialization(self, basic_node_base: ConcreteNodeBase):
        """Test that private attributes are initialized correctly."""
        assert hasattr(basic_node_base, "_subscribed_topics")
        assert hasattr(basic_node_base, "_command")
        assert basic_node_base._subscribed_topics == {}
        assert basic_node_base._command is None

    # Test Field Validation
    def test_subscribed_expressions_field_validation(self, mock_topic: MockTopic):
        """Test that subscribed_expressions field accepts valid SubExpr objects."""
        topic_expr = TopicExpr(topic=mock_topic)
        node = ConcreteNodeBase(
            name="test_node",
            subscribed_expressions=[topic_expr],
        )

        assert len(node.subscribed_expressions) == 1
        assert isinstance(node.subscribed_expressions[0], SubExpr)

    def test_publish_to_field_validation(self, mock_topic: MockTopic):
        """Test that publish_to field accepts valid TopicBase objects."""
        node = ConcreteNodeBase(
            name="test_node",
            publish_to=[mock_topic],
        )

        assert len(node.publish_to) == 1
        assert isinstance(node.publish_to[0], TopicBase)

    def test_tool_field_validation(self, mock_tool: MockTool):
        """Test that tool field accepts valid Tool objects."""
        node = ConcreteNodeBase(
            name="test_node",
            tool=mock_tool,
        )

        assert node.tool is mock_tool
        assert isinstance(node.tool, Tool)

    def test_oi_span_type_field_validation(self):
        """Test that oi_span_type field accepts valid OpenInferenceSpanKindValues."""
        node = ConcreteNodeBase(
            name="test_node",
            oi_span_type=OpenInferenceSpanKindValues.AGENT,
        )

        assert node.oi_span_type == OpenInferenceSpanKindValues.AGENT

    # Test Type Validation Errors
    def test_invalid_tool_type_raises_error(self):
        """Test that invalid tool type raises validation error."""
        with pytest.raises(Exception):  # Pydantic validation error
            ConcreteNodeBase(name="test_node", tool="invalid_tool")

    def test_invalid_subscribed_expressions_type_raises_error(self):
        """Test that invalid subscribed_expressions type raises validation error."""
        with pytest.raises(Exception):  # Pydantic validation error
            ConcreteNodeBase(
                name="test_node", subscribed_expressions=["invalid_expression"]
            )

    def test_invalid_publish_to_type_raises_error(self):
        """Test that invalid publish_to type raises validation error."""
        with pytest.raises(Exception):  # Pydantic validation error
            ConcreteNodeBase(name="test_node", publish_to=["invalid_topic"])

    def test_invalid_oi_span_type_raises_error(self):
        """Test that invalid oi_span_type raises validation error."""
        with pytest.raises(Exception):  # Pydantic validation error
            ConcreteNodeBase(name="test_node", oi_span_type="invalid_span_type")

    # Test Default Values
    def test_default_name_value(self):
        """Test that default name is 'Node'."""
        node = ConcreteNodeBase()
        assert node.name == "Node"

    def test_default_type_value(self):
        """Test that default type is 'Node'."""
        node = ConcreteNodeBase()
        assert node.type == "Node"

    def test_default_tool_value(self):
        """Test that default tool is None."""
        node = ConcreteNodeBase()
        assert node.tool is None

    def test_default_oi_span_type_value(self):
        """Test that default oi_span_type is CHAIN."""
        node = ConcreteNodeBase()
        assert node.oi_span_type == OpenInferenceSpanKindValues.CHAIN

    def test_default_subscribed_expressions_value(self):
        """Test that default subscribed_expressions is empty list."""
        node = ConcreteNodeBase()
        assert node.subscribed_expressions == []

    def test_default_publish_to_value(self):
        """Test that default publish_to is empty list."""
        node = ConcreteNodeBase()
        assert node.publish_to == []

    # Test List Field Mutability
    def test_list_fields_are_mutable(self, mock_topic: MockTopic):
        """Test that list fields can be modified after creation."""
        node = ConcreteNodeBase(name="test_node")

        # Initially empty
        assert len(node.subscribed_expressions) == 0
        assert len(node.publish_to) == 0

        # Add items
        topic_expr = TopicExpr(topic=mock_topic)
        node.subscribed_expressions.append(topic_expr)
        node.publish_to.append(mock_topic)

        # Verify changes
        assert len(node.subscribed_expressions) == 1
        assert len(node.publish_to) == 1

    def test_field_assignment_after_creation(self, mock_tool: MockTool):
        """Test that fields can be reassigned after creation."""
        node = ConcreteNodeBase(name="test_node")

        # Initially None
        assert node.tool is None

        # Assign tool
        node.tool = mock_tool

        # Verify assignment
        assert node.tool is mock_tool

    # Test Pydantic Model Features
    def test_model_dump(self, mock_tool: MockTool, mock_topic: MockTopic):
        """Test that model_dump works correctly."""
        topic_expr = TopicExpr(topic=mock_topic)
        node = ConcreteNodeBase(
            name="test_node",
            tool=mock_tool,
            subscribed_expressions=[topic_expr],
            publish_to=[mock_topic],
        )

        dumped = node.model_dump()

        assert isinstance(dumped, dict)
        assert dumped["name"] == "test_node"
        assert "node_id" in dumped
        assert "tool" in dumped
        assert "subscribed_expressions" in dumped
        assert "publish_to" in dumped

    def test_model_equality(self):
        """Test that model equality works correctly."""
        node1 = ConcreteNodeBase(name="test_node", node_id="same_id")
        node2 = ConcreteNodeBase(name="test_node", node_id="same_id")
        node3 = ConcreteNodeBase(name="different_node", node_id="same_id")

        # Same content should be equal
        assert node1 == node2

        # Different content should not be equal
        assert node1 != node3

    def test_private_attributes_not_in_model_dump(self):
        """Test that private attributes are not included in model_dump."""
        node = ConcreteNodeBase(name="test_node")
        dumped = node.model_dump()

        assert "_subscribed_topics" not in dumped
        assert "_command" not in dumped

    # Test Inheritance
    def test_inheritance_from_base_model(self):
        """Test that NodeBase properly inherits from BaseModel."""
        from pydantic import BaseModel

        assert issubclass(NodeBase, BaseModel)
        node = ConcreteNodeBase(name="test_node")
        assert isinstance(node, BaseModel)

    def test_subclass_behavior(self):
        """Test that subclasses work correctly."""

        class CustomNodeBase(NodeBase):
            custom_field: str = "default"

            def invoke(self, invoke_context, node_input):
                return [
                    Message(role="assistant", content=f"Custom: {self.custom_field}")
                ]

            async def a_invoke(self, invoke_context, node_input):
                yield [
                    Message(
                        role="assistant", content=f"Custom async: {self.custom_field}"
                    )
                ]

        node = CustomNodeBase(name="custom_node", custom_field="test_value")
        assert node.custom_field == "test_value"
        assert node.name == "custom_node"

    # Test Complex Scenarios
    def test_complex_node_configuration(self, mock_tool: MockTool):
        """Test a complex NodeBase configuration."""
        # Create multiple topics
        topic1 = MockTopic(name="input_topic")
        topic2 = MockTopic(name="output_topic")
        topic3 = MockTopic(name="control_topic")

        # Create expressions
        expr1 = TopicExpr(topic=topic1)
        expr2 = TopicExpr(topic=topic3)

        # Create complex node
        node = ConcreteNodeBase(
            name="complex_node",
            type="ComplexNode",
            tool=mock_tool,
            oi_span_type=OpenInferenceSpanKindValues.AGENT,
            subscribed_expressions=[expr1, expr2],
            publish_to=[topic2, topic3],
        )

        # Verify all configurations
        assert node.name == "complex_node"
        assert node.type == "ComplexNode"
        assert node.tool is mock_tool
        assert node.oi_span_type == OpenInferenceSpanKindValues.AGENT
        assert len(node.subscribed_expressions) == 2
        assert len(node.publish_to) == 2

        # Verify types
        assert all(isinstance(expr, SubExpr) for expr in node.subscribed_expressions)
        assert all(isinstance(topic, TopicBase) for topic in node.publish_to)

    # Test Edge Cases
    def test_empty_string_name(self):
        """Test NodeBase with empty string name."""
        node = ConcreteNodeBase(name="")
        assert node.name == ""

    def test_empty_string_type(self):
        """Test NodeBase with empty string type."""
        node = ConcreteNodeBase(type="")
        assert node.type == ""

    def test_none_values_for_optional_fields(self):
        """Test that None values are accepted for optional fields."""
        node = ConcreteNodeBase(
            name="test_node",
            tool=None,
        )

        assert node.tool is None

    def test_large_lists_for_collection_fields(self, mock_topic: MockTopic):
        """Test NodeBase with large lists for collection fields."""
        # Create multiple topics and expressions
        topics = [MockTopic(name=f"topic_{i}") for i in range(100)]
        expressions = [TopicExpr(topic=topic) for topic in topics[:50]]

        node = ConcreteNodeBase(
            name="test_node",
            subscribed_expressions=expressions,
            publish_to=topics,
        )

        assert len(node.subscribed_expressions) == 50
        assert len(node.publish_to) == 100


class TestNodeBaseBuilder:
    """Test suite for the NodeBaseBuilder class."""

    @pytest.fixture
    def mock_tool(self) -> MockTool:
        """Fixture providing a mock Tool."""
        return MockTool(name="builder_test_tool")

    @pytest.fixture
    def mock_topic(self) -> MockTopic:
        """Fixture providing a mock Topic."""
        return MockTopic(name="builder_test_topic")

    @pytest.fixture
    def builder(self) -> NodeBaseBuilder:
        """Fixture providing a NodeBaseBuilder instance."""
        return NodeBaseBuilder(ConcreteNodeBase)

    # Test Builder Methods
    def test_builder_name_method(self, builder: NodeBaseBuilder):
        """Test the name() builder method."""
        result = builder.name("test_node_name")

        assert result is builder  # Should return self for chaining
        assert "name" in builder.kwargs
        assert builder.kwargs["name"] == "test_node_name"

    def test_builder_type_method(self, builder: NodeBaseBuilder):
        """Test the type() builder method."""
        result = builder.type("CustomNodeType")

        assert result is builder
        assert "type" in builder.kwargs
        assert builder.kwargs["type"] == "CustomNodeType"

    def test_builder_oi_span_type_method(self, builder: NodeBaseBuilder):
        """Test the oi_span_type() builder method."""
        result = builder.oi_span_type(OpenInferenceSpanKindValues.AGENT)

        assert result is builder
        assert "oi_span_type" in builder.kwargs
        assert builder.kwargs["oi_span_type"] == OpenInferenceSpanKindValues.AGENT

    def test_builder_tool_method(self, builder: NodeBaseBuilder, mock_tool: MockTool):
        """Test the tool() builder method."""
        result = builder.tool(mock_tool)

        assert result is builder
        assert "tool" in builder.kwargs
        assert builder.kwargs["tool"] is mock_tool

    def test_builder_subscribe_method_with_topic(
        self, builder: NodeBaseBuilder, mock_topic: MockTopic
    ):
        """Test the subscribe() builder method with TopicBase."""
        result = builder.subscribe(mock_topic)

        assert result is builder
        assert "subscribed_expressions" in builder.kwargs
        assert len(builder.kwargs["subscribed_expressions"]) == 1

        expr = builder.kwargs["subscribed_expressions"][0]
        assert isinstance(expr, TopicExpr)
        assert expr.topic is mock_topic

    def test_builder_subscribe_method_with_subexpr(
        self, builder: NodeBaseBuilder, mock_topic: MockTopic
    ):
        """Test the subscribe() builder method with SubExpr."""
        topic_expr = TopicExpr(topic=mock_topic)
        result = builder.subscribe(topic_expr)

        assert result is builder
        assert "subscribed_expressions" in builder.kwargs
        assert len(builder.kwargs["subscribed_expressions"]) == 1
        assert builder.kwargs["subscribed_expressions"][0] is topic_expr

    def test_builder_subscribe_method_invalid_type(self, builder: NodeBaseBuilder):
        """Test the subscribe() builder method with invalid type."""
        with pytest.raises(ValueError, match="Expected a Topic or SubExpr"):
            builder.subscribe("invalid_subscription")

    def test_builder_subscribe_method_multiple_calls(
        self, builder: NodeBaseBuilder, mock_topic: MockTopic
    ):
        """Test multiple calls to subscribe() method."""
        topic1 = MockTopic(name="topic1")
        topic2 = MockTopic(name="topic2")

        builder.subscribe(topic1).subscribe(topic2)

        assert len(builder.kwargs["subscribed_expressions"]) == 2

    def test_builder_publish_to_method(
        self, builder: NodeBaseBuilder, mock_topic: MockTopic
    ):
        """Test the publish_to() builder method."""
        result = builder.publish_to(mock_topic)

        assert result is builder
        assert "publish_to" in builder.kwargs
        assert len(builder.kwargs["publish_to"]) == 1
        assert builder.kwargs["publish_to"][0] is mock_topic

    def test_builder_publish_to_method_multiple_calls(self, builder: NodeBaseBuilder):
        """Test multiple calls to publish_to() method."""
        topic1 = MockTopic(name="topic1")
        topic2 = MockTopic(name="topic2")

        builder.publish_to(topic1).publish_to(topic2)

        assert len(builder.kwargs["publish_to"]) == 2
        assert builder.kwargs["publish_to"][0] is topic1
        assert builder.kwargs["publish_to"][1] is topic2

    # Test Builder Chaining
    def test_builder_method_chaining(self, mock_tool: MockTool, mock_topic: MockTopic):
        """Test that all builder methods can be chained together."""
        builder = NodeBaseBuilder(ConcreteNodeBase)

        result = (
            builder.name("chained_node")
            .type("ChainedNode")
            .oi_span_type(OpenInferenceSpanKindValues.AGENT)
            .tool(mock_tool)
            .subscribe(mock_topic)
            .publish_to(mock_topic)
        )

        assert result is builder
        assert builder.kwargs["name"] == "chained_node"
        assert builder.kwargs["type"] == "ChainedNode"
        assert builder.kwargs["oi_span_type"] == OpenInferenceSpanKindValues.AGENT
        assert builder.kwargs["tool"] is mock_tool
        assert len(builder.kwargs["subscribed_expressions"]) == 1
        assert len(builder.kwargs["publish_to"]) == 1

    # Test Builder Build Method
    def test_builder_build_basic(self, builder: NodeBaseBuilder):
        """Test building a basic node."""
        node = builder.name("built_node").build()

        assert isinstance(node, ConcreteNodeBase)
        assert node.name == "built_node"

    def test_builder_build_with_all_options(
        self, mock_tool: MockTool, mock_topic: MockTopic
    ):
        """Test building a node with all options set."""
        builder = NodeBaseBuilder(ConcreteNodeBase)

        node = (
            builder.name("full_node")
            .type("FullNode")
            .oi_span_type(OpenInferenceSpanKindValues.AGENT)
            .tool(mock_tool)
            .subscribe(mock_topic)
            .publish_to(mock_topic)
            .build()
        )

        assert isinstance(node, ConcreteNodeBase)
        assert node.name == "full_node"
        assert node.type == "FullNode"
        assert node.oi_span_type == OpenInferenceSpanKindValues.AGENT
        assert node.tool is mock_tool
        assert len(node.subscribed_expressions) == 1
        assert len(node.publish_to) == 1

    def test_builder_build_multiple_times(self, builder: NodeBaseBuilder):
        """Test that builder can build multiple instances."""
        builder.name("multi_node")

        node1 = builder.build()
        node2 = builder.build()

        assert isinstance(node1, ConcreteNodeBase)
        assert isinstance(node2, ConcreteNodeBase)
        assert node1.name == "multi_node"
        assert node2.name == "multi_node"
        assert node1 is not node2  # Should be different instances

    def test_builder_build_with_empty_kwargs(self):
        """Test building with no kwargs set."""
        builder = NodeBaseBuilder(ConcreteNodeBase)
        node = builder.build()

        assert isinstance(node, ConcreteNodeBase)
        # Should use default values
        assert node.name == "Node"
        assert node.type == "Node"

    # Test Builder State Management
    def test_builder_kwargs_persistence(self, builder: NodeBaseBuilder):
        """Test that builder kwargs persist across method calls."""
        builder.name("persistent_node")

        # Add more kwargs
        builder.type("PersistentNode")

        # Original kwargs should still be there
        assert builder.kwargs["name"] == "persistent_node"
        assert builder.kwargs["type"] == "PersistentNode"

    def test_builder_kwargs_modification(self, builder: NodeBaseBuilder):
        """Test that builder kwargs can be modified."""
        # Set initial value
        builder.name("initial_name")
        assert builder.kwargs["name"] == "initial_name"

        # Change value
        builder.name("changed_name")
        assert builder.kwargs["name"] == "changed_name"

    # Test Builder with Collections
    def test_builder_subscribe_creates_list_if_not_exists(
        self, builder: NodeBaseBuilder, mock_topic: MockTopic
    ):
        """Test that subscribe() creates subscribed_expressions list if it doesn't exist."""
        assert "subscribed_expressions" not in builder.kwargs

        builder.subscribe(mock_topic)

        assert "subscribed_expressions" in builder.kwargs
        assert isinstance(builder.kwargs["subscribed_expressions"], list)

    def test_builder_publish_to_creates_list_if_not_exists(
        self, builder: NodeBaseBuilder, mock_topic: MockTopic
    ):
        """Test that publish_to() creates publish_to list if it doesn't exist."""
        assert "publish_to" not in builder.kwargs

        builder.publish_to(mock_topic)

        assert "publish_to" in builder.kwargs
        assert isinstance(builder.kwargs["publish_to"], list)

    def test_builder_subscribe_appends_to_existing_list(self, builder: NodeBaseBuilder):
        """Test that subscribe() appends to existing subscribed_expressions list."""
        topic1 = MockTopic(name="topic1")
        topic2 = MockTopic(name="topic2")

        # First subscription
        builder.subscribe(topic1)
        assert len(builder.kwargs["subscribed_expressions"]) == 1

        # Second subscription
        builder.subscribe(topic2)
        assert len(builder.kwargs["subscribed_expressions"]) == 2

    def test_builder_publish_to_appends_to_existing_list(
        self, builder: NodeBaseBuilder
    ):
        """Test that publish_to() appends to existing publish_to list."""
        topic1 = MockTopic(name="topic1")
        topic2 = MockTopic(name="topic2")

        # First topic
        builder.publish_to(topic1)
        assert len(builder.kwargs["publish_to"]) == 1

        # Second topic
        builder.publish_to(topic2)
        assert len(builder.kwargs["publish_to"]) == 2

    # Test Builder Return Types
    def test_builder_methods_return_self(
        self, builder: NodeBaseBuilder, mock_tool: MockTool, mock_topic: MockTopic
    ):
        """Test that all builder methods return self for chaining."""
        assert builder.name("test") is builder
        assert builder.type("test") is builder
        assert builder.oi_span_type(OpenInferenceSpanKindValues.AGENT) is builder
        assert builder.tool(mock_tool) is builder
        assert builder.subscribe(mock_topic) is builder
        assert builder.publish_to(mock_topic) is builder

    # Test Builder Edge Cases
    def test_builder_with_none_values(self, builder: NodeBaseBuilder):
        """Test builder with None values."""
        # These should be acceptable for optional fields
        result = builder.tool(None)
        assert result is builder
        assert builder.kwargs["tool"] is None

    def test_builder_with_empty_strings(self, builder: NodeBaseBuilder):
        """Test builder with empty string values."""
        builder.name("").type("")

        assert builder.kwargs["name"] == ""
        assert builder.kwargs["type"] == ""

    def test_builder_subscribe_with_mixed_types(
        self, builder: NodeBaseBuilder, mock_topic: MockTopic
    ):
        """Test builder subscribe with mixed TopicBase and SubExpr types."""
        topic_expr = TopicExpr(topic=mock_topic)
        another_topic = MockTopic(name="another_topic")

        builder.subscribe(mock_topic).subscribe(topic_expr).subscribe(another_topic)

        assert len(builder.kwargs["subscribed_expressions"]) == 3
        # All should be SubExpr instances
        assert all(
            isinstance(expr, SubExpr)
            for expr in builder.kwargs["subscribed_expressions"]
        )

    # Test Builder Complex Scenarios
    def test_builder_inheritance_compatibility(self):
        """Test that builder works with inheritance."""

        class CustomNode(ConcreteNodeBase):
            custom_field: str = "default"

        builder = NodeBaseBuilder(CustomNode)
        node = builder.name("custom_node").build()

        assert isinstance(node, CustomNode)
        assert isinstance(node, ConcreteNodeBase)
        assert node.name == "custom_node"
        assert node.custom_field == "default"
