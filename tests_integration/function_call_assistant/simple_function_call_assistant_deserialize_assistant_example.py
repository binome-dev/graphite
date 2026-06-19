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
from grafi.tools.tool_factory import ToolFactory
from tests_integration.function_call_assistant.simple_function_call_assistant_multi_functions_example import (  # noqa: E501
    LocalInfoMock,
)

# The custom FunctionCallTool subclass must be registered so the manifest's
# "LocalInfoMock" tool reconstructs with its @llm_function methods (they are
# defined by the class, not serialized).
ToolFactory.register_tool_class("LocalInfoMock", LocalInfoMock)


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
    with open(
        Path(__file__).parent / "SimpleFunctionCallAssistant_manifest.json", "r"
    ) as f:
        manifest_json = f.read()

    # Deserialize the assistant using the new method
    assistant = await Assistant.from_dict(json.loads(manifest_json))

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
    assert "bad" in str(output[-1].data[0].content)
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
