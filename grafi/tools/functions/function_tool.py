import inspect
import json
from typing import Any
from typing import Callable
from typing import List
from typing import Self
from typing import Union

import jsonpickle
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel

from grafi.common.decorators.record_tool_a_invoke import record_tool_a_invoke
from grafi.common.decorators.record_tool_invoke import record_tool_invoke
from grafi.common.models.command import Command
from grafi.common.models.command import use_command
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.tool import Tool
from grafi.tools.tool import ToolBuilder


OutputType = Union[BaseModel, List[BaseModel]]


@use_command(Command)
class FunctionTool(Tool):
    name: str = "FunctionTool"
    type: str = "FunctionTool"
    function: Callable[[Messages], OutputType]
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    @classmethod
    def builder(cls) -> "FunctionToolBuilder":
        """
        Return a builder for FunctionTool.

        This method allows for the construction of a FunctionTool instance with specified parameters.
        """
        return FunctionToolBuilder(cls)

    @record_tool_invoke
    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        response = self.function(input_data)

        return self.to_messages(response=response)

    @record_tool_a_invoke
    async def a_invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        response = self.function(input_data)
        if inspect.isawaitable(response):
            response = await response

        yield self.to_messages(response=response)

    def to_messages(self, response: OutputType) -> Messages:
        response_str = ""
        if isinstance(response, BaseModel):
            response_str = response.model_dump_json()
        elif isinstance(response, list) and all(
            isinstance(item, BaseModel) for item in response
        ):
            response_str = json.dumps([item.model_dump() for item in response])
        elif isinstance(response, str):
            response_str = response
        else:
            response_str = jsonpickle.encode(response)

        message_args = {"role": "function", "content": response_str}

        return [Message.model_validate(message_args)]

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the tool instance to a dictionary representation.

        Returns:
            Dict[str, Any]: A dictionary representation of the tool.
        """
        return {
            **super().to_dict(),
            "function": self.function.__name__,  # will add functionality to serialize the function later
        }


class FunctionToolBuilder(ToolBuilder[FunctionTool]):
    """Builder for FunctionTool instances."""

    def function(self, function: Callable[[Messages], OutputType]) -> Self:
        self.kwargs["function"] = function
        return self
