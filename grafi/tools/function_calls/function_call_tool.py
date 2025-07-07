import inspect
import json
from typing import Any
from typing import Callable
from typing import Dict
from typing import Optional
from typing import Self
from typing import TypeVar

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.decorators.llm_function import llm_function
from grafi.common.decorators.record_tool_a_invoke import record_tool_a_invoke
from grafi.common.decorators.record_tool_invoke import record_tool_invoke
from grafi.common.models.command import use_command
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.tool import Tool
from grafi.tools.tool import ToolBuilder


@use_command(FunctionCallCommand)
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

    @classmethod
    def builder(cls) -> "FunctionCallToolBuilder":
        """
        Return a builder for FunctionCallTool.

        This method allows for the construction of a FunctionCallTool instance with specified parameters.
        """
        return FunctionCallToolBuilder(cls)

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

    @record_tool_invoke
    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        """
        Invoke the registered function with the given arguments.

        This method is decorated with @record_tool_invoke to log its invoke.

        Args:
            function_name (str): The name of the function to invoke.
            arguments (Dict[str, Any]): The arguments to pass to the function.

        Returns:
            Any: The result of the function invoke.

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

    @record_tool_a_invoke
    async def a_invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        """
        Invoke the registered function with the given arguments.

        This method is decorated with @record_tool_invoke to log its invoke.

        Args:
            function_name (str): The name of the function to invoke.
            arguments (Dict[str, Any]): The arguments to pass to the function.

        Returns:
            Any: The result of the function invoke.

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
            **super().to_dict(),
            "function_specs": [spec.model_dump() for spec in self.function_specs],
            "function": list(self.functions.keys()),
        }


T_F = TypeVar("T_F", bound=FunctionCallTool)


class FunctionCallToolBuilder(ToolBuilder[T_F]):
    """
    Builder for FunctionCallTool.

    This class provides a fluent interface for constructing a FunctionCallTool instance.
    It allows setting the function and building the tool.
    """

    def function(self, function: Callable) -> Self:
        if not hasattr(function, "_function_spec"):
            function = llm_function(function)

        if "functions" not in self.kwargs:
            self.kwargs["functions"] = {}
        if "function_specs" not in self.kwargs:
            self.kwargs["function_specs"] = []

        self.kwargs["functions"][function.__name__] = function
        self.kwargs["function_specs"].append(function._function_spec)  # type: ignore[attr-defined]
        return self
