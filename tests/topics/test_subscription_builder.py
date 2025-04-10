import pytest

from grafi.common.topics.subscription_builder import (
    SubscriptionBuilder,  # Replace `your_module` with the actual module
)
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_expression import CombinedExpr
from grafi.common.topics.topic_expression import LogicalOp
from grafi.common.topics.topic_expression import TopicExpr


@pytest.fixture
def mock_topics():
    """Creates mock TopicBase instances for testing."""
    topic1 = TopicBase(name="topic_1")
    topic2 = TopicBase(name="topic_2")
    topic3 = TopicBase(name="topic_3")

    return topic1, topic2, topic3


def test_subscribed_to_single_topic(mock_topics):
    """Test subscribing to a single topic."""
    builder = SubscriptionBuilder()
    expr = builder.subscribed_to(mock_topics[0]).build()

    assert isinstance(expr, TopicExpr)
    assert expr.topic.name == "topic_1"


def test_subscribed_to_with_and(mock_topics):
    """Test combining two topics with AND."""
    builder = SubscriptionBuilder()
    expr = (
        builder.subscribed_to(mock_topics[0])
        .and_()
        .subscribed_to(mock_topics[1])
        .build()
    )

    assert isinstance(expr, CombinedExpr)
    assert expr.op == LogicalOp.AND
    assert isinstance(expr.left, TopicExpr)
    assert isinstance(expr.right, TopicExpr)
    assert expr.left.topic.name == "topic_1"
    assert expr.right.topic.name == "topic_2"


def test_subscribed_to_with_or(mock_topics):
    """Test combining two topics with OR."""
    builder = SubscriptionBuilder()
    expr = (
        builder.subscribed_to(mock_topics[0])
        .or_()
        .subscribed_to(mock_topics[1])
        .build()
    )

    assert isinstance(expr, CombinedExpr)
    assert expr.op == LogicalOp.OR
    assert isinstance(expr.left, TopicExpr)
    assert isinstance(expr.right, TopicExpr)
    assert expr.left.topic.name == "topic_1"
    assert expr.right.topic.name == "topic_2"


def test_chained_expressions(mock_topics):
    """Test chaining multiple subscriptions with AND and OR."""
    builder = SubscriptionBuilder()
    expr = (
        builder.subscribed_to(mock_topics[0])
        .and_()
        .subscribed_to(mock_topics[1])
        .or_()
        .subscribed_to(mock_topics[2])
        .build()
    )

    assert isinstance(expr, CombinedExpr)
    assert expr.op == LogicalOp.OR
    assert isinstance(expr.left, CombinedExpr)  # (topic_1 AND topic_2)
    assert expr.left.op == LogicalOp.AND
    assert expr.left.left.topic.name == "topic_1"
    assert expr.left.right.topic.name == "topic_2"
    assert expr.right.topic.name == "topic_3"


def test_missing_operator_raises_error(mock_topics):
    """Ensure a ValueError is raised if an operator is missing between expressions."""
    builder = SubscriptionBuilder().subscribed_to(mock_topics[0])

    with pytest.raises(
        ValueError, match=r"No operator set\. Did you forget \.and_\(\) or \.or_\(\)\?"
    ):
        builder.subscribed_to(
            mock_topics[1]
        )  # No AND/OR before the second subscription


def test_invalid_subscription_raises_error():
    """Ensure a ValueError is raised if a non-TopicBase object is passed."""
    builder = SubscriptionBuilder()

    with pytest.raises(
        ValueError, match="subscribed_to\\(\\.\\.\\.\\) must receive a Topic object."
    ):
        builder.subscribed_to("invalid_topic")  # String instead of TopicBase


def test_build_without_subscription_returns_none():
    """Ensure build() without any subscriptions returns None."""
    builder = SubscriptionBuilder()
    assert builder.root_expr is None
