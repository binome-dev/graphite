"""Exception for handling duplicate nodes in the graph."""

from typing import TYPE_CHECKING

from grafi.common.exceptions.workflow_exceptions import WorkflowError


if TYPE_CHECKING:
    from grafi.nodes.node_base import NodeBase


class DuplicateNodeError(WorkflowError):
    """Exception raised when a duplicate node is detected in the graph."""

    def __init__(self, node: "NodeBase") -> None:
        super().__init__(
            message=f"Duplicate node detected: {node.name}", severity="ERROR"
        )
        self.node = node
        self.node_name = node.name
