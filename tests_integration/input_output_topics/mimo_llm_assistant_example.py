# We will test the MIMOLLMAssistant class in this file.

import os
import uuid

from grafi.common.containers.container import container
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.instrumentations.tracing import TracingOptions
from grafi.common.instrumentations.tracing import setup_tracing
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from tests_integration.input_output_topics.mimo_llm_assistant import MIMOLLMAssistant


container.register_tracer(setup_tracing(tracing_options=TracingOptions.IN_MEMORY))
event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_mimo_llm_assistant() -> None:
    invoke_context = get_invoke_context()
    assistant = (
        MIMOLLMAssistant.builder()
        .name("MIMOLLMAssistant")
        .system_message_greeting(
            """You are a cheerful greeter! When someone says hello, respond warmly and enthusiastically.
            Welcome them and ask how you can help them today. Keep your greeting friendly and engaging."""
        )
        .system_message_question(
            """You are a knowledgeable question answerer. When someone asks a question, provide a clear,
            helpful, and informative response. Focus on being accurate and comprehensive in your answers."""
        )
        .system_message_merge(
            """You are a smart response merger. You receive different types of responses and need to
            combine them into a single, coherent output. Merge the information smoothly and naturally,
            ensuring the final response flows well and addresses all aspects."""
        )
        .api_key(api_key)
        .build()
    )
    event_store.clear_events()

    # Test greeting input
    print("Testing greeting input...")
    greeting_input = [Message(content="Hello there! How are you?", role="user")]
    greeting_output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=get_invoke_context(),
            data=greeting_input,
        )
    )
    print(f"Greeting Output: {greeting_output}")
    assert len(greeting_output) == 2

    assert len(event_store.get_events()) == 20

    # Test question input
    print("\nTesting question input...")
    question_input = [
        Message(
            content="I have a question about artificial intelligence. What is machine learning?",
            role="user",
        )
    ]
    question_output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=get_invoke_context(),
            data=question_input,
        )
    )
    print(f"Question Output: {question_output}")
    assert len(question_output) == 2

    assert len(event_store.get_events()) == 40

    # Test mixed input (both greeting and question)
    print("\nTesting mixed input...")
    mixed_input = [
        Message(
            content="Hello! I have a question about the UK traditional food.",
            role="user",
        )
    ]
    mixed_output = assistant.invoke(
        PublishToTopicEvent(
            invoke_context=get_invoke_context(),
            data=mixed_input,
        )
    )
    print(f"Mixed Output: {mixed_output}")
    assert len(mixed_output) == 3

    assert len(event_store.get_events()) == 70


test_mimo_llm_assistant()
