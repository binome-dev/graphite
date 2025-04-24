from enum import Enum
from typing import Any
from typing import List

from pydantic import BaseModel

from grafi.common.topics.topic_base import TopicBase


class LogicalOp(Enum):
    AND = "AND"
    OR = "OR"


class SubExpr(BaseModel):
    """Base class for subscription expressions."""

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


class TopicExpr(SubExpr):
    """Represents a single subscribed Topic by name."""

    topic: TopicBase

    def to_dict(self) -> dict[str, Any]:
        return {"topic": self.topic.to_dict()}


class CombinedExpr(SubExpr):
    """Represents (left_expr op right_expr)."""

    op: LogicalOp
    left: SubExpr
    right: SubExpr

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op.value,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }


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
