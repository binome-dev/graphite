import inspect
import json
from typing import Any
from typing import Callable
from typing import Dict
from typing import Optional
from typing import Self

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.decorators.llm_function import llm_function
from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.tool import Tool


class FunctionCallTool(Tool):
    """
    A class representing a callable function as a tool for language models.

    This class allows registering a function, retrieving its specifications,
    and executing it with given arguments. It's designed to work with
    language model function calls.

    Attributes:
        function_specs (Dict[str, Any]): Specifications of the registered function.
        function (Callable): The registered callable function.
        event_store (EventStore): The event store for logging.
        name (str): The name of the tool.
    """

    name: str = "FunctionCallTool"
    type: str = "FunctionCallTool"
    function_specs: FunctionSpecs = Field(default=[])
    functions: Dict[str, Callable] = Field(default={})
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    class Builder(Tool.Builder):
        """Concrete builder for WorkflowDag."""

        _tool: "FunctionCallTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "FunctionCallTool":
            return FunctionCallTool.model_construct()

        def function(self, function: Callable) -> Self:
            if not hasattr(function, "_function_spec"):
                function = llm_function(function)
            self._tool.functions[function.__name__] = function
            self._tool.function_specs.append(function._function_spec)
            return self

        def build(self) -> "FunctionCallTool":
            return self._tool

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        """
        Initialize the Function instance.

        Args:
            **kwargs: Additional keyword arguments.
        """
        super().__init_subclass__(**kwargs)

        # subclasses are free to skip discovery (use the builder instead)
        if cls is FunctionCallTool:
            return

        cls.functions = {}
        cls.function_specs = []
        for _, attr in cls.__dict__.items():
            if (
                getattr(attr, "_function_spec", None)
                and attr is not None
                and isinstance(attr._function_spec, FunctionSpec)
            ):
                function_spec: FunctionSpec = attr._function_spec
                cls.functions[function_spec.name] = attr
                cls.function_specs.append(function_spec)
        else:
            logger.warning(
                f"{cls.__name__}: no method decorated with @llm_function found."
            )

    def get_function_specs(self) -> FunctionSpecs:
        """
        Retrieve the specifications of the registered function.

        Returns:
            List[Dict[str, Any]]: A list containing the function specifications.
        """
        return self.function_specs

    @record_tool_execution
    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        """
        Execute the registered function with the given arguments.

        This method is decorated with @record_tool_execution to log its execution.

        Args:
            function_name (str): The name of the function to execute.
            arguments (Dict[str, Any]): The arguments to pass to the function.

        Returns:
            Any: The result of the function execution.

        Raises:
            ValueError: If the provided function_name doesn't match the registered function.
        """
        if len(input_data) > 0 and input_data[0].tool_calls is None:
            logger.warning("Function call is None.")
            raise ValueError("Function call is None.")

        messages: Messages = []

        for tool_call in input_data[0].tool_calls if input_data[0].tool_calls else []:
            if tool_call.function.name in self.functions:
                func = self.functions[tool_call.function.name]
                response = func(
                    self,
                    **json.loads(tool_call.function.arguments),
                )

                messages.extend(
                    self.to_messages(response=response, tool_call_id=tool_call.id)
                )

        return messages

    @record_tool_a_execution
    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:
        """
        Execute the registered function with the given arguments.

        This method is decorated with @record_tool_execution to log its execution.

        Args:
            function_name (str): The name of the function to execute.
            arguments (Dict[str, Any]): The arguments to pass to the function.

        Returns:
            Any: The result of the function execution.

        Raises:
            ValueError: If the provided function_name doesn't match the registered function.
        """
        if len(input_data) > 0 and input_data[0].tool_calls is None:
            logger.warning("Function call is None.")
            raise ValueError("Function call is None.")

        messages: Messages = []

        for tool_call in input_data[0].tool_calls if input_data[0].tool_calls else []:
            if tool_call.function.name in self.functions:
                func = self.functions[tool_call.function.name]
                response = func(self, **json.loads(tool_call.function.arguments))
                if inspect.isawaitable(response):
                    response = await response

                messages.extend(
                    self.to_messages(response=response, tool_call_id=tool_call.id)
                )

        yield messages

    def to_messages(self, response: Any, tool_call_id: Optional[str]) -> Messages:
        message_args = {
            "role": "tool",
            "content": response,
            "tool_call_id": tool_call_id,
        }

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
            "function_specs": [spec.model_dump() for spec in self.function_specs],
            "function": list(self.functions.keys()),
        }
