"""Exception for handling duplicate nodes in the graph."""

from grafi.nodes.node import Node


class DuplicateNodeError(Exception):
    """Exception raised when a duplicate node is detected in the graph."""

    def __init__(self, node: "Node"):
        super().__init__(f"Duplicate element detected: {node.name}")
        self.node = node
