from typing import TypeVar

from pydantic import BaseModel

from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen


class Command(BaseModel):
    """
    A class representing a command in the agent.

    This class defines the interface for all commands. Each specific command should
    inherit from this class and implement its methods.
    """

    def execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Messages:
        """
        Execute the command.

        This method should be implemented by all subclasses to define
        the specific behavior of each command.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    async def a_execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:
        """
        Execute the command asynchronously.

        This method should be implemented by all subclasses to define
        the specific behavior of each command.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def to_dict(self) -> dict:
        """Convert the command to a dictionary."""
        raise NotImplementedError("Subclasses must implement this method.")


T_C = TypeVar("T_C", bound=Command)


class CommandBuilder(BaseBuilder[T_C]):
    """Inner builder class for Assistant construction."""

    def build(self) -> T_C:
        """Build the AssistantBase instance."""
        return self._obj
