import asyncio
import json
import uuid
from pathlib import Path

from grafi.assistants.assistant import Assistant
from grafi.common.containers.container import container
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.mcp_tool import MCPTool
from grafi.tools.tool_factory import ToolFactory


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


event_store = container.event_store


async def test_deserialized_assistant() -> None:
    """Test the deserialized assistant using the new from_dict method."""
    # Read the manifest JSON file
    invoke_context = get_invoke_context()
    with open(Path(__file__).parent / "MCPAssistant_manifest.json", "r") as f:
        manifest_json = f.read()

    ToolFactory.register_tool_class("MCPTool", MCPTool)
    # Deserialize the assistant using the new method
    assistant = await Assistant.from_dict(json.loads(manifest_json))

    print(f"Successfully deserialized assistant: {assistant.name}")
    print(f"Workflow: {assistant.workflow.name}")
    print(f"Number of nodes: {len(assistant.workflow.nodes)}")

    input_data = [Message(role="user", content="Hi my name is Graphite.")]

    # Invoke the assistant's function call
    async for output in assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    ):
        print(output)
        assert output is not None

    assert len(await event_store.get_events()) == 24


if __name__ == "__main__":
    asyncio.run(test_deserialized_assistant())
