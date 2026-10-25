from typing import Any
from typing import Callable
from typing import List
from typing import Type

from pydantic import BaseModel

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import tool_messages
from grafi.tools.tool import Tool
from grafi.tools.tool import refuse_invoke_not_returning


class Command(BaseModel):
    """How a node runs its tool: it turns the events the node consumed into the
    tool's input, and returns the tool's output.

    The base command passes the consumed messages as they are. A tool class
    names a command of its own with :func:`use_command`, as LLM tools do to read
    the conversation's history; its subclasses inherit it.
    """

    tool: Tool

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        refuse_invoke_not_returning(cls, "a command returns its tool's output")

    @classmethod
    def for_tool(cls, tool: Tool) -> "Command":
        """The command the tool's class names, else this one, for ``tool``."""
        command_class = type(tool).command_class or cls
        return command_class(tool=tool)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: List[ConsumeFromTopicEvent]
    ) -> Messages:
        tool_input = await self.get_tool_input(invoke_context, input_data)
        return tool_messages(await self.tool.invoke(invoke_context, tool_input))

    async def get_tool_input(
        self,
        invoke_context: InvokeContext,
        input_data: List[ConsumeFromTopicEvent],
    ) -> Messages:
        return [message for event in input_data for message in event.data]


def use_command(command_class: Type[Command]) -> Callable:
    """Name the command a node runs this tool class, and its subclasses, through."""

    def decorator(tool_class: Type[Tool]) -> Type[Tool]:
        tool_class.command_class = command_class
        return tool_class

    return decorator
