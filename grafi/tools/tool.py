from typing import Any
from typing import Dict
from typing import Optional
from typing import Self
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen


class Tool(BaseModel):
    """
    A base class representing a tool in the agent.

    This class defines the interface for all tools. Each specific tool should
    inherit from this class and implement its methods.
    """

    tool_id: str = default_id
    name: Optional[str] = Field(default=None)
    type: Optional[str] = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> Messages:
        """
        Process the input data and return a response.

        This method should be implemented by all subclasses to define
        the specific behavior of each tool.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        yield []  # Too keep mypy happy
        raise NotImplementedError("Subclasses must implement this method.")

    def to_messages(self, response: Any) -> Messages:
        """
        Convert the tool's response to a Message object.

        Args:
            response (Any): The response generated by the tool.

        Returns:
            Message: The response converted to a Message object.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the tool instance to a dictionary representation.

        Returns:
            Dict[str, Any]: A dictionary representation of the tool.
        """
        return {
            "class": self.__class__.__name__,
            "tool_id": self.tool_id,
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
        }


T_T = TypeVar("T_T", bound="Tool")  # the Tool subclass


class ToolBuilder(BaseBuilder[T_T]):
    """Inner builder class for Tool construction."""

    def name(self, name: str) -> Self:
        self.kwargs["name"] = name
        return self

    def type(self, type_name: str) -> Self:
        self.kwargs["type"] = type_name
        return self

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        self.kwargs["oi_span_type"] = oi_span_type
        return self
