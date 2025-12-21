import asyncio
import json
import uuid
from pathlib import Path

from grafi.assistants.assistant import Assistant
from grafi.common.containers.container import container
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


event_store = container.event_store


async def test_deserialized_assistant() -> None:
    """Test the deserialized assistant using the new load_from_manifest method."""
    # Read the manifest JSON file
    with open(Path(__file__).parent / "complex_function_manifest.json", "r") as f:
        manifest_json = f.read()

    # Deserialize the assistant using the new method
    assistant = await Assistant.from_dict(json.loads(manifest_json))

    print(f"Successfully deserialized assistant: {assistant.name}")
    print(f"Workflow: {assistant.workflow.name}")
    print(f"Number of nodes: {len(assistant.workflow.nodes)}")

    # Test the run method
    input_data = [
        Message(
            role="user",
            content="Delete files /tmp/isdhfiadffiadfadf.log and /home/test/file.log?",
        )
    ]

    output = await async_func_wrapper(
        assistant.invoke(
            PublishToTopicEvent(
                invoke_context=get_invoke_context(),
                data=input_data,
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    assert "isdhfiadffiadfadf" in str(output[0].data[0].content)
    assert "file" in str(output[0].data[0].content)
    print(len(await event_store.get_events()))
    assert len(await event_store.get_events()) == 24


if __name__ == "__main__":
    asyncio.run(test_deserialized_assistant())
