from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import TypeVar
from typing import Union

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import PrivateAttr

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.command import Command
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_expression import SubExpr
from grafi.common.topics.topic_expression import TopicExpr
from grafi.tools.tool import Tool


class NodeBase(BaseModel):
    """Abstract base class for nodes in a graph-based agent system."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    node_id: str = default_id
    name: str = Field(default="Node")
    type: str = Field(default="Node")
    tool: Optional[Tool] = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.CHAIN
    subscribed_expressions: List[SubExpr] = Field(default=[])
    publish_to: List[TopicBase] = Field(default=[])

    _subscribed_topics: Dict[str, TopicBase] = PrivateAttr(default={})
    _command: Optional[Command] = PrivateAttr(default=None)

    @property
    def command(self) -> Command:
        """Access the internal command (for backward compatibility)."""
        return self._command

    @command.setter
    def command(self, value: Command) -> None:
        """Set the internal command."""
        self._command = value

    def invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        """
        Process the input data and return a response.

        This method should be implemented by all subclasses to define
        the specific behavior of each node.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        """
        Process the input data asynchronously and return a response generator.

        This method should be implemented by all subclasses to define
        the specific behavior of each node.
        """
        yield []
        raise NotImplementedError("Subclasses must implement this method.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "class": self.__class__.__name__,
            "node_id": self.node_id,
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
            "tool": self.tool.to_dict() if self.tool else None,
            "subscribed_expressions": [
                expr.to_dict() for expr in self.subscribed_expressions
            ],
            "publish_to": [topic.to_dict() for topic in self.publish_to],
            "command": self.command.to_dict() if self.command else None,
        }


T_N = TypeVar("T_N", bound=NodeBase)


class NodeBaseBuilder(BaseBuilder[T_N]):
    """Inner builder class for workflow construction."""

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        self.kwargs["oi_span_type"] = oi_span_type
        return self

    def name(self, name: str) -> Self:
        self.kwargs["name"] = name
        return self

    def type(self, type: str) -> Self:
        self.kwargs["type"] = type
        return self

    def tool(self, tool: Tool) -> Self:
        """Set the tool for this node. Command will be auto-created."""
        self.kwargs["tool"] = tool
        return self

    def subscribe(self, subscribe_to: Union[TopicBase, SubExpr]) -> Self:
        """
        Begin building a DSL expression. Returns a SubscriptionDSL.Builder,
        which the user can chain with:
            .subscribed_to(topicA).and_().subscribed_to(topicB).build()
        """
        if "subscribed_expressions" not in self.kwargs:
            self.kwargs["subscribed_expressions"] = []

        if isinstance(subscribe_to, TopicBase):
            self.kwargs["subscribed_expressions"].append(TopicExpr(topic=subscribe_to))
        elif isinstance(subscribe_to, SubExpr):
            self.kwargs["subscribed_expressions"].append(subscribe_to)
        else:
            raise ValueError(
                f"Expected a Topic or SubExpr, but got {type(subscribe_to)}"
            )
        return self

    def publish_to(self, topic: TopicBase) -> Self:
        if "publish_to" not in self.kwargs:
            self.kwargs["publish_to"] = []
        self.kwargs["publish_to"].append(topic)
        return self
