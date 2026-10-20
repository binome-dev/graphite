from enum import Enum
from typing import Annotated
from typing import Any
from typing import List
from typing import Union

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Discriminator
from pydantic import Tag

from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_base import TopicRef


class LogicalOp(Enum):
    AND = "AND"
    OR = "OR"


class SubExpr(BaseModel):
    """Base class for subscription expressions."""

    # A key it does not have is refused, so a misspelt one is not ignored.
    model_config = ConfigDict(extra="forbid")


class TopicExpr(SubExpr):
    """A subscribed topic, saved by its name."""

    topic: TopicRef


class CombinedExpr(SubExpr):
    """Represents (left_expr op right_expr)."""

    op: LogicalOp
    left: "Subscription"
    right: "Subscription"


def _expression_kind(value: Any) -> str:
    if isinstance(value, SubExpr):
        return "topic" if isinstance(value, TopicExpr) else "combined"
    return "topic" if isinstance(value, dict) and "topic" in value else "combined"


# A subscription expression: a topic, saved as {"topic": name}, or two
# expressions combined, saved as {"op": "AND", "left": ..., "right": ...}.
Subscription = Annotated[
    Union[Annotated[TopicExpr, Tag("topic")], Annotated[CombinedExpr, Tag("combined")]],
    Discriminator(_expression_kind),
]

CombinedExpr.model_rebuild()


def evaluate_subscription(expr: SubExpr, topics_with_new_msgs: List[str]) -> bool:
    """
    Evaluate the subscription expression given the list of topic names
    that have new (unread) messages.
    """
    if isinstance(expr, TopicExpr):
        return expr.topic.name in topics_with_new_msgs
    elif isinstance(expr, CombinedExpr):
        left_val = evaluate_subscription(expr.left, topics_with_new_msgs)
        right_val = evaluate_subscription(expr.right, topics_with_new_msgs)
        if expr.op == LogicalOp.AND:
            return left_val and right_val
        else:  # expr.op == LogicalOp.OR
            return left_val or right_val
    else:
        return False


def extract_topics(expr: SubExpr) -> List[TopicBase]:
    """Recursively collect topic names from a DSL expression tree."""
    if isinstance(expr, TopicExpr):
        return [expr.topic]
    elif isinstance(expr, CombinedExpr):
        return extract_topics(expr.left) + extract_topics(expr.right)
    return []
