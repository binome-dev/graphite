import asyncio
import os
import uuid

from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import GrafiRuntime
from grafi.runtime.execution_services import bind_services
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from tests_integration.hooked_node_assistant.pre_approval_assistant import (
    RefundApprovalAssistant,
)

runtime = GrafiRuntime()
event_store = runtime.services.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


class ProcessRefund(FunctionCallTool):
    @llm_function
    def process_refund(self, order_id: str, amount: float) -> str:
        """
        Function to process a refund for an order.

        Args:
            order_id (str): The id of the order to refund.
            amount (float): The refund amount in USD.

        Returns:
            str: A confirmation message with the order id and amount.
        """
        return f"Refund of ${amount:.2f} for order {order_id} has been processed."


def get_invoke_context(
    conversation_id: str, assistant_request_id: str
) -> InvokeContext:
    return InvokeContext(
        conversation_id=conversation_id,
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=assistant_request_id,
    )


def build_assistant() -> RefundApprovalAssistant:
    return (
        RefundApprovalAssistant.builder()
        .name("RefundApprovalAssistant")
        .api_key(api_key)
        .refund_tool(ProcessRefund(name="ProcessRefund"))
        .refund_limit(500.0)
        .build()
    )


async def test_refund_approved() -> None:
    # In-limit refund: policy lets it through, the human gate pauses, and a
    # plain "approve" runs the STORED proposal recovered from the event store.
    conversation_id = "refund_conversation_id_approve"
    assistant_request_id = "refund_assistant_request_id_approve"

    invoke_context = get_invoke_context(conversation_id, assistant_request_id)
    assistant = build_assistant()

    input_data = [Message(role="user", content="Please refund order A123 for $120.")]

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
    assert len(output) > 0
    # The pause surfaces the proposal itself: the pending refund tool call.
    assert output[0].data[0].tool_calls is not None

    # Human approves with a bare token; the node recovers the stored proposal.
    invoke_context = get_invoke_context(conversation_id, assistant_request_id)

    output = await async_func_wrapper(
        assistant.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=[Message(role="user", content="approve")],
                consumed_event_ids=[event.event_id for event in output],
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    # The recovered proposal executed and the LLM summarized the confirmation.
    final_message = output[0].data[0]
    assert final_message.tool_calls is None
    assert final_message.content
    assert "refund" in str(final_message.content).lower()


async def test_refund_denied() -> None:
    # In-limit refund pauses for the human; a substantive denial reply skips
    # the tool and flows back through the LLM as the final answer.
    conversation_id = "refund_conversation_id_deny"
    assistant_request_id = "refund_assistant_request_id_deny"

    invoke_context = get_invoke_context(conversation_id, assistant_request_id)
    assistant = build_assistant()

    input_data = [Message(role="user", content="Please refund order A456 for $200.")]

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
    assert output[0].data[0].tool_calls is not None

    # Anything beyond a bare approval token is a denial (strict verdict).
    invoke_context = get_invoke_context(conversation_id, assistant_request_id)

    output = await async_func_wrapper(
        assistant.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=[
                    Message(
                        role="user",
                        content="no, the customer already used the product",
                    )
                ],
                consumed_event_ids=[event.event_id for event in output],
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    # The denial flowed back through the LLM; the refund tool never ran.
    final_message = output[0].data[0]
    assert final_message.tool_calls is None
    assert final_message.content


async def test_refund_over_limit_auto_denied() -> None:
    # Over-limit refund: SpendingLimitHook denies before the human gate, so a
    # SINGLE invoke completes with a final answer -- no pause, no reviewer.
    conversation_id = "refund_conversation_id_over_limit"
    assistant_request_id = "refund_assistant_request_id_over_limit"

    invoke_context = get_invoke_context(conversation_id, assistant_request_id)
    assistant = build_assistant()

    input_data = [Message(role="user", content="Please refund order B999 for $9000.")]

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
    # A final answer, not a pause: the policy denial already went back through
    # the LLM, so no tool call is left pending and the human was never asked.
    final_message = output[0].data[0]
    assert final_message.tool_calls is None
    assert final_message.content


with bind_services(runtime.services):
    asyncio.run(test_refund_approved())
with bind_services(runtime.services):
    asyncio.run(test_refund_denied())
with bind_services(runtime.services):
    asyncio.run(test_refund_over_limit_auto_denied())
