import json
import os
import uuid

from simple_hitl_assistant import SimpleHITLAssistant

from grafi.common.containers.container import event_store
from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.functions.function_tool import FunctionTool

api_key = os.getenv("OPENAI_API_KEY")


class HumanInfo(FunctionTool):
    @llm_function
    def request_human_information(self, question_description: str):
        """
        Requests human input for personal information based on a given question description.
        This method simulates requesting information from a human user during test scenarios.
        It prompts the user with a specific question about personal information based on the
        provided context.

        Args:
            question_description (str): The question or prompt to ask the human user for personal information.

        Returns:
            dict: An dictionary representing a questionary schema for the user to fill out.
        """
        return json.dumps(
            {
                "question_description": question_description,
                "name": "string",
            }
        )


def get_execution_context():
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_simple_hitl_assistant():
    execution_context = get_execution_context()

    assistant = (
        SimpleHITLAssistant.Builder()
        .name("SimpleHITLAssistant")
        .api_key(api_key)
        .hitl_llm_system_message(
            "You are an AI assistant analysis the request, if request required user then ask user to provide information."
        )
        .summary_llm_system_message(
            "You are an AI assistant tasked with summarizing the findings from previous observations to provide a clear and accurate answer to the user's question. Ensure the summary directly addresses the query based on the information gathered."
        )
        .hitl_request(HumanInfo(name="request_human_information"))
        .build()
    )

    # Test the run method
    input_data = [
        Message(
            role="user",
            content="Hello, I want to register the gym. This gym require user's name and user's age separately. Can you help me?",
        )
    ]

    output = assistant.execute(execution_context, input_data)

    print(output)

    human_input = [
        Message(
            role="user",
            content="My name is craig.",
        )
    ]

    output = assistant.execute(execution_context, human_input)

    human_input = [
        Message(
            role="user",
            content="My age is 30.",
        )
    ]

    output = assistant.execute(execution_context, human_input)

    print(output)

    events = event_store.get_events()
    print(len(events))
    assert len(events) == 53


test_simple_hitl_assistant()
