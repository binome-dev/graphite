import asyncio
import os
import uuid

from simple_function_call_assistant import SimpleFunctionCallAssistant

from grafi.common.containers.container import event_store
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.functions.impl.agent_calling_tool import AgentCallingTool

api_key = os.getenv("OPENAI_API_KEY")


def get_execution_context():
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def mock_agent_call_function(
    execution_context: ExecutionContext, message: Message
):
    content = f"Current weather is bad now"
    message = Message(role="assistant", content=content)

    return message.model_dump()


async def test_simple_function_call_assistant_async():
    execution_context = get_execution_context()

    assistant = (
        SimpleFunctionCallAssistant.Builder()
        .name("SimpleAgentCallAssistant")
        .api_key(api_key)
        .function_tool(
            AgentCallingTool.Builder()
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

    if assistant.unfinished_requests:
        print(assistant.unfinished_requests)
        execution_context.assistant_request_id = assistant.unfinished_requests[0]

    output = await assistant.a_execute(execution_context, input_data)
    print(output)
    assert output is not None
    assert "12345" in output[0].content
    print(len(event_store.get_events()))
    assert len(event_store.get_events()) == 23

    assistant.generate_manifest()


asyncio.run(test_simple_function_call_assistant_async())
