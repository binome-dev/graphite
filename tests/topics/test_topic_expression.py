import pytest

from grafi.topics.expressions.topic_expression import (
    CombinedExpr,  # Replace `your_module` with the actual module
)
from grafi.topics.expressions.topic_expression import LogicalOp
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.expressions.topic_expression import evaluate_subscription
from grafi.topics.expressions.topic_expression import extract_topics
from grafi.topics.topic_base import TopicBase


@pytest.fixture
def mock_topics(monkeypatch) -> tuple[TopicBase, TopicBase, TopicBase]:
    """Creates mock TopicBase instances for testing."""
    topic1 = TopicBase(name="topic_1")
    topic2 = TopicBase(name="topic_2")
    topic3 = TopicBase(name="topic_3")

    return topic1, topic2, topic3


def test_topic_expr_to_dict(mock_topics: tuple[TopicBase, TopicBase, TopicBase]):
    """Test serialization of TopicExpr."""
    topic_expr = TopicExpr(topic=mock_topics[0])
    result = topic_expr.to_dict()

    # The to_dict() now returns just the topic name
    assert result == {"topic": "topic_1"}


def test_combined_expr_to_dict(mock_topics):
    """Test serialization of CombinedExpr."""
    left_expr = TopicExpr(topic=mock_topics[0])
    right_expr = TopicExpr(topic=mock_topics[1])
    combined_expr = CombinedExpr(op=LogicalOp.AND, left=left_expr, right=right_expr)

    result = combined_expr.to_dict()

    # The to_dict() now returns just the topic names
    assert result == {
        "op": "AND",
        "left": {"topic": "topic_1"},
        "right": {"topic": "topic_2"},
    }


def test_evaluate_subscription_single_topic(mock_topics):
    """Test evaluating a single TopicExpr."""
    topic_expr = TopicExpr(topic=mock_topics[0])

    assert evaluate_subscription(topic_expr, ["topic_1"]) is True
    assert evaluate_subscription(topic_expr, ["topic_2"]) is False  # Different topic


def test_evaluate_subscription_combined_expr(mock_topics):
    """Test evaluating a CombinedExpr with AND/OR."""
    expr1 = TopicExpr(topic=mock_topics[0])  # topic_1
    expr2 = TopicExpr(topic=mock_topics[1])  # topic_2
    expr3 = TopicExpr(topic=mock_topics[2])  # topic_3

    and_expr = CombinedExpr(op=LogicalOp.AND, left=expr1, right=expr2)
    or_expr = CombinedExpr(op=LogicalOp.OR, left=expr1, right=expr2)

    # Test AND: Both topics must be in the list
    assert evaluate_subscription(and_expr, ["topic_1", "topic_2"]) is True
    assert evaluate_subscription(and_expr, ["topic_1"]) is False
    assert evaluate_subscription(and_expr, ["topic_2"]) is False

    # Test OR: At least one topic must be in the list
    assert evaluate_subscription(or_expr, ["topic_1"]) is True
    assert evaluate_subscription(or_expr, ["topic_2"]) is True
    assert (
        evaluate_subscription(or_expr, ["topic_3"]) is False
    )  # Neither topic_1 nor topic_2

    # Complex case: (topic_1 AND topic_2) OR topic_3
    complex_expr = CombinedExpr(op=LogicalOp.OR, left=and_expr, right=expr3)
    assert evaluate_subscription(complex_expr, ["topic_1", "topic_2"]) is True
    assert evaluate_subscription(complex_expr, ["topic_3"]) is True
    assert (
        evaluate_subscription(complex_expr, ["topic_1"]) is False
    )  # Neither topic_2 nor topic_3


