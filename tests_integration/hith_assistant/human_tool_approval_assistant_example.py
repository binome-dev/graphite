import os
import uuid

from grafi.common.containers.container import container
from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from tests_integration.hith_assistant.human_tool_approval_assistant import (
    HumanApprovalAssistant,
)


event_store = container.event_store

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


def test_simple_function_call_assistant() -> None:
    conversation_id = "test_conversation_id_approve"
    assistant_request_id = "test_assistant_request_id_approve"

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    assistant = (
        HumanApprovalAssistant.builder()
        .name("HumanApprovalAssistant")
        .api_key(api_key)
        .function_tool(DeleteDatabase(name="DeleteDatabase"))
        .build()
    )

    # Test the run method
    input_data = [
        Message(role="user", content="Hello, I want to delete database user_backup.")
    ]

    output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[0].tool_calls is not None

    # Test the run method
    input_data = output[0].data
    input_data.append(
        Message(
            role="user",
            content="YES",
        )
    )

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )
    invoke_context.kwargs = {"consumed_event_ids": [event.event_id for event in output]}

    output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[0].tool_calls is None


def test_simple_function_call_assistant_disapproval() -> None:

    conversation_id = "test_conversation_id_disapprove"
    assistant_request_id = "test_assistant_request_id_disapprove"
    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    assistant = (
        HumanApprovalAssistant.builder()
        .name("HumanApprovalAssistant")
        .api_key(api_key)
        .function_tool(DeleteDatabase(name="DeleteDatabase"))
        .build()
    )

    # Test the run method
    input_data = [
        Message(role="user", content="Hello, I want to delete database user_backup.")
    ]

    output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[0].tool_calls is not None

    # Test the run method
    input_data = []
    input_data.append(
        Message(
            role="user",
            content="NO",
        )
    )

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )
    invoke_context.kwargs = {"consumed_event_ids": [event.event_id for event in output]}

    output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[0].tool_calls is None


def test_simple_function_call_assistant_suggestion() -> None:

    conversation_id = "test_conversation_id_suggest"
    assistant_request_id = "test_assistant_request_id_suggest"
    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    assistant = (
        HumanApprovalAssistant.builder()
        .name("HumanApprovalAssistant")
        .api_key(api_key)
        .function_tool(DeleteDatabase(name="DeleteDatabase"))
        .build()
    )

    # Test the run method
    input_data = [
        Message(role="user", content="Hello, I want to delete database user_backup.")
    ]

    output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[0].tool_calls is not None

    # Test the run method
    input_data = []
    input_data.append(
        Message(
            role="user",
            content="NO. You should add 'staging.' prefix to all the database names.",
        )
    )

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )
    invoke_context.kwargs = {"consumed_event_ids": [event.event_id for event in output]}

    output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[0].tool_calls is not None
    arguments = output[0].data[0].tool_calls[0].function.arguments
    import json

    parsed_args = json.loads(arguments)
    assert parsed_args["db_name"] == "staging.user_backup"

    # Test the run method
    input_data = []
    input_data.append(
        Message(
            role="user",
            content="YES",
        )
    )

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )
    invoke_context.kwargs = {"consumed_event_ids": [event.event_id for event in output]}

    output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[0].tool_calls is None


def test_simple_function_call_assistant_suggestion_mem() -> None:

    conversation_id = "test_conversation_id_suggest"
    assistant_request_id = "test_assistant_request_id_mem"
    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    assistant = (
        HumanApprovalAssistant.builder()
        .name("HumanApprovalAssistant")
        .api_key(api_key)
        .function_tool(DeleteDatabase(name="DeleteDatabase"))
        .function_call_llm_system_message(
            "You must consider previous user's suggestions, think about how to incorporate them when calling the tools"
        )
        .build()
    )

    # Test the run method
    input_data = [
        Message(role="user", content="Hello, I want to delete database product_backup.")
    ]

    output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[0].tool_calls is not None
    arguments = output[0].data[0].tool_calls[0].function.arguments
    import json

    parsed_args = json.loads(arguments)
    assert parsed_args["db_name"] == "staging.product_backup"


test_simple_function_call_assistant()
test_simple_function_call_assistant_disapproval()
test_simple_function_call_assistant_suggestion()
test_simple_function_call_assistant_suggestion_mem()
