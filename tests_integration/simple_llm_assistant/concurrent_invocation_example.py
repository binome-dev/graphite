"""Integration test: concurrent invocations on ONE assistant instance.

Exercises the runtime isolation work (Defect #3 / runtime Gap 00) against a real
LLM. A single ``SimpleLLMAssistant`` instance is invoked several times
concurrently, each with a distinct one-word prompt. Each response must echo its
own word and none of the others -- proving the concurrent runs do not share or
corrupt each other's runtime state (topic queues, tracker, stop flag).

API keys are read from the environment, loaded from a ``.env`` file at the repo
root (see ``.env.example``). Requires ``OPENAI_API_KEY``.
"""

import asyncio
import os
import uuid

from dotenv import load_dotenv

from grafi.common.containers.container import container
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.instrumentations.tracing import TracingOptions
from grafi.common.instrumentations.tracing import setup_tracing
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from tests_integration.simple_llm_assistant.simple_llm_assistant import (
    SimpleLLMAssistant,
)

load_dotenv()

container.register_tracer(setup_tracing(tracing_options=TracingOptions.IN_MEMORY))
event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")

# Distinct, non-overlapping words so each response is unambiguously traceable to
# the prompt that produced it (none is a substring of another).
WORDS = ["ALPHA", "BETA", "GAMMA"]

SYSTEM_MESSAGE = (
    "You are a word-echo service. Reply with ONLY the single uppercase word the "
    "user sends, and nothing else."
)


def _invoke_context() -> InvokeContext:
    request_id = uuid.uuid4().hex
    return InvokeContext(
        conversation_id=request_id,
        invoke_id=request_id,
        assistant_request_id=request_id,
    )


def _input(word: str) -> PublishToTopicEvent:
    return PublishToTopicEvent(
        invoke_context=_invoke_context(),
        data=[Message(role="user", content=word)],
    )


async def _run_once(assistant: SimpleLLMAssistant, word: str) -> str:
    """Drain one invocation's output into a single string."""
    contents = []
    async for event in assistant.invoke(_input(word), is_sequential=False):
        for message in event.data:
            if isinstance(message.content, str):
                contents.append(message.content)
    return " ".join(contents).upper()


async def test_concurrent_invokes_are_isolated() -> None:
    """One assistant instance, several concurrent invokes; each response matches
    its own prompt with no cross-talk."""
    assert api_key, "OPENAI_API_KEY is not set (add it to .env at the repo root)"

    await event_store.clear_events()

    # A single shared assistant instance drives every concurrent invocation.
    assistant = (
        SimpleLLMAssistant.builder()
        .name("ConcurrentAssistant")
        .api_key(api_key)
        .system_message(SYSTEM_MESSAGE)
        .build()
    )

    results = await asyncio.gather(*[_run_once(assistant, w) for w in WORDS])

    for word, output in zip(WORDS, results):
        others = [w for w in WORDS if w != word]
        print(f"{word} -> {output!r}")
        assert word in output, f"response for {word!r} missing its word: {output!r}"
        assert not any(
            other in output for other in others
        ), f"cross-talk in response for {word!r}: {output!r}"

    print("Concurrent invocation isolation: OK")


asyncio.run(test_concurrent_invokes_are_isolated())
