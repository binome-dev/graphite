from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Type

from pydantic import BaseModel

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.tool import Tool


class Command(BaseModel):
    """
    A class representing a command in the agent.

    This class defines the interface for all commands. Each specific command should
    inherit from this class and implement its methods.
    """

    tool: Tool

    @classmethod
    def for_tool(cls, tool: Tool) -> "Command":
        """Factory method to create appropriate command for a tool."""
        tool_type = type(tool)

        # First, try to find exact match
        if tool_type in TOOL_COMMAND_REGISTRY:
            command_class = TOOL_COMMAND_REGISTRY[tool_type]
            return command_class(tool=tool)

        # If no exact match, look for parent class matches
        for registered_type, command_class in TOOL_COMMAND_REGISTRY.items():
            if isinstance(tool, registered_type):
                return command_class(tool=tool)

        # If no command found, return the base Command class
        return cls(tool=tool)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: List[ConsumeFromTopicEvent]
    ) -> MsgsAGen:
        tool_input = await self.get_tool_input(invoke_context, input_data)
        async for messages in self.tool.invoke(invoke_context, tool_input):
            yield messages

    async def get_tool_input(
        self,
        invoke_context: InvokeContext,
        input_data: List[ConsumeFromTopicEvent],
    ) -> Messages:
        all_messages = []
        for event in input_data:
            all_messages.extend(event.data)
        return all_messages

    def to_dict(self) -> dict[str, Any]:
        return {"class": self.__class__.__name__}

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "Command":
        """
        Create a command instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the command.

        Returns:
            Command: A command instance created from the dictionary.

        Note:
            This base implementation returns a Command instance without a tool.
            Subclasses should override this method if they need to reconstruct
            the tool from the dictionary data.
        """
        # Base Command doesn't serialize tool, so we can't reconstruct it
        # Subclasses should override this if they need tool reconstruction
        raise NotImplementedError(
            "from_dict must be implemented by subclasses that need tool reconstruction"
        )


# Registry for tool types to command classes
TOOL_COMMAND_REGISTRY: Dict[Type[Tool], Type[Command]] = {}


def use_command(command_class: Type[Command]) -> Callable:
    """Decorator to register which command class a tool should use."""

    def decorator(tool_class: Type[Tool]) -> Type[Tool]:
        TOOL_COMMAND_REGISTRY[tool_class] = command_class
        return tool_class

    return decorator
