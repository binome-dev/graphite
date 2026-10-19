from typing import Any
from typing import Callable
from typing import List
from typing import Type

from pydantic import BaseModel

from grafi.common.async_lifecycle import owned_iterator
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.tool import Tool


class Command(BaseModel):
    """How a node runs its tool: it turns the events the node consumed into the
    tool's input, then streams the tool's output.

    The base command passes the consumed messages as they are. A tool class
    names a command of its own with :func:`use_command`, as LLM tools do to read
    the conversation's history; its subclasses inherit it.
    """

    tool: Tool

    @classmethod
    def for_tool(cls, tool: Tool) -> "Command":
        """The command the tool's class names, else this one, for ``tool``."""
        command_class = type(tool).command_class or cls
        return command_class(tool=tool)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: List[ConsumeFromTopicEvent]
    ) -> MsgsAGen:
        tool_input = await self.get_tool_input(invoke_context, input_data)
        async with owned_iterator(
            self.tool.invoke(invoke_context, tool_input)
        ) as stream:
            async for messages in stream:
                yield messages

    async def get_tool_input(
        self,
        invoke_context: InvokeContext,
        input_data: List[ConsumeFromTopicEvent],
    ) -> Messages:
        return [message for event in input_data for message in event.data]

    def to_dict(self) -> dict[str, Any]:
        return {"class": self.__class__.__name__}


def use_command(command_class: Type[Command]) -> Callable:
    """Name the command a node runs this tool class, and its subclasses, through."""

    def decorator(tool_class: Type[Tool]) -> Type[Tool]:
        tool_class.command_class = command_class
        return tool_class

    return decorator
