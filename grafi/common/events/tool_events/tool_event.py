from typing import Any
from typing import Dict

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import Event
from grafi.common.models.default_id import default_id
from grafi.common.models.execution_context import ExecutionContext


TOOL_ID = "tool_id"
TOOL_NAME = "tool_name"
TOOL_TYPE = "tool_type"


class ToolEvent(Event):
    tool_id: str = default_id
    tool_name: str
    tool_type: str

    def tool_event_dict(self) -> Dict[str, Any]:
        event_context = {
            TOOL_ID: self.tool_id,
            TOOL_NAME: self.tool_name,
            TOOL_TYPE: self.tool_type,
            "execution_context": self.execution_context.model_dump(),
        }
        return {
            **self.event_dict(),
            EVENT_CONTEXT: event_context,
        }

    @classmethod
    def tool_event_base(cls, tool_event_dict: Dict[str, Any]) -> "ToolEvent":
        tool_id = tool_event_dict[EVENT_CONTEXT][TOOL_ID]
        tool_name = tool_event_dict[EVENT_CONTEXT][TOOL_NAME]
        tool_type = tool_event_dict[EVENT_CONTEXT][TOOL_TYPE]
        execution_context = ExecutionContext.model_validate(
            tool_event_dict[EVENT_CONTEXT]["execution_context"]
        )
        event_base = cls.event_base(tool_event_dict)
        return ToolEvent(
            event_id=event_base[0],
            event_type=event_base[1],
            timestamp=event_base[2],
            tool_id=tool_id,
            tool_name=tool_name,
            tool_type=tool_type,
            execution_context=execution_context,
        )
