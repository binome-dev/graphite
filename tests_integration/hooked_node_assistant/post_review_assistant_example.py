import asyncio
import os
import uuid

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import GrafiRuntime
from grafi.runtime.execution_services import bind_services
from tests_integration.hooked_node_assistant.post_review_assistant import (
    AnnouncementReviewAssistant,
)

runtime = GrafiRuntime()
event_store = runtime.services.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_invoke_context(
    conversation_id: str, assistant_request_id: str
) -> InvokeContext:
    return InvokeContext(
        conversation_id=conversation_id,
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=assistant_request_id,
    )


async def test_draft_approved_releases_exact_reviewed_text() -> None:
    conversation_id = "test_conversation_id_review_approve"
    assistant_request_id = "test_assistant_request_id_review_approve"

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    assistant = (
        AnnouncementReviewAssistant.builder()
        .name("AnnouncementReviewAssistant")
        .api_key(api_key)
        .build()
    )

    # Draft the announcement -- the post-hook pauses it for editorial review.
    input_data = [
        Message(
            role="user",
            content="We are opening a new office in Amsterdam on March 1st.",
        )
    ]

    output = await async_func_wrapper(
        assistant.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=input_data,
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    reviewed_draft = output[0].data[-1].content
    assert isinstance(reviewed_draft, str)
    assert len(reviewed_draft) > 0

    # Approve -- the reviewed draft is recovered from the event store and
    # released WITHOUT re-invoking the LLM.
    input_data = [
        Message(
            role="user",
            content="approve",
        )
    ]

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    output = await async_func_wrapper(
        assistant.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=input_data,
                consumed_event_ids=[event.event_id for event in output],
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    released = output[0].data[-1].content
    # Byte-for-byte equality: the store-recovered draft was released, the LLM
    # was not re-run (a fresh generation would not reproduce it exactly).
    assert released == reviewed_draft


async def test_draft_denied_forwards_feedback() -> None:
    conversation_id = "test_conversation_id_review_deny"
    assistant_request_id = "test_assistant_request_id_review_deny"

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    assistant = (
        AnnouncementReviewAssistant.builder()
        .name("AnnouncementReviewAssistant")
        .api_key(api_key)
        .build()
    )

    # Draft the announcement -- the post-hook pauses it for editorial review.
    input_data = [
        Message(
            role="user",
            content="We are opening a new office in Amsterdam on March 1st.",
        )
    ]

    output = await async_func_wrapper(
        assistant.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=input_data,
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    assert isinstance(output[0].data[-1].content, str)

    # Deny -- anything beyond a bare approval token is a denial; the
    # reviewer's feedback is forwarded instead of the draft.
    feedback = "no - too informal, do not release"
    input_data = [
        Message(
            role="user",
            content=feedback,
        )
    ]

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    output = await async_func_wrapper(
        assistant.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=input_data,
                consumed_event_ids=[event.event_id for event in output],
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    assert output[0].data[-1].tool_calls is None
    assert feedback in output[0].data[-1].content


with bind_services(runtime.services):
    asyncio.run(test_draft_approved_releases_exact_reviewed_text())
with bind_services(runtime.services):
    asyncio.run(test_draft_denied_forwards_feedback())
