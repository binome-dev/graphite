from typing import List

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.command import Command
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_expression import TopicExpr
from grafi.nodes.node import Node
from grafi.nodes.node import NodeBuilder


# --- Dummy Implementations for Testing ---


class DummyNode(Node):
    """
    A concrete implementation of Node for testing.
    Implements the abstract methods with dummy behavior.
    """

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.CHAIN
    name: str = "LLMNode"
    type: str = "LLMNode"
    command: Command = Field(default=None)
    function_specs: FunctionSpecs = Field(default=[])

    def invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        return [Message(role="assistant", content="sync dummy")]

    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        yield [Message(role="assistant", content="async dummy")]

    def get_command_input(self, node_input: List[ConsumeFromTopicEvent]) -> Messages:
        return [Message(role="assistant", content="command dummy")]


class DummyNodeBuilder(NodeBuilder):
    """
    Builder for DummyNode that implements the required _init_node() method.
    """

    def _init_node(self) -> DummyNode:
        # Provide default values for required fields.
        return DummyNode()


class DummyTopic(Topic):
    """
    A dummy topic for testing purposes.
    Overrides can_consume() to return a preset value and provides a simple to_dict().
    """

    def __init__(self, name: str, can_consume_value: bool = True):
        super().__init__(name=name)
        self._can_consume_value = can_consume_value

    def can_consume(self, consumer_name: str) -> bool:
        return self._can_consume_value

    def to_dict(self) -> dict:
        return {"name": self.name}


# --- Unit Tests ---


def test_node_builder_creates_node():
    builder = NodeBuilder(Node)
    node = builder.name("test_node").type("test_type").build()
    assert node.name == "test_node"
    assert node.type == "test_type"
    # Without subscriptions, _subscribed_topics should be empty.
    assert node._subscribed_topics == {}


def test_subscribe_adds_topic_expr():
    builder = NodeBuilder(Node)
    dummy_topic = DummyTopic(name="dummy_topic")
    node = builder.name("test_node").type("test_type").subscribe(dummy_topic).build()
    # Check that a TopicExpr is added.
    assert len(node.subscribed_expressions) == 1
    expr = node.subscribed_expressions[0]
    assert isinstance(expr, TopicExpr)
    # Builder.build() should compute _subscribed_topics based on the subscription expression.
    assert "dummy_topic" in node._subscribed_topics
    assert node._subscribed_topics["dummy_topic"] == dummy_topic


def test_publish_to_adds_topic():
    builder = NodeBuilder(Node)
    dummy_topic = DummyTopic(name="publish_topic")
    node = builder.name("test_node").type("test_type").publish_to(dummy_topic).build()
    assert len(node.publish_to) == 1
    assert node.publish_to[0].name == "publish_topic"


def test_can_invoke_no_subscription():
    builder = NodeBuilder(Node)
    node = builder.name("test_node").type("test_type").build()
    # With no subscriptions, can_invoke() should return True.
    assert node.can_invoke() is True


def test_can_invoke_with_subscription_true():
    builder = NodeBuilder(Node)
    # Create a dummy topic that reports new messages (can_consume returns True).
    dummy_topic = DummyTopic(name="sub_topic", can_consume_value=True)
    node = builder.name("test_node").type("test_type").subscribe(dummy_topic).build()
    # The subscribed expression evaluates to True because "sub_topic" is in topics with new messages.
    assert node.can_invoke() is True


def test_can_invoke_with_subscription_false():
    builder = NodeBuilder(Node)
    # Create a dummy topic that reports no new messages.
    dummy_topic = DummyTopic(name="sub_topic", can_consume_value=False)
    node = builder.name("test_node").type("test_type").subscribe(dummy_topic).build()
    # The subscribed expression evaluates to False, so can_invoke() should return False.
    assert node.can_invoke() is False


def test_to_dict_returns_correct_structure():
    builder = NodeBuilder(Node)
    dummy_topic = DummyTopic(name="dummy_topic")
    node = (
        builder.name("test_node")
        .type("test_type")
        .subscribe(dummy_topic)
        .publish_to(dummy_topic)
        .build()
    )

    # Optionally, set a dummy command with a to_dict() method.
    class DummyCommand:
        def to_dict(self):
            return {"dummy": "command"}

    node.command = DummyCommand()

    node_dict = node.to_dict()
    # Check that the returned dict includes the required keys.
    assert "node_id" in node_dict
    assert "subscribed_expressions" in node_dict
    assert "publish_to" in node_dict
    assert "command" in node_dict
    # subscribed_expressions and publish_to should be lists.
    assert isinstance(node_dict["subscribed_expressions"], list)
    assert isinstance(node_dict["publish_to"], list)
    # Check that the command's dict is as expected.
    assert node_dict["command"] == {"dummy": "command"}
