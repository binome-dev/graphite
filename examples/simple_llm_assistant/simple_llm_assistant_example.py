# We will test the SimpleLLMAssistant class in this file.

import os
import uuid

from examples.simple_llm_assistant.simple_llm_assistant import SimpleLLMAssistant
from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_simple_llm_assistant() -> None:
    execution_context = get_execution_context()
    assistant = (
        SimpleLLMAssistant.builder()
        .name("SimpleLLMAssistant")
        .system_message(
            """You're a friendly and helpful assistant, always eager to make tasks easier and provide clear, supportive answers.
                You respond warmly to questions, and always call the user's name, making users feel comfortable and understood.
                If you don't have all the information, you reassure users that you're here to help them find the best answer or solution.
                Your tone is approachable and optimistic, and you aim to make each interaction enjoyable."""
        )
        .api_key(api_key)
        .build()
    )
    event_store.clear_events()

    input_data = [
        Message(content="Hello, my name is Grafi, how are you doing?", role="user")
    ]
    output = assistant.execute(execution_context, input_data)

    print(output)
    assert output is not None
    assert len(event_store.get_events()) == 11

    input_data = [
        Message(
            role="user",
            content="I felt stressful today. Can you help me address my stress by saying my name? It is important to me.",
        )
    ]
    output = assistant.execute(get_execution_context(), input_data)
    print(output)
    assert output is not None
    assert "Grafi" in str(output[0].content)
    assert len(event_store.get_events()) == 22


test_simple_llm_assistant()
