import asyncio
import os
import uuid

from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import GrafiRuntime
from grafi.runtime.execution_services import bind_services
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from tests_integration.hith_assistant.human_tool_approval_assistant import (
    HumanApprovalAssistant,
)

runtime = GrafiRuntime()
event_store = runtime.services.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


class DeleteDatabase(FunctionCallTool):
    @llm_function
    def delete_database(self, db_name: str) -> str:
        """
        Function to delete a database.

        Args:
            db_name (str): The name of the database to delete.

        Returns:
            str: A confirmation message indicating the result of the deletion.
        """
        return f"Database {db_name} has been deleted."


def get_invoke_context(
    conversation_id: str, assistant_request_id: str
) -> InvokeContext:
    return InvokeContext(
        conversation_id=conversation_id,
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=assistant_request_id,
    )


async def test_human_tool_approval_pause_then_resume() -> None:
    """Plain pause/resume: propose a tool call, surface it, resume on a reply.

    (Verdict-gated approve/deny lands with the tool-hooks change; this example
    only exercises the pause/resume mechanics.)
    """
    conversation_id = "test_conversation_id_review"
    assistant_request_id = "test_assistant_request_id_review"

    invoke_context = get_invoke_context(conversation_id, assistant_request_id)

    assistant = (
        HumanApprovalAssistant.builder()
        .name("HumanApprovalAssistant")
        .api_key(api_key)
        .function_tool(DeleteDatabase(name="DeleteDatabase"))
        .build()
    )

    # 1) Propose the tool call; the function node runs it and surfaces the
    #    result to the human, pausing the workflow.
    input_data = [
        Message(role="user", content="Hello, I want to delete database user_backup.")
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

    # 2) The human reviews and replies; the reply resumes the workflow and the
    #    LLM produces the final answer.
    resume_data = [Message(role="user", content="Looks good, thanks.")]

    invoke_context = get_invoke_context(conversation_id, assistant_request_id)

    output = await async_func_wrapper(
        assistant.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=resume_data,
                consumed_event_ids=[event.event_id for event in output],
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[0].tool_calls is None


with bind_services(runtime.services):
    asyncio.run(test_human_tool_approval_pause_then_resume())
