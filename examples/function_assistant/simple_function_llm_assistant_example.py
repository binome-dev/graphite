import os
import uuid
from typing import List

from pydantic import BaseModel

from examples.function_assistant.simple_function_llm_assistant import (
    SimpleFunctionLLMAssistant,
)
from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


class UserForm(BaseModel):
    """
    A simple user form model for demonstration purposes.
    """

    first_name: str
    last_name: str
    location: str
    gender: str


def print_user_form(input_messages: Messages) -> List[str]:
    """
    Function to print user form details.

    Args:
        Messages: The input messages containing user form details.

    Returns:
        list: A list string containing the user form details.
    """

    user_details = []

    for message in input_messages:
        if message.role == "assistant" and message.content:
            try:
                form = UserForm.model_validate_json(message.content)
                print(
                    f"User Form Details:\nFirst Name: {form.first_name}\nLast Name: {form.last_name}\nLocation: {form.location}\nGender: {form.gender}\n"
                )
                user_details.append(form.model_dump_json(indent=2))
            except Exception as e:
                raise ValueError(
                    f"Failed to parse user form from message content: {message.content}. Error: {e}"
                )

    return user_details


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_simple_function_call_assistant() -> None:
    execution_context = get_execution_context()

    assistant = (
        SimpleFunctionLLMAssistant.Builder()
        .name("SimpleFunctionLLMAssistant")
        .api_key(api_key)
        .function(print_user_form)
        .output_format(UserForm)
        .build()
    )

    # Test the run method
    input_data = [
        Message(
            role="user",
            content="Generate mock user.",
        )
    ]

    output = assistant.execute(execution_context, input_data)
    print(output)
    assert output is not None
    assert "first_name" in str(output[0].content)
    assert "last_name" in str(output[0].content)
    print(len(event_store.get_events()))
    assert len(event_store.get_events()) == 17


test_simple_function_call_assistant()
