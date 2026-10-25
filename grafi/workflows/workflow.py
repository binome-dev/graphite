import inspect
from typing import Any
from typing import AsyncGenerator
from typing import ClassVar
from typing import Dict
from typing import FrozenSet
from typing import Mapping
from typing import Optional
from typing import Self
from typing import Set
from typing import TypeVar
from typing import Union

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field
from pydantic import ModelWrapValidatorHandler
from pydantic import PrivateAttr
from pydantic import ValidationInfo
from pydantic import computed_field
from pydantic import model_validator

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions.duplicate_node_error import DuplicateNodeError
from grafi.common.manifest import Component
from grafi.common.manifest import ManifestError
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.nodes.node_base import NodeBase
from grafi.runtime.deltas import Delta
from grafi.topics.expressions.topic_expression import extract_topics
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_base import topics_in_scope


class Workflow(Component):
    """Abstract base class for workflows in a graph-based agent system.

    It is saved with its topics, once, and its nodes name them.
    """

    manifest_kind: ClassVar[Optional[str]] = "Workflow"
    loads_computed: ClassVar[FrozenSet[str]] = frozenset({"topics"})

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        refuse_invoke_without_stream(cls)

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.AGENT
    workflow_id: str = default_id
    name: str = "Workflow"
    type: str = "Workflow"
    nodes: Dict[str, NodeBase] = Field(default_factory=dict)

    # Stop flag to control workflow execution
    _stop_requested: bool = PrivateAttr(default=False)

    @computed_field(repr=False)  # type: ignore[prop-decorator]
    @property
    def topics(self) -> Dict[str, TopicBase]:
        """The workflow's topics, by name: those its nodes subscribe and
        publish to."""
        topics: Dict[str, TopicBase] = {}
        for node in self.nodes.values():
            for expr in node.subscribed_expressions:
                topics.update((topic.name, topic) for topic in extract_topics(expr))
            topics.update((topic.name, topic) for topic in node.publish_to)
        return topics

    @model_validator(mode="wrap")
    @classmethod
    def _load_topics(
        cls, data: Any, handler: ModelWrapValidatorHandler[Self], info: ValidationInfo
    ) -> Self:
        """Load the topics a saved workflow holds before its nodes, which name
        them."""
        if not (isinstance(data, Mapping) and "topics" in data):
            return handler(data)
        data = dict(data)
        if not isinstance(data["topics"], Mapping):
            raise ManifestError("A workflow's topics are an object, by name.")
        topics = {
            name: TopicBase.model_validate(topic, context=info.context)
            for name, topic in data.pop("topics").items()
        }
        for name, topic in topics.items():
            if topic.name != name:
                raise ManifestError(f"The topic {topic.name!r} is keyed as {name!r}.")
        with topics_in_scope(topics):
            return handler(data)

    def stop(self) -> None:
        """
        Stop the workflow execution.
        This method can be called by an assistant to stop the workflow during execution.
        It records the request in ``_stop_requested``; a subclass stops its runs.
        """
        logger.info("Workflow stop requested")
        self._stop_requested = True

    def reset_stop_flag(self) -> None:
        """
        Reset the stop flag for the workflow. (EventDrivenWorkflow stops its runs
        in flight directly, and its runs do not read this flag.)
        """
        self._stop_requested = False

    async def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        """Run the workflow on ``input_data``, yielding its outputs, and, if
        ``stream``, the deltas its tools emit as they emit them."""
        yield None  # type: ignore
        raise NotImplementedError

    async def initial_workflow(self, assistant_request_id: str) -> Any:
        """Initial workflow state, and replays events from an unfinished request to resume invoke."""
        raise NotImplementedError


def refuse_invoke_without_stream(cls: type) -> None:
    """Raise TypeError unless ``cls.invoke`` takes ``stream`` by keyword: a
    caller streaming passes it, and grafi passes it to every invoke. A wrapper
    taking ``**kwargs`` passes it to what it wraps, which must take it."""
    function: Any = cls.invoke  # type: ignore[attr-defined]
    seen: Set[int] = set()
    while function is not None and id(function) not in seen:
        seen.add(id(function))
        try:
            parameters = inspect.signature(function, follow_wrapped=False).parameters
        except (TypeError, ValueError):
            return  # Not one Python can read; its calls will tell.
        stream = parameters.get("stream")
        if stream is not None and stream.kind in (
            stream.POSITIONAL_OR_KEYWORD,
            stream.KEYWORD_ONLY,
        ):
            return
        if not any(p.kind is p.VAR_KEYWORD for p in parameters.values()):
            raise TypeError(
                f"{cls.__name__}.invoke() takes no stream by keyword: add `*, "
                "stream: bool = False` and pass it on, declaring the overloads "
                "the Assistant guide shows."
            )
        function = getattr(function, "__wrapped__", None)


T_W = TypeVar("T_W", bound="Workflow")  # the Workflow subclass


class WorkflowBuilder(BaseBuilder[T_W]):
    """Inner builder class for Workflow construction."""

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        """Set the OpenInference span type for observability.

        Args:
            oi_span_type: The span type for tracing (typically AGENT).

        Returns:
            Self for method chaining.
        """
        self.kwargs["oi_span_type"] = oi_span_type
        return self

    def name(self, name: str) -> Self:
        """Set the workflow's display name.

        Args:
            name: Human-readable identifier for the workflow.

        Returns:
            Self for method chaining.
        """
        self.kwargs["name"] = name
        return self

    def type(self, type_name: str) -> Self:
        """Set the workflow's type identifier.

        Args:
            type_name: Type classification for the workflow.

        Returns:
            Self for method chaining.
        """
        self.kwargs["type"] = type_name
        return self

    def node(self, node: NodeBase) -> Self:
        """Add a node to the workflow.

        Args:
            node: The node to add to this workflow.

        Returns:
            Self for method chaining.

        Raises:
            DuplicateNodeError: If a node with the same name already exists.
        """
        if "nodes" not in self.kwargs:
            self.kwargs["nodes"] = {}
        if node.name in self.kwargs["nodes"]:
            raise DuplicateNodeError(node)
        self.kwargs["nodes"][node.name] = node
        return self
