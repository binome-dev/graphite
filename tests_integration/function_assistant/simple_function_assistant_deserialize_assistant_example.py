import asyncio
import uuid
from pathlib import Path

from dotenv import load_dotenv

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.import_ref import trust_modules
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import current_services

# Load API keys (e.g. OPENAI_API_KEY) from .env before the assistant is
# loaded: the manifest holds no key, only the variable each is read from.
load_dotenv()

# The manifest names the assistant's class, its function and its
# response_format model, all of tests_integration. Loading imports classes and
# functions only from trusted modules.
trust_modules("tests_integration")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


event_store = current_services().event_store


async def test_deserialized_assistant() -> None:
    """Load the assistant from its manifest, and run it."""
    assistant = Assistant.from_manifest(
        Path(__file__).parent / "SimpleFunctionLLMAssistant_manifest.json"
    )

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
    asyncio.run(test_deserialized_assistant())
