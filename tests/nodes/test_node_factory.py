"""Unit tests for NodeFactory class dispatch on serialized manifests."""

import pytest

from grafi.nodes.impl.hooked_node import HookedNode
from grafi.nodes.node import Node
from grafi.nodes.node_factory import NodeFactory
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.topic_impl.output_topic import OutputTopic


def _node_dict(node) -> dict:
    return node.to_dict()


def _tool():
    return OpenAITool.builder().name("llm").model("gpt-4o-mini").build()


class TestNodeFactory:
    @pytest.mark.asyncio
    async def test_dispatches_plain_node(self):
        out = OutputTopic(name="agent_output")
        node = Node.builder().name("n").tool(_tool()).publish_to(out).build()
        restored = await NodeFactory.from_dict(node.to_dict(), {"agent_output": out})
        assert type(restored) is Node

    @pytest.mark.asyncio
    async def test_dispatches_hooked_node(self):
        out = OutputTopic(name="agent_output")
        node = HookedNode.builder().name("n").tool(_tool()).publish_to(out).build()
        restored = await NodeFactory.from_dict(node.to_dict(), {"agent_output": out})
        assert type(restored) is HookedNode

    @pytest.mark.asyncio
    async def test_missing_class_defaults_to_plain_node(self):
        # Manifests that predate the "class" field deserialize as plain Node.
        out = OutputTopic(name="agent_output")
        node = Node.builder().name("n").tool(_tool()).publish_to(out).build()
        data = node.to_dict()
        data.pop("class")
        restored = await NodeFactory.from_dict(data, {"agent_output": out})
        assert type(restored) is Node

    @pytest.mark.asyncio
    async def test_unknown_class_fails_loudly(self):
        # An unknown class must NOT silently deserialize as an ungated Node.
        out = OutputTopic(name="agent_output")
        node = HookedNode.builder().name("n").tool(_tool()).publish_to(out).build()
        data = node.to_dict()
        data["class"] = "MyCustomGateNode"
        with pytest.raises(ValueError) as err:
            await NodeFactory.from_dict(data, {"agent_output": out})
        message = str(err.value)
        assert "MyCustomGateNode" in message
        assert "HookedNode" in message  # enumerates known classes
        assert "register" in message.lower()

    @pytest.mark.asyncio
    async def test_registered_custom_class_dispatches(self):
        class MyCustomGateNode(HookedNode):
            pass

        NodeFactory.register(MyCustomGateNode)
        try:
            out = OutputTopic(name="agent_output")
            node = (
                MyCustomGateNode.builder()
                .name("n")
                .tool(_tool())
                .publish_to(out)
                .build()
            )
            data = node.to_dict()
            assert data["class"] == "MyCustomGateNode"
            restored = await NodeFactory.from_dict(data, {"agent_output": out})
            assert type(restored) is MyCustomGateNode
        finally:
            NodeFactory._NODE_REGISTRY.pop("MyCustomGateNode", None)

    @pytest.mark.asyncio
    async def test_register_supports_alias_for_renamed_class(self):
        # The migration path for a renamed class: register the old name too.
        NodeFactory.register(HookedNode, name="LegacyHookedNode")
        try:
            out = OutputTopic(name="agent_output")
            node = HookedNode.builder().name("n").tool(_tool()).publish_to(out).build()
            data = node.to_dict()
            data["class"] = "LegacyHookedNode"
            restored = await NodeFactory.from_dict(data, {"agent_output": out})
            assert type(restored) is HookedNode
        finally:
            NodeFactory._NODE_REGISTRY.pop("LegacyHookedNode", None)
