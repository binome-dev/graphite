"""Integration test: concurrent SEQUENTIAL invocations on ONE assistant instance.

Companion to ``concurrent_invocation_example.py`` (which covers the parallel
engine). Here several ``invoke(..., is_sequential=True)`` calls run concurrently
on a single ``SimpleLLMAssistant``; each must echo its own word with no
cross-talk, proving the sequential engine is per-invocation isolated too (its
ready-queue and topic queues are not shared across runs).

Requires ``OPENAI_API_KEY`` (loaded from ``.env`` at the repo root).
"""

import asyncio
import os
import uuid

from dotenv import load_dotenv

from grafi.common.containers.container import container
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from tests_integration.simple_llm_assistant.simple_llm_assistant import (
    SimpleLLMAssistant,
)

load_dotenv()

event_store = container.event_store
api_key = os.getenv("OPENAI_API_KEY", "")

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


async def _run_once(assistant: SimpleLLMAssistant, word: str) -> str:
    contents = []
    event = PublishToTopicEvent(
        invoke_context=_invoke_context(),
        data=[Message(role="user", content=word)],
    )
    async for out in assistant.invoke(event, is_sequential=True):
        for message in out.data:
            if isinstance(message.content, str):
                contents.append(message.content)
    return " ".join(contents).upper()


async def test_concurrent_sequential_invokes_are_isolated() -> None:
    assert api_key, "OPENAI_API_KEY is not set (add it to .env at the repo root)"

    await event_store.clear_events()
    assistant = (
        SimpleLLMAssistant.builder()
        .name("ConcurrentSequentialAssistant")
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

    print("Concurrent sequential invocation isolation: OK")


asyncio.run(test_concurrent_sequential_invokes_are_isolated())
