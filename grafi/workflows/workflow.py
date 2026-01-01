from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import Self
from typing import TypeVar

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import Field
from pydantic import PrivateAttr

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions.duplicate_node_error import DuplicateNodeError
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.nodes.node_base import NodeBase


class Workflow(BaseModel):
    """Abstract base class for workflows in a graph-based agent system."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.AGENT
    workflow_id: str = default_id
    name: str = "Workflow"
    type: str = "Workflow"
    nodes: Dict[str, NodeBase] = Field(default_factory=dict)

    # Stop flag to control workflow execution
    _stop_requested: bool = PrivateAttr(default=False)

    def stop(self) -> None:
        """
        Stop the workflow execution.
        This method can be called by an assistant to stop the workflow during execution.
        """
        logger.info("Workflow stop requested")
        self._stop_requested = True

    def reset_stop_flag(self) -> None:
        """
        Reset the stop flag for the workflow.
        This should be called before starting a new workflow execution.
        """
        self._stop_requested = False

    async def invoke(
        self, input_data: PublishToTopicEvent, is_sequential: bool = False
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """Invokes the workflow with the given initial inputs parallelly."""
        yield None  # type: ignore
        raise NotImplementedError

    async def initial_workflow(self, assistant_request_id: str) -> Any:
        """Initial workflow state, and replays events from an unfinished request to resume invoke."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Convert the workflow to a dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
            "nodes": {name: node.to_dict() for name, node in self.nodes.items()},
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "Workflow":
        """Create a Workflow instance from a dictionary representation."""
        raise NotImplementedError("from_dict must be implemented in subclasses.")


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
