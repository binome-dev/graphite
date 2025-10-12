import base64
import inspect
import json
from typing import Any
from typing import Callable
from typing import List
from typing import Self
from typing import Union

import cloudpickle
import jsonpickle
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel

from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.exceptions import FunctionToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.command import Command
from grafi.tools.command import use_command
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
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        try:
            response = self.function(input_data)
            if inspect.isawaitable(response):
                response = await response

            yield self.to_messages(response=response)
        except Exception as e:
            raise FunctionToolException(
                tool_name=self.name,
                operation="invoke",
                message=f"Async function execution failed: {e}",
                invoke_context=invoke_context,
                cause=e,
            ) from e

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
            "function": base64.b64encode(cloudpickle.dumps(self.function)).decode(
                "utf-8"
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FunctionTool":
        """
        Create a FunctionTool instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the FunctionTool.

        Returns:
            FunctionTool: A FunctionTool instance created from the dictionary.

        Note:
            Functions cannot be fully reconstructed from serialized data as they
            contain executable code. This method creates an instance with a
            placeholder function that needs to be re-registered after deserialization.
        """
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            cls.builder()
            .name(data.get("name", "FunctionTool"))
            .type(data.get("type", "FunctionTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .function(
                cloudpickle.loads(base64.b64decode(data["function"].encode("utf-8")))
            )
            .build()
        )


class FunctionToolBuilder(ToolBuilder[FunctionTool]):
    """Builder for FunctionTool instances."""

    def function(self, function: Callable[[Messages], OutputType]) -> Self:
        self.kwargs["function"] = function
        return self
