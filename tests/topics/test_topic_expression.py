import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError

from grafi.topics.expressions.topic_expression import CombinedExpr
from grafi.topics.expressions.topic_expression import LogicalOp
from grafi.topics.expressions.topic_expression import Subscription
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.expressions.topic_expression import evaluate_subscription
from grafi.topics.expressions.topic_expression import extract_topics
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_types import TopicType


@pytest.fixture
def mock_topics(monkeypatch) -> tuple[TopicBase, TopicBase, TopicBase]:
    """Creates mock TopicBase instances for testing."""
    topic1 = TopicBase(name="topic_1")
    topic2 = TopicBase(name="topic_2")
    topic3 = TopicBase(name="topic_3")

    return topic1, topic2, topic3


def _topics_context(*topics: TopicBase) -> dict:
    """The validation context a workflow loads its nodes' expressions in."""
    return {"topics": {topic.name: topic for topic in topics}}


def test_topic_expr_dump(mock_topics: tuple[TopicBase, TopicBase, TopicBase]):
    """Test serialization of TopicExpr."""
    topic_expr = TopicExpr(topic=mock_topics[0])

    # The topic is saved by its name in JSON
    assert topic_expr.model_dump(mode="json") == {"topic": "topic_1"}
    # and in full in a python-mode dump, which loads back on its own.
    data = topic_expr.model_dump()
    assert data == {
        "topic": {
            "class": TopicBase,
            "name": "topic_1",
            "type": TopicType.DEFAULT_TOPIC_TYPE,
        }
    }
    restored = TopicExpr.model_validate(data)
    assert type(restored.topic) is TopicBase
    assert restored.topic.name == "topic_1"
    # Among a workflow's topics, it is the one of its name.
    in_scope = TopicExpr.model_validate(data, context=_topics_context(*mock_topics))
    assert in_scope.topic is mock_topics[0]


def test_combined_expr_dump(mock_topics):
    """Test serialization of CombinedExpr."""
    left_expr = TopicExpr(topic=mock_topics[0])
    right_expr = TopicExpr(topic=mock_topics[1])
    combined_expr = CombinedExpr(op=LogicalOp.AND, left=left_expr, right=right_expr)

    result = combined_expr.model_dump(mode="json")

    # The topics are saved by their names
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


def test_topic_expr_model_validate(mock_topics):
    """Test deserialization of TopicExpr: the name resolves through the context."""
    data = {"topic": "topic_1"}

    expr = TopicExpr.model_validate(data, context=_topics_context(*mock_topics))

    assert isinstance(expr, TopicExpr)
    assert expr.topic is mock_topics[0]


def test_combined_expr_model_validate(mock_topics):
    """Test deserialization of CombinedExpr."""
    data = {
        "op": "AND",
        "left": {"topic": "topic_1"},
        "right": {"topic": "topic_2"},
    }

    expr = CombinedExpr.model_validate(data, context=_topics_context(*mock_topics))

    assert isinstance(expr, CombinedExpr)
    assert expr.op == LogicalOp.AND
    assert isinstance(expr.left, TopicExpr)
    assert isinstance(expr.right, TopicExpr)
    assert expr.left.topic is mock_topics[0]
    assert expr.right.topic is mock_topics[1]


def test_nested_combined_expr_model_validate(mock_topics):
    """Test deserialization of nested CombinedExpr."""
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

    expr = CombinedExpr.model_validate(data, context=_topics_context(*mock_topics))

    assert isinstance(expr, CombinedExpr)
    assert expr.op == LogicalOp.OR
    assert isinstance(expr.left, CombinedExpr)
    assert isinstance(expr.right, TopicExpr)
    assert expr.left.op == LogicalOp.AND
    assert expr.right.topic is mock_topics[2]


def test_subscription_type_picks_expression_kind(mock_topics):
    """The Subscription type loads a topic or a combined expression by shape."""
    adapter = TypeAdapter(Subscription)
    context = _topics_context(*mock_topics)

    single = adapter.validate_python({"topic": "topic_3"}, context=context)
    combined = adapter.validate_python(
        {"op": "OR", "left": {"topic": "topic_1"}, "right": {"topic": "topic_2"}},
        context=context,
    )

    assert isinstance(single, TopicExpr)
    assert single.topic is mock_topics[2]
    assert isinstance(combined, CombinedExpr)
    assert combined.op == LogicalOp.OR


@pytest.mark.parametrize(
    "data",
    [
        {"topic": "topic_1", "negate": True},
        {
            "op": "AND",
            "left": {"topic": "topic_1"},
            "right": {"topic": "topic_2"},
            "x": 1,
        },
        {
            "op": "OR",
            "left": {"topic": "topic_1"},
            "right": {"topic": "topic_2", "y": 0},
        },
    ],
    ids=["topic", "combined", "nested"],
)
def test_a_key_an_expression_does_not_have_is_refused(mock_topics, data):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TypeAdapter(Subscription).validate_python(
            data, context=_topics_context(*mock_topics)
        )


def test_unknown_topic_name_fails_loudly(mock_topics):
    """A name that is not one of the context's topics is an error, never None."""
    with pytest.raises(ValidationError, match="Unknown topic 'missing'"):
        TopicExpr.model_validate(
            {"topic": "missing"}, context=_topics_context(*mock_topics)
        )

    with pytest.raises(ValidationError, match="Unknown topic 'topic_2'"):
        CombinedExpr.model_validate(
            {"op": "AND", "left": {"topic": "topic_1"}, "right": {"topic": "topic_2"}},
            context=_topics_context(mock_topics[0]),
        )


def test_topic_name_without_context_fails(mock_topics):
    """Loading a topic name needs the topics, in the validation context."""
    with pytest.raises(ValidationError, match="Unknown topic 'topic_1'"):
        TopicExpr.model_validate({"topic": "topic_1"})


def test_topic_expr_roundtrip(mock_topics):
    """Test serialization and deserialization roundtrip for TopicExpr."""
    original = TopicExpr(topic=mock_topics[0])
    data = original.model_dump(mode="json")

    restored = TopicExpr.model_validate(data, context=_topics_context(mock_topics[0]))

    assert restored.topic is original.topic
    assert restored.model_dump(mode="json") == data


def test_combined_expr_roundtrip(mock_topics):
    """Test serialization and deserialization roundtrip for CombinedExpr."""
    left_expr = TopicExpr(topic=mock_topics[0])
    right_expr = TopicExpr(topic=mock_topics[1])
    original = CombinedExpr(op=LogicalOp.AND, left=left_expr, right=right_expr)

    data = original.model_dump(mode="json")

    restored = CombinedExpr.model_validate(
        data, context=_topics_context(mock_topics[0], mock_topics[1])
    )

    assert restored.op == original.op
    assert restored.left.topic is original.left.topic
    assert restored.right.topic is original.right.topic
    assert restored.model_dump(mode="json") == data
