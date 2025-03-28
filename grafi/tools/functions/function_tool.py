import asyncio
import json
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.decorators.llm_function import llm_function
from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.message import Message
from grafi.tools.tool import Tool


class FunctionTool(Tool):
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

    name: str = "FunctionTool"
    type: str = "FunctionTool"
    function_specs: FunctionSpec = None
    function: Callable = None
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    class Builder(Tool.Builder):
        """Concrete builder for WorkflowDag."""

        def __init__(self):
            self._tool = self._init_tool()

        def _init_tool(self) -> "FunctionTool":
            return FunctionTool()

        def function(self, function: Callable) -> "FunctionTool.Builder":
            self._tool.function = function
            self._tool.register_function(function)
            return self

        def build(self) -> "FunctionTool":
            return self._tool

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """
        Initialize the Function instance.

        Args:
            **kwargs: Additional keyword arguments.
        """
        super().__init_subclass__(**kwargs)
        if cls.__name__ == "AgentCallingTool":
            return
        for name, attr in cls.__dict__.items():
            if callable(attr) and getattr(attr, "_function_spec", False):
                cls.function = attr
                cls.function_specs = attr._function_spec
                return

        logger.warning(
            "At least one method with @llm_function decorator must be implemented."
        )

    def register_function(self, func: Callable[..., Any]) -> None:
        """
        Register a function to be used by this Function instance.

        If the provided function is not decorated with @llm_function,
        it will be decorated automatically.

        Args:
            func (Callable[..., Any]): The function to be registered.
        """
        if (not hasattr(func, "_function_spec")) or func._function_spec is None:
            func = llm_function(func)
        self.function = func
        self.function_specs = func._function_spec

    def get_function_specs(self) -> List[Dict[str, Any]]:
        """
        Retrieve the specifications of the registered function.

        Returns:
            List[Dict[str, Any]]: A list containing the function specifications.
        """
        return self.function_specs

    @record_tool_execution
    def execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> List[Message]:
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
        if input_data.tool_calls is None:
            logger.warning("Function call is None.")
            raise ValueError("Function call is None.")

        messages: List[Message] = []

        for tool_call in input_data.tool_calls:
            if tool_call.function.name == self.function_specs.name:
                func = self.function
                response = func(
                    self,
                    **json.loads(tool_call.function.arguments),
                )

                messages.append(
                    self.to_message(response=response, tool_call_id=tool_call.id)
                )

        return messages

    @record_tool_a_execution
    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> AsyncGenerator[Message, None]:
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
        if input_data.tool_calls is None:
            logger.warning("Function call is None.")
            raise ValueError("Function call is None.")

        messages: List[Message] = []

        for tool_call in input_data.tool_calls:
            if tool_call.function.name == self.function_specs.name:
                func = self.function
                if asyncio.iscoroutinefunction(func.__wrapped__):
                    response = await func(
                        self,
                        **json.loads(tool_call.function.arguments),
                    )
                else:
                    response = func(
                        self,
                        **json.loads(tool_call.function.arguments),
                    )
                messages.append(
                    self.to_message(response=response, tool_call_id=tool_call.id)
                )

        yield messages

    def to_message(self, response: Any, tool_call_id: Optional[str]) -> Message:
        message_args = {
            "role": "tool",
            "content": response,
            "tool_call_id": tool_call_id,
        }

        return Message(**message_args)

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
            "function_specs": self.function_specs.model_dump(),
            "fuction": self.function.__class__.__name__,
        }
