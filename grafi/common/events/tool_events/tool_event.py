from typing import Any
from typing import Dict

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import Event
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext


class ToolEvent(Event):
    id: str = default_id
    name: str
    type: str

    def tool_event_dict(self) -> Dict[str, Any]:
        event_context = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "invoke_context": self.invoke_context.model_dump(),
        }
        return {
            **self.event_dict(),
            EVENT_CONTEXT: event_context,
        }

    @classmethod
    def tool_event_base(cls, tool_event_dict: Dict[str, Any]) -> "ToolEvent":
        id = tool_event_dict[EVENT_CONTEXT]["id"]
        name = tool_event_dict[EVENT_CONTEXT]["name"]
        type = tool_event_dict[EVENT_CONTEXT]["type"]
        invoke_context = InvokeContext.model_validate(
            tool_event_dict[EVENT_CONTEXT]["invoke_context"]
        )
        event_base = cls.event_base(tool_event_dict)
        return ToolEvent(
            event_id=event_base[0],
            event_type=event_base[1],
            timestamp=event_base[2],
            id=id,
            name=name,
            type=type,
            invoke_context=invoke_context,
        )
