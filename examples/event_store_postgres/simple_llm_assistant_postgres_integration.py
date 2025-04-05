# We will test the SimpleLLMAssistant class in this file.

import os
import uuid

from simple_llm_assistant import SimpleLLMAssistant

from grafi.common.containers.container import container
from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message

""" docker compose yaml

version: '3.8'

services:
  postgres:
    image: postgres:15
    container_name: postgres
    environment:
      POSTGRES_DB: grafi_test_db
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - ./.pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

"""

postgres_event_store = EventStorePostgres(
    db_url="postgresql://user:password@localhost:5432/grafi_test_db",
)

container.register_event_store(EventStorePostgres, postgres_event_store)

event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY")

conversation_id = uuid.uuid4().hex


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id=conversation_id,
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_simple_llm_assistant():
    execution_context = get_execution_context()
    assistant = (
        SimpleLLMAssistant.Builder()
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

    input_data = [
        Message(content="Hello, my name is Grafi, how are you doing?", role="user")
    ]
    output = assistant.execute(execution_context, input_data)

    print(output)
    assert output is not None
    events = event_store.get_conversation_events(conversation_id)
    assert len(events) == 11

    input_data = [
        Message(
            role="user",
            content="I felt stressful today. Can you help me address my stress by saying my name? It is important to me.",
        )
    ]
    output = assistant.execute(get_execution_context(), input_data)
    print(output)
    assert output is not None
    assert "Grafi" in output[0].content
    assert len(event_store.get_conversation_events(conversation_id)) == 22


test_simple_llm_assistant()
