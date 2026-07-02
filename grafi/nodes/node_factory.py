"""NodeFactory - deserialize nodes from dictionary representations.

Mirrors :class:`~grafi.tools.tool_factory.ToolFactory`: the serialized
``"class"`` field selects the node class, which then reconstructs itself via
its own ``from_dict``. Custom node classes join the registry with
:meth:`NodeFactory.register`.
"""

from typing import Any
from typing import Dict
from typing import Optional
from typing import Type

from grafi.nodes.impl.hooked_node import HookedNode
from grafi.nodes.node import Node
from grafi.nodes.node_base import NodeBase
from grafi.topics.topic_base import TopicBase


class NodeFactory:
    """Factory for creating node instances from dictionary representations."""

    _NODE_REGISTRY: Dict[str, Type[NodeBase]] = {}

    @classmethod
    def register(
        cls, node_class: Type[NodeBase], name: Optional[str] = None
    ) -> Type[NodeBase]:
        """Register a node class for manifest deserialization.

        Args:
            node_class: The class to register; must implement ``from_dict``.
            name: Registry key; defaults to the class name (which is what
                ``NodeBase.to_dict`` serializes as ``"class"``).

        Returns:
            The class, so this can be used as a decorator on custom nodes.
        """
        cls._NODE_REGISTRY[name or node_class.__name__] = node_class
        return node_class

    @classmethod
    async def from_dict(
        cls, node_dict: Dict[str, Any], topics: Dict[str, TopicBase]
    ) -> NodeBase:
        """Create a node instance from its dictionary representation.

        Args:
            node_dict: Serialized node. ``"class"`` selects the node class;
                manifests that predate the field deserialize as plain ``Node``.
            topics: Reconstructed topic instances keyed by name (for routes and
                subscriptions).

        Returns:
            NodeBase: An instance of the registered node class.

        Raises:
            ValueError: If ``"class"`` names an unregistered node class.
        """
        class_name = node_dict.get("class", Node.__name__)
        node_class = cls._NODE_REGISTRY.get(class_name)
        if node_class is None:
            raise ValueError(
                f"Unknown node class: {class_name!r}. Known classes: "
                f"{sorted(cls._NODE_REGISTRY)}. Register custom node classes "
                "with NodeFactory.register() before deserializing."
            )
        return await node_class.from_dict(node_dict, topics)


NodeFactory.register(Node)
NodeFactory.register(HookedNode)
