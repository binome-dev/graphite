from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import ClassVar
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import TypeVar
from typing import Union

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import PrivateAttr

from grafi.common.callable_ref import CallableRef
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.manifest import Component
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.nodes.conditions import always_true
from grafi.tools.command import Command
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import SubExpr
from grafi.topics.expressions.topic_expression import Subscription
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.expressions.topic_expression import evaluate_subscription
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_base import TopicRef


class PublishRoute(BaseModel):
    """One destination in the publisher router's table.

    ``when`` is the CONTENT predicate (what used to live on ``topic.condition``).
    """

    # A key it does not have is refused, so a misspelt one changes no route.
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    topic: TopicRef  # destination (definition-time instance), saved by name
    when: CallableRef = always_true  # content predicate, saved by reference


class PublisherRouter(BaseModel):
    """The node's output routing table; ``publish_to`` derives from its routes."""

    # A key it does not have is refused, so a misspelt one changes no route.
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    routes: List[PublishRoute] = Field(default_factory=list)

    def select(self, event: PublishToTopicEvent) -> List[str]:
        """Matched destinations, once each in first matched route order."""
        return list(
            dict.fromkeys(
                r.topic.name for r in self.routes if self._condition_ok(r.when, event)
            )
        )

    @staticmethod
    def _condition_ok(
        when: Callable[[PublishToTopicEvent], bool], event: PublishToTopicEvent
    ) -> bool:
        """Evaluate a route's content predicate with the topic error policy.

        Mirrors the old ``TopicBase.publish_data``: an ``IndexError``/``KeyError``
        is the expected "not met" signal for predicates that index possibly-empty
        data; any other exception is a probable bug, surfaced at WARNING but
        still treated as not-met so one faulty predicate cannot halt the
        workflow.
        """
        try:
            return bool(when(event))
        except (IndexError, KeyError) as e:
            logger.debug(f"Route predicate not met ({type(e).__name__}: {e}).")
            return False
        except Exception as e:  # noqa: BLE001 - defensive: a user predicate bug
            logger.warning(
                f"Route predicate raised an unexpected {type(e).__name__}: {e}. "
                "Treating as not published; check the publisher route's `when`."
            )
            return False

    @property
    def publish_to(self) -> List[TopicBase]:
        """Every destination topic (the node's single output declaration)."""
        return [r.topic for r in self.routes]


class NodeBase(Component):
    """Abstract base class for nodes in a graph-based agent system.

    A node is saved with its tool, its subscriptions and its routes, which name
    their topics; its command follows from its tool.
    """

    manifest_kind: ClassVar[Optional[str]] = "Node"

    node_id: str = default_id
    name: str = Field(default="Node")
    type: str = Field(default="Node")
    tool: Optional[Tool] = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.CHAIN
    subscribed_expressions: List[Subscription] = Field(default_factory=list)
    publisher_router: PublisherRouter = Field(default_factory=PublisherRouter)

    _subscribed_topics: Dict[str, TopicBase] = PrivateAttr(default_factory=dict)
    _command: Optional[Command] = PrivateAttr(default=None)

    @property
    def publish_to(self) -> List[TopicBase]:
        """Every destination topic (derived from the publisher router's routes)."""
        return self.publisher_router.publish_to

    @property
    def command(self) -> Optional[Command]:
        """The command the node runs its tool through, which the tool's class
        names (see :func:`~grafi.tools.command.use_command`); None without a
        tool. Made from the tool when read, again once the node holds
        another."""
        if self.tool is None:
            return None
        if self._command is None or self._command.tool is not self.tool:
            self._command = Command.for_tool(self.tool)
        return self._command

    @command.setter
    def command(self, command: Command) -> None:
        raise AttributeError(
            "A node's command cannot be set: it follows from its tool's class, "
            "which names it with @use_command."
        )

    @property
    def subscribed_topics(self) -> List[TopicBase]:
        """Return a list of subscribed topics."""
        return list(self._subscribed_topics.values())

    async def invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> AsyncGenerator[PublishToTopicEvent, None]:
        """
        Process the input data asynchronously and return a response generator.

        This method should be implemented by all subclasses to define
        the specific behavior of each node.
        """
        raise NotImplementedError("Subclasses must implement this method.")
        # The yield after raise is unreachable but needed for type checking
        yield  # pragma: no cover

    async def can_invoke(self) -> bool:
        """
        Check if this node can invoke given which topics currently have new data.
        If ALL of the node's subscribed_expressions is True, we return True.
        :return: Boolean indicating whether the node should run.
        """
        if not self.subscribed_expressions:
            return True

        topics_with_new_msgs = set()

        # Evaluate each expression; if any is satisfied, we can invoke.
        for topic in self._subscribed_topics.values():
            if await topic.can_consume(self.name):
                topics_with_new_msgs.add(topic.name)

        for expr in self.subscribed_expressions:
            if not evaluate_subscription(expr, list(topics_with_new_msgs)):
                return False

        return True

    def can_invoke_with_topics(self, topics: List[str]) -> bool:
        """
        Check if this node can invoke given a list of topic names.
        If ALL of the node's subscribed_expressions is True, we return True.
        :param topics: List of topic names to check against the node's expressions.
        :return: Boolean indicating whether the node should run.
        """
        if not self.subscribed_expressions:
            return True

        for expr in self.subscribed_expressions:
            if not evaluate_subscription(expr, topics):
                return False

        return True


