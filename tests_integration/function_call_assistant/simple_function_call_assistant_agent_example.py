import os
import uuid
from typing import Any

from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.agent_calling_tool import AgentCallingTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)


api_key = os.getenv("OPENAI_API_KEY", "")

event_store = container.event_store


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def mock_agent_call_function(
    execution_context: ExecutionContext, message: Message
) -> dict[str, Any]:
    content = "Current weather is bad now"
    message = Message(role="assistant", content=content)

    return message.model_dump()


def test_simple_function_call_assistant() -> None:
    execution_context = get_execution_context()

    assistant = (
        SimpleFunctionCallAssistant.builder()
        .name("SimpleAgentCallAssistant")
        .api_key(api_key)
        .function_tool(
            AgentCallingTool.builder()
            .agent_name("weather_agent")
            .agent_description("Agent to get weather information")
            .argument_description("Question about the weather")
            .agent_call(mock_agent_call_function)
            .build()
        )
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content="Hello, how's the weather in 12345?")]

    output = assistant.execute(execution_context, input_data)
    print(output)
    assert output is not None
    assert "12345" in str(output[0].content)
    print(len(event_store.get_events()))
    assert len(event_store.get_events()) == 24


test_simple_function_call_assistant()
