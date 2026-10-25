from typing import TYPE_CHECKING
from typing import List
from typing import cast

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.runtime.wiring import wiring
from grafi.tools.command import Command

if TYPE_CHECKING:
    from grafi.tools.function_calls.function_call_tool import FunctionCallTool


class FunctionCallCommand(Command):
    """Passes a function-call tool the calls it should answer: those it
    consumed that no result answers yet, and that it answers, each message
    keeping only those calls.

    A tool answers the calls to the functions it offers. So that every call gets a
    result, a workflow also wires one function-call node on each topic
    carrying calls to answer, with an error, the calls naming a function no
    LLM calling there was offered (see :mod:`grafi.runtime.wiring`).
    """

    async def get_tool_input(
        self, _: InvokeContext, node_input: List[ConsumeFromTopicEvent]
    ) -> Messages:
        answered = {
            message.tool_call_id for event in node_input for message in event.data
        }
        tool = cast("FunctionCallTool", self.tool)
        answers = {spec.name for spec in tool.get_function_specs()}
        offered_by_topic = wiring(tool.tool_id).offered
        pending = []
        for event in node_input:
            offered = offered_by_topic.get(event.name)
            for message in event.data:
                calls = [
                    call
                    for call in message.tool_calls or []
                    if call.id not in answered
                    and (
                        call.function.name in answers
                        or (offered is not None and call.function.name not in offered)
                    )
                ]
                if calls:  # Once each, though a message came on several topics.
                    answered.update(call.id for call in calls)
                    pending.append(message.model_copy(update={"tool_calls": calls}))
        return pending
