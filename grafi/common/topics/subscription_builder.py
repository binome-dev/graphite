from typing import Optional

from pydantic import BaseModel
from pydantic import ConfigDict

from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_expression import CombinedExpr
from grafi.common.topics.topic_expression import LogicalOp
from grafi.common.topics.topic_expression import SubExpr
from grafi.common.topics.topic_expression import TopicExpr


class SubscriptionBuilder(BaseModel):
    """
    Builder for the subscription DSL. Allows chaining:
        .subscribed_to(topicA).and_().subscribed_to(topicB).or_()...
        .build()
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    root_expr: Optional[SubExpr] = None
    pending_op: Optional[LogicalOp] = None

    def subscribed_to(self, topic: TopicBase) -> "SubscriptionBuilder":
        if not isinstance(topic, TopicBase):
            raise ValueError("subscribed_to(...) must receive a Topic object.")
        new_expr = TopicExpr(topic=topic)

        if self.root_expr is None:
            self.root_expr = new_expr
        else:
            if not self.pending_op:
                raise ValueError("No operator set. Did you forget .and_() or .or_()?")
            self.root_expr = CombinedExpr(
                op=self.pending_op, left=self.root_expr, right=new_expr
            )
            self.pending_op = None

        return self

    def and_(self) -> "SubscriptionBuilder":
        self.pending_op = LogicalOp.AND
        return self

    def or_(self) -> "SubscriptionBuilder":
        self.pending_op = LogicalOp.OR
        return self

    def build(self) -> SubExpr:
        """
        Attach the final expression (root_expr) to the Node's subscribed_expressions,
        then return the Node.Builder for further chaining.
        """
        if self.root_expr:
            return self.root_expr
