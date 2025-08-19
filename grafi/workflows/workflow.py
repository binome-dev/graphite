from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List
from typing import Self
from typing import TypeVar

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import PrivateAttr

from grafi.common.events.event import Event
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions.duplicate_node_error import DuplicateNodeError
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.nodes.node import Node


class Workflow(BaseModel):
    """Abstract base class for workflows in a graph-based agent system."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.AGENT
    workflow_id: str = default_id
    name: str = "Workflow"
    type: str = "Workflow"
    nodes: Dict[str, Node] = {}

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

    def invoke(self, input_data: PublishToTopicEvent) -> List[ConsumeFromTopicEvent]:
        """Invokes the workflow with the given initial inputs."""
        raise NotImplementedError

    async def a_invoke(
        self, input_data: PublishToTopicEvent
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """Invokes the workflow with the given initial inputs."""
        yield None  # type: ignore
        raise NotImplementedError

    def initial_workflow(self, assistant_request_id: str) -> Any:
        """Initial workflow state, and replays events from an unfinished request to resume invoke."""
        raise NotImplementedError

    def on_event(self, event: "Event") -> None:
        """Handle events dispatched from nodes and tools."""
        raise NotImplementedError

    def on_output_event(self, event: Event) -> None:
        """Handle output events dispatched from nodes and tools."""
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


T_W = TypeVar("T_W", bound="Workflow")  # the Tool subclass


class WorkflowBuilder(BaseBuilder[T_W]):
    """Inner builder class for Workflow construction."""

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        self.kwargs["oi_span_type"] = oi_span_type
        return self

    def name(self, name: str) -> Self:
        self.kwargs["name"] = name
        return self

    def type(self, type_name: str) -> Self:
        self.kwargs["type"] = type_name
        return self

    def node(self, node: Node) -> Self:
        if "nodes" not in self.kwargs:
            self.kwargs["nodes"] = {}
        if node.name in self.kwargs["nodes"]:
            raise DuplicateNodeError(node)
        self.kwargs["nodes"][node.name] = node
        return self
