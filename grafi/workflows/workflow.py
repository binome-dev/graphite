from typing import Any
from typing import Dict
from typing import List
from typing import Self
from typing import Tuple
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel

from grafi.common.events.event import Event
from grafi.common.events.node_events.node_event import NodeEvent
from grafi.common.models.default_id import default_id
from grafi.common.models.event_id import EventId
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.nodes.node import Node


class Workflow(BaseModel):
    """Abstract base class for workflows in a graph-based agent system."""

    oi_span_type: OpenInferenceSpanKindValues
    workflow_id: str = default_id
    name: str
    type: str
    nodes: Dict[str, Node] = {}
    state: Dict[str, Tuple[str, NodeEvent | None]] = {}

    class Builder:
        """Inner builder class for workflow construction."""

        def __init__(self) -> None:
            self._workflow = self._init_workflow()

        def _init_workflow(self) -> "Workflow":
            raise NotImplementedError

        def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
            self._workflow.oi_span_type = oi_span_type
            return self

        def name(self, name: str) -> Self:
            self._workflow.name = name
            return self

        def type(self, type_name: str) -> Self:
            self._workflow.type = type_name
            return self

        def node(self, node: Node) -> Self:
            raise NotImplementedError

        def build(self) -> "Workflow":
            raise NotImplementedError

    def execute(self, execution_context: ExecutionContext, input: Messages) -> None:
        """Executes the workflow with the given initial inputs."""
        raise NotImplementedError

    async def a_execute(
        self, execution_context: ExecutionContext, input: Messages
    ) -> None:
        """Executes the workflow with the given initial inputs."""
        raise NotImplementedError

    def initial_workflow(self, assistant_request_id: str) -> Any:
        """Initial workflow state, and replays events from an unfinished request to resume execution."""
        raise NotImplementedError

    def get_node_input(
        self, node: Node, execution_context: ExecutionContext
    ) -> Tuple[List[EventId], Messages]:
        """Get input messages for a node from its subscribed topics."""
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
        }


W = TypeVar("W", bound="Workflow")  # the Tool subclass
