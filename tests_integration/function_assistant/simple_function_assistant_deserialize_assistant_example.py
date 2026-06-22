import asyncio
import json
import uuid
from pathlib import Path

from dotenv import load_dotenv

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import GrafiRuntime
from grafi.runtime.execution_services import bind_services

# Load API keys (e.g. OPENAI_API_KEY) from .env before the assistant is
# deserialized; OpenAITool.from_dict() reads the key from the environment since
# the manifest stores it masked.
load_dotenv()


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


runtime = GrafiRuntime()
event_store = runtime.services.event_store


async def test_deserialized_assistant() -> None:
    """Test the deserialized assistant using the new load_from_manifest method."""
    # Read the manifest JSON file
    with open(
        Path(__file__).parent / "SimpleFunctionLLMAssistant_manifest.json", "r"
    ) as f:
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
            content="Generate mock user.",
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
    assert "first_name" in str(output[0].data[0].content)
    assert "last_name" in str(output[0].data[0].content)
    print(len(await event_store.get_events()))
    assert len(await event_store.get_events()) == 18


if __name__ == "__main__":
    with bind_services(runtime.services):
        asyncio.run(test_deserialized_assistant())
