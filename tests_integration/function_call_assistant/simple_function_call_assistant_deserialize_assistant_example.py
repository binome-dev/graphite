import asyncio
import uuid
from pathlib import Path

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.import_ref import trust_modules
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import current_services

# The manifest names classes of tests_integration: the assistant's, and the
# LocalInfoMock tool's, which brings its @llm_function methods. Loading imports
# classes only from trusted modules.
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
        Path(__file__).parent / "SimpleFunctionCallAssistant_manifest.json"
    )

    print(f"Successfully deserialized assistant: {assistant.name}")
    print(f"Workflow: {assistant.workflow.name}")
    print(f"Number of nodes: {len(assistant.workflow.nodes)}")

    # Test the run method
    input_data = [Message(role="user", content="Hello, how's the weather in 12345?")]

    output = await async_func_wrapper(
        assistant.invoke(
            PublishToTopicEvent(
                invoke_context=get_invoke_context(),
                data=input_data,
            ),
            is_sequential=True,
        )
    )
    print(output[-1].data[0].content)
    assert output is not None
    assert "12345" in str(output[-1].data[0].content)
    # The function's own words, not the LLM's rewording of them.
    tool_results = [
        message.content
        for event in await event_store.get_events()
        if isinstance(event, PublishToTopicEvent)
        for message in event.data
        if message.role == "tool"
    ]
    assert any("bad" in str(result) for result in tool_results)
    print(len(await event_store.get_events()))
    # Same workflow as the freshly-built assistant, so the same event count
    # (see simple_function_call_assistant_multi_functions_example.py).
    assert len(await event_store.get_events()) == 24

    # Test restore from finished requests

    input_data = [
        Message(role="user", content="Hello, what's the population in 12345?")
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

    print(output[-1].data[0].content)
    assert output is not None
    content = str(output[-1].data[0].content)
    assert "12345" in content
    # The mock returns "200000"; the summary LLM may or may not add a comma.
    assert "200,000" in content or "200000" in content
    print(len(await event_store.get_events()))
    # Two identical runs, 24 unique events each (deduped on event_id).
    assert len(await event_store.get_events()) == 48


if __name__ == "__main__":
    asyncio.run(test_deserialized_assistant())
