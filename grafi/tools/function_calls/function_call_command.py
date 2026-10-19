from typing import TYPE_CHECKING
from typing import Dict
from typing import FrozenSet
from typing import List
from typing import cast

from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.tools.command import Command

if TYPE_CHECKING:
    from grafi.tools.function_calls.function_call_tool import FunctionCallTool


class FunctionCallCommand(Command):
    """Passes a function-call tool the tool calls it consumed that it answers
    and no result answers yet, each message keeping only those calls.

    A tool answers the calls to its own functions. A workflow also makes one
    function-call node on each topic carrying calls answer there, with an
    error, the calls naming a function no LLM calling there was offered
    (``offered``), so that every call reaching such a node gets a result. A node
    so set belongs to that workflow.
    """

    # By topic: the functions offered to the LLMs calling there, where this
    # node also answers the calls naming another function.
    offered: Dict[str, FrozenSet[str]] = Field(default_factory=dict)

    async def get_tool_input(
        self, _: InvokeContext, node_input: List[ConsumeFromTopicEvent]
    ) -> Messages:
        answered = {
            message.tool_call_id for event in node_input for message in event.data
        }
        own = {spec.name for spec in cast("FunctionCallTool", self.tool).function_specs}
        pending = []
        for event in node_input:
            offered = self.offered.get(event.name)
            for message in event.data:
                calls = [
                    call
                    for call in message.tool_calls or []
                    if call.id not in answered
                    and (
                        call.function.name in own
                        or (offered is not None and call.function.name not in offered)
                    )
                ]
                if calls:  # Once each, though a message came on several topics.
                    answered.update(call.id for call in calls)
                    pending.append(message.model_copy(update={"tool_calls": calls}))
        return pending
