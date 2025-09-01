"""Exception for handling duplicate nodes in the graph."""

from grafi.nodes.node_base import NodeBase


class DuplicateNodeError(Exception):
    """Exception raised when a duplicate node is detected in the graph."""

    def __init__(self, node: NodeBase):
        super().__init__(f"Duplicate element detected: {node.name}")
        self.node = node