def test_extract_topics(mock_topics):
    """Test extracting topics from expressions."""
    expr1 = TopicExpr(topic=mock_topics[0])
    expr2 = TopicExpr(topic=mock_topics[1])
    expr3 = TopicExpr(topic=mock_topics[2])

    and_expr = CombinedExpr(op=LogicalOp.AND, left=expr1, right=expr2)
    or_expr = CombinedExpr(op=LogicalOp.OR, left=and_expr, right=expr3)

    topics = extract_topics(or_expr)
    assert topics == [
        mock_topics[0],
        mock_topics[1],
        mock_topics[2],
    ]  # Extract all topics


@pytest.mark.asyncio
async def test_topic_expr_from_dict(mock_topics):
    """Test deserialization of TopicExpr."""
    topics_dict = {
        "topic_1": mock_topics[0],
        "topic_2": mock_topics[1],
        "topic_3": mock_topics[2],
    }

    data = {"topic": "topic_1"}

    expr = await TopicExpr.from_dict(data, topics_dict)

    assert isinstance(expr, TopicExpr)
    assert expr.topic.name == "topic_1"


@pytest.mark.asyncio
async def test_combined_expr_from_dict(mock_topics):
    """Test deserialization of CombinedExpr."""
    topics_dict = {
        "topic_1": mock_topics[0],
        "topic_2": mock_topics[1],
        "topic_3": mock_topics[2],
    }

    data = {
        "op": "AND",
        "left": {"topic": "topic_1"},
        "right": {"topic": "topic_2"},
    }

    expr = await CombinedExpr.from_dict(data, topics_dict)

    assert isinstance(expr, CombinedExpr)
    assert expr.op == LogicalOp.AND
    assert isinstance(expr.left, TopicExpr)
    assert isinstance(expr.right, TopicExpr)
    assert expr.left.topic.name == "topic_1"
    assert expr.right.topic.name == "topic_2"


@pytest.mark.asyncio
async def test_nested_combined_expr_from_dict(mock_topics):
    """Test deserialization of nested CombinedExpr."""
    topics_dict = {
        "topic_1": mock_topics[0],
        "topic_2": mock_topics[1],
        "topic_3": mock_topics[2],
    }

    # (topic_1 AND topic_2) OR topic_3
    data = {
        "op": "OR",
        "left": {
            "op": "AND",
            "left": {"topic": "topic_1"},
            "right": {"topic": "topic_2"},
        },
        "right": {"topic": "topic_3"},
    }

    expr = await CombinedExpr.from_dict(data, topics_dict)

    assert isinstance(expr, CombinedExpr)
    assert expr.op == LogicalOp.OR
    assert isinstance(expr.left, CombinedExpr)
    assert isinstance(expr.right, TopicExpr)
    assert expr.left.op == LogicalOp.AND
    assert expr.right.topic.name == "topic_3"


@pytest.mark.asyncio
async def test_topic_expr_roundtrip(mock_topics):
    """Test serialization and deserialization roundtrip for TopicExpr."""
    topics_dict = {"topic_1": mock_topics[0]}

    original = TopicExpr(topic=mock_topics[0])
    data = original.to_dict()

    # to_dict() returns just the topic name, can use directly with from_dict
    restored = await TopicExpr.from_dict(data, topics_dict)

    assert restored.topic.name == original.topic.name


@pytest.mark.asyncio
async def test_combined_expr_roundtrip(mock_topics):
    """Test serialization and deserialization roundtrip for CombinedExpr."""
    topics_dict = {
        "topic_1": mock_topics[0],
        "topic_2": mock_topics[1],
    }

    left_expr = TopicExpr(topic=mock_topics[0])
    right_expr = TopicExpr(topic=mock_topics[1])
    original = CombinedExpr(op=LogicalOp.AND, left=left_expr, right=right_expr)

    data = original.to_dict()

    # to_dict() returns just the topic names, can use directly with from_dict
    restored = await CombinedExpr.from_dict(data, topics_dict)

    assert restored.op == original.op
    assert restored.left.topic.name == original.left.topic.name
    assert restored.right.topic.name == original.right.topic.name
