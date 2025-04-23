from typing import Any
from typing import Dict

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import Event
from grafi.common.models.default_id import default_id
from grafi.common.models.execution_context import ExecutionContext


ASSISTANT_ID = "assistant_id"
ASSISTANT_NAME = "assistant_name"
ASSISTANT_TYPE = "assistant_type"


class AssistantEvent(Event):
    assistant_id: str = default_id
    assistant_name: str
    assistant_type: str

    def assistant_event_dict(self) -> Dict[str, Any]:
        event_context = {
            ASSISTANT_ID: self.assistant_id,
            ASSISTANT_NAME: self.assistant_name,
            ASSISTANT_TYPE: self.assistant_type,
            "execution_context": self.execution_context.model_dump(),
        }
        return {
            **self.event_dict(),
            EVENT_CONTEXT: event_context,
        }

    @classmethod
    def assistant_event_base(
        cls, assistant_event_dict: Dict[str, Any]
    ) -> "AssistantEvent":
        assistant_id = assistant_event_dict[EVENT_CONTEXT][ASSISTANT_ID]
        assistant_name = assistant_event_dict[EVENT_CONTEXT][ASSISTANT_NAME]
        assistant_type = assistant_event_dict[EVENT_CONTEXT][ASSISTANT_TYPE]
        execution_context = ExecutionContext.model_validate(
            assistant_event_dict[EVENT_CONTEXT]["execution_context"]
        )
        event_base = cls.event_base(assistant_event_dict)
        return AssistantEvent(
            event_id=event_base[0],
            event_type=event_base[1],
            timestamp=event_base[2],
            assistant_id=assistant_id,
            assistant_name=assistant_name,
            assistant_type=assistant_type,
            execution_context=execution_context,
        )
