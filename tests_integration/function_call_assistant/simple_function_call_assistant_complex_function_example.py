import asyncio
import os
import uuid
from typing import Optional

from grafi.common.containers.container import container
from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


class LocalFileMock(FunctionCallTool):
    @llm_function
    def delete_files(self, files: list[str], root_path: Optional[str] = "/") -> str:
        """
        Function to delete files from a given root path.

        Args:
            files (list[str]): A list of file names to delete.
            root_path (Optional[str]): The root directory path from which to delete files.

        Returns:
            str: A string indicating which files were deleted from which root path.
        """
        return f"Deleted files: {files} from root path: {root_path}"


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant() -> None:
    invoke_context = get_invoke_context()

    assistant = (
        SimpleFunctionCallAssistant.builder()
        .name("SimpleFunctionCallAssistant")
        .api_key(api_key)
        .function_tool(LocalFileMock(name="LocalFileMock"))
        .build()
    )

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
                invoke_context=invoke_context,
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

    # assistant.generate_workflow_graph()
    # assistant.generate_manifest()

    # events = event_store.get_events()
    # for event in events:
    #     try:
    #         print(json.dumps(event.to_dict(), indent=4))
    #     except Exception as e:
    #         print(e)
    #         print(event)
    #         break


asyncio.run(test_simple_function_call_assistant())
