import asyncio
import uuid
from pathlib import Path

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.import_ref import trust_modules
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message

# The manifest names the assistant's class, of tests_integration. Loading
# imports classes only from trusted modules.
trust_modules("tests_integration")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_deserialized_assistant() -> None:
    """Load the assistant from its manifest, and run it."""
    assistant = Assistant.from_manifest(
        Path(__file__).parent / "ReActAssistant_manifest.json"
    )

    print(f"Successfully deserialized assistant: {assistant.name}")
    print(f"Workflow: {assistant.workflow.name}")
    print(f"Number of nodes: {len(assistant.workflow.nodes)}")

    # Test the assistant with a query
    input_data = [
        Message(
            role="user",
            content="What is the elevation range for the area that the eastern sector of the Colorado orogeny extends into?",
        )
    ]

    # Invoke the assistant
    async for output in assistant.invoke(
        PublishToTopicEvent(
            invoke_context=get_invoke_context(),
            data=input_data,
        ),
        is_sequential=True,
    ):
        print("Assistant output:", output)
        assert output is not None
        print("Test passed!")


if __name__ == "__main__":
    asyncio.run(test_deserialized_assistant())