T_N = TypeVar("T_N", bound=NodeBase)


class NodeBaseBuilder(BaseBuilder[T_N]):
    """Inner builder class for workflow construction."""

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        """Set the OpenInference span type for observability.

        Args:
            oi_span_type: The span type for tracing (e.g., CHAIN, TOOL).

        Returns:
            Self for method chaining.
        """
        self.kwargs["oi_span_type"] = oi_span_type
        return self

    def node_id(self, node_id: str) -> Self:
        """Set the node's stable identifier.

        Events name the node by it, so a node built again keeps its events'
        history by keeping its id, rather than getting a fresh one.

        Args:
            node_id: The node's unique identifier.

        Returns:
            Self for method chaining.
        """
        self.kwargs["node_id"] = node_id
        return self

    def name(self, name: str) -> Self:
        """Set the node's display name.

        Args:
            name: Human-readable identifier for the node.

        Returns:
            Self for method chaining.
        """
        self.kwargs["name"] = name
        return self

    def type(self, type: str) -> Self:
        """Set the node's type identifier.

        Args:
            type: Type classification for the node.

        Returns:
            Self for method chaining.
        """
        self.kwargs["type"] = type
        return self

    def tool(self, tool: Tool) -> Self:
        """Set the tool for this node. Command will be auto-created.

        Args:
            tool: The tool instance to execute when this node is invoked.

        Returns:
            Self for method chaining.
        """
        self.kwargs["tool"] = tool
        return self

    def subscribe(self, subscribe_to: Union[TopicBase, SubExpr]) -> Self:
        """Subscribe this node to a topic or subscription expression.

        The node will be triggered when the subscription condition is met.
        Can be chained with boolean expressions using SubscriptionBuilder.

        Args:
            subscribe_to: A Topic or SubExpr (from SubscriptionBuilder).

        Returns:
            Self for method chaining.

        Raises:
            NodeExecutionError: If subscribe_to is not a Topic or SubExpr.
        """
        if "subscribed_expressions" not in self.kwargs:
            self.kwargs["subscribed_expressions"] = []

        if isinstance(subscribe_to, TopicBase):
            self.kwargs["subscribed_expressions"].append(TopicExpr(topic=subscribe_to))
        elif isinstance(subscribe_to, SubExpr):
            self.kwargs["subscribed_expressions"].append(subscribe_to)
        else:
            raise NodeExecutionError(
                node_name=self.kwargs.get("name", "unknown"),
                message=f"Invalid subscription: Expected a Topic or SubExpr, but got {type(subscribe_to)}",
            )
        return self

    def publish_to(
        self,
        topic: TopicBase,
        when: Optional[Callable[[PublishToTopicEvent], bool]] = None,
    ) -> Self:
        """Add a publisher route to a topic this node publishes to.

        Args:
            topic: The topic to publish output events to.
            when: Optional content predicate (defaults to "always"); the route is
                taken when it returns True for the outgoing event.

        Returns:
            Self for method chaining.
        """
        if "publisher_router" not in self.kwargs:
            self.kwargs["publisher_router"] = PublisherRouter()
        route_kwargs: Dict[str, Any] = {"topic": topic}
        if when is not None:
            route_kwargs["when"] = when
        self.kwargs["publisher_router"].routes.append(PublishRoute(**route_kwargs))
        return self

    def publisher_router(self, publisher_router: PublisherRouter) -> Self:
        """Set the whole publisher router, its routes at once.

        Args:
            publisher_router: The node's output routing table.

        Returns:
            Self for method chaining.
        """
        self.kwargs["publisher_router"] = publisher_router
        return self
