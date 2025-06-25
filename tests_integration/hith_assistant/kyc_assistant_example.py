import json
import os
import uuid

from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from tests_integration.hith_assistant.kyc_assistant import KycAssistant


api_key = os.getenv("OPENAI_API_KEY", "")


class ClientInfo(FunctionCallTool):
    @llm_function
    def request_client_information(self, question_description: str) -> str:
        """
        Requests client input for personal information based on a given question description.
        This method simulates requesting information from a client during test scenarios.
        It prompts the user with a specific question about personal information based on the
        provided context.

        Args:
            question_description (str): The question or prompt to ask the client for personal information.

        Returns:
            dict: An dictionary representing a questionary schema for the user to fill out.
        """
        return json.dumps(
            {
                "question_description": question_description,
            }
        )


class RegisterClient(FunctionCallTool):
    @llm_function
    def register_client(self, name: str, email: str) -> str:
        """
        Requests human input for personal information based on a given question description.
        This method simulates requesting information from a human user during test scenarios.
        It prompts the user with a specific question about personal information based on the
        provided context.

        Args:
            name (str): user's full name.
            email (str): user's email address.

        Returns:
            str: A message confirming that the user has been registered.
        """

        return f"user {name}, email {email} has been registered."


user_info_extract_system_message = """
"You are a strict validator designed to check whether a given input contains a user's full name and email address. Your task is to analyze the input and determine if both a full name (first and last name) and a valid email address are present.

### Validation Criteria:
- **Full Name**: The input should contain at least two words that resemble a first and last name. Ignore common placeholders (e.g., 'John Doe').
- **Email Address**: The input should include a valid email format (e.g., example@domain.com).
- **Case Insensitivity**: Email validation should be case insensitive.
- **Accuracy**: Avoid false positives by ensuring random text, usernames, or partial names don’t trigger validation.
- **Output**: Respond with Valid if both a full name and an email are present, otherwise respond with Invalid. Optionally, provide a reason why the input is invalid.
### Example Responses:
- **Input**: "John Smith, john.smith@email.com" → **Output**: "Valid"
- **Input**: "john.smith@email.com" → **Output**: "Invalid - Full name is missing"
- **Input**: "John" → **Output**: "Invalid - Full name and email are missing"

Strictly follow these validation rules and do not assume missing details."
"""


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_kyc_assistant() -> None:
    invoke_context = get_invoke_context()

    assistant = (
        KycAssistant.builder()
        .name("SimpleHITLAssistant")
        .api_key(api_key)
        .user_info_extract_system_message(user_info_extract_system_message)
        .action_llm_system_message(
            "Select the most appropriate tool based on the request."
        )
        .summary_llm_system_message("Response to user with result of registering.")
        .hitl_request(ClientInfo(name="request_human_information"))
        .register_request(RegisterClient(name="register_client"))
        .build()
    )

    # Test the run method
    input_data = [
        Message(
            role="user",
            content="Hello, this is craig. I want to register the gym. can you help me?",
        )
    ]

    output = assistant.invoke(invoke_context, input_data)

    print(output)

    human_input = [
        Message(
            role="user",
            content="My full name is Craig Li, and my email address is: craig@binome.dev",
        )
    ]

    output = assistant.invoke(invoke_context, human_input)

    print(output)


test_kyc_assistant()
