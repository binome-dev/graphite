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

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.tool import Tool


OutputType = Union[BaseModel, List[BaseModel]]


class FunctionTool(Tool):
    name: str = "FunctionTool"
    type: str = "FunctionTool"
    function: Callable[[Messages], OutputType]
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    class Builder(Tool.Builder):
        """Concrete builder for WorkflowDag."""

        _tool: "FunctionTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "FunctionTool":
            return FunctionTool.model_construct()

        def function(self, function: Callable) -> Self:
            self._tool.function = function
            return self

        def build(self) -> "FunctionTool":
            return self._tool

    @record_tool_execution
    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        response = self.function(input_data)

        return self.to_messages(response=response)

    @record_tool_a_execution
    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
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
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
            "function": self.function.__name__,
        }
