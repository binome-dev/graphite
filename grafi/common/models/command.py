from typing import Dict
from typing import List
from typing import Type
from typing import TypeVar

from pydantic import BaseModel

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.base_builder import BaseBuilder
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

        for registered_type, command_class in TOOL_COMMAND_REGISTRY.items():
            if isinstance(tool, registered_type):
                return command_class(tool=tool)

        raise ValueError(
            f"No command registered for tool type: {type(tool)} or its parent classes"
        )

    def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: List[ConsumeFromTopicEvent],
    ) -> Messages:
        """
        Invoke the command.

        This method should be implemented by all subclasses to define
        the specific behavior of each command.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        input_data: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        """
        Invoke the command asynchronously.

        This method should be implemented by all subclasses to define
        the specific behavior of each command.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def get_tool_input(
        self,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        """
        Prepare the input for the command based on the node input and invoke context.

        This method should be implemented by all subclasses to define
        how to extract the input data for the command.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def to_dict(self) -> dict:
        """Convert the command to a dictionary."""
        raise NotImplementedError("Subclasses must implement this method.")


# Registry for tool types to command classes
TOOL_COMMAND_REGISTRY: Dict[Type[Tool], Type[Command]] = {}


def register_command(tool_type: Type[Tool]):
    """Decorator to register command classes for specific tool types."""

    def decorator(command_class: Type[Command]):
        TOOL_COMMAND_REGISTRY[tool_type] = command_class
        return command_class

    return decorator


T_C = TypeVar("T_C", bound=Command)


class CommandBuilder(BaseBuilder[T_C]):
    """Inner builder class for Assistant construction."""

    pass
