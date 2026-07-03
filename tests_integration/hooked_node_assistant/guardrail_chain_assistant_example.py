import asyncio
import json
import os
import re
import uuid

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.impl.hooked_node import HookedNode
from grafi.runtime import GrafiRuntime
from grafi.runtime.execution_services import bind_services
from tests_integration.hooked_node_assistant.guardrail_chain_assistant import (
    DisclaimerHook,
)
from tests_integration.hooked_node_assistant.guardrail_chain_assistant import (
    GuardrailSupportAssistant,
)
from tests_integration.hooked_node_assistant.guardrail_chain_assistant import (
    RedactPIIHook,
)

runtime = GrafiRuntime()
event_store = runtime.services.event_store

api_key = os.getenv("OPENAI_API_KEY", "")

# The raw PII the pre-hook must mask before the LLM ever sees it.
PII_MESSAGE = (
    "Hi, my email address is jane.doe@example.com and my phone number is "
    "+1 415 555 0100. Please confirm the contact details you have on file."
)


def get_invoke_context(
    conversation_id: str, assistant_request_id: str
) -> InvokeContext:
    return InvokeContext(
        conversation_id=conversation_id,
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=assistant_request_id,
    )


def assert_guardrails_applied(content: str) -> None:
    """Assert the reply carries no injected PII and ends with the disclaimer."""
    # The raw email must never leak into the reply (the LLM is asked to quote
    # the contact details on file, so a leak would surface here).
    assert "jane.doe@example.com" not in content
    # Nor the raw phone digits, under any spacing or punctuation.
    assert "4155550100" not in re.sub(r"\D", "", content)
    # The post-hook stamped the final assistant message.
    assert content.endswith(DisclaimerHook().disclaimer)


async def test_pii_redacted_and_disclaimer_appended() -> None:
    conversation_id = "guardrail_conversation_id"
    assistant_request_id = "guardrail_request_id"

    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    assistant = (
        GuardrailSupportAssistant.builder()
        .name("GuardrailSupportAssistant")
        .api_key(api_key)
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content=PII_MESSAGE)]

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
    content = str(output[-1].data[-1].content)
    assert_guardrails_applied(content)


async def test_manifest_round_trip_preserves_guardrails() -> None:
    conversation_id = "guardrail_roundtrip_conversation_id"
    assistant_request_id = "guardrail_roundtrip_request_id"

    assistant = (
        GuardrailSupportAssistant.builder()
        .name("GuardrailSupportAssistant")
        .api_key(api_key)
        .build()
    )

    # Round-trip the manifest through JSON so only serializable state survives.
    # The custom hooks reconstruct via their class-name auto-registration
    # (importing guardrail_chain_assistant above registered them).
    manifest = assistant.to_dict()
    restored = await Assistant.from_dict(json.loads(json.dumps(manifest)))

    node = restored.workflow.nodes["GuardrailLLMNode"]
    assert isinstance(node, HookedNode)
    assert len(node.pre_tool_hooks) == 1
    assert isinstance(node.pre_tool_hooks[0], RedactPIIHook)
    assert len(node.post_tool_hooks) == 1
    assert isinstance(node.post_tool_hooks[0], DisclaimerHook)

    # The api_key is masked in the manifest; the restored OpenAITool falls
    # back to the OPENAI_API_KEY environment variable (same pattern as
    # simple_function_call_assistant_deserialize_assistant_example.py).
    invoke_context = get_invoke_context(
        conversation_id,
        assistant_request_id,
    )

    input_data = [Message(role="user", content=PII_MESSAGE)]

    output = await async_func_wrapper(
        restored.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=input_data,
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    content = str(output[-1].data[-1].content)
    assert_guardrails_applied(content)


with bind_services(runtime.services):
    asyncio.run(test_pii_redacted_and_disclaimer_appended())
with bind_services(runtime.services):
    asyncio.run(test_manifest_round_trip_preserves_guardrails())
