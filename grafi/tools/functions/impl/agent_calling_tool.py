import json
from typing import Any, AsyncGenerator, Callable, Dict, List

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import (
    FunctionSpec,
    ParameterSchema,
    ParametersSchema,
)
from grafi.common.models.message import Message
from grafi.tools.functions.function_tool import FunctionTool


class AgentCallingTool(FunctionTool):
    name: str = "AgentCallingTool"
    type: str = "AgentCallingTool"
    agent_name: str = None
    agent_description: str = None
    argument_description: str = None
    agent_call: Callable[[ExecutionContext, Message], Any] = None
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    class Builder(FunctionTool.Builder):
        def __init__(self):
            self._tool = self._init_tool()

        def _init_tool(self) -> "AgentCallingTool":
            return AgentCallingTool()

        def agent_name(self, agent_name: str) -> "AgentCallingTool.Builder":
            self._tool.agent_name = agent_name
            self._tool.name = agent_name
            return self

        def agent_description(
            self, agent_description: str
        ) -> "AgentCallingTool.Builder":
            self._tool.agent_description = agent_description
            return self

        def argument_description(
            self, argument_description: str
        ) -> "AgentCallingTool.Builder":
            self._tool.argument_description = argument_description
            return self

        def agent_call(self, agent_call: Callable) -> "AgentCallingTool.Builder":
            self._tool.agent_call = agent_call
            return self

        def build(self) -> "AgentCallingTool":
            self._tool.function_specs = FunctionSpec(
                name=self._tool.agent_name,
                description=self._tool.agent_description,
                parameters=ParametersSchema(
                    properties={
                        "prompt": ParameterSchema(
                            type="string",
                            description=self._tool.argument_description,
                        )
                    },
                    required=["prompt"],
                ),
            )
            return self._tool

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
            logger.warning("Agent call is None.")
            raise ValueError("Agent call is None.")

        messages: List[Message] = []
        for tool_call in input_data.tool_calls:
            if tool_call.function.name == self.agent_name:
                func = self.agent_call

                prompt = json.loads(tool_call.function.arguments)["prompt"]
                message = Message(
                    role="assistant",
                    content=prompt,
                )
                response = func(execution_context, message)

                messages.append(
                    self.to_message(
                        response=response["content"], tool_call_id=tool_call.id
                    )
                )
            else:
                logger.warning(
                    f"Function name {tool_call.function.name} does not match the registered function {self.agent_name}."
                )
                messages.append(
                    self.to_message(response=None, tool_call_id=tool_call.id)
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
            logger.warning("Agent call is None.")
            raise ValueError("Agent call is None.")

        messages: List[Message] = []
        for tool_call in input_data.tool_calls:
            if tool_call.function.name == self.agent_name:
                func = self.agent_call

                prompt = json.loads(tool_call.function.arguments)["prompt"]
                message = Message(
                    role="assistant",
                    content=prompt,
                )
                response = await func(execution_context, message)

                messages.append(
                    self.to_message(
                        response=response["content"], tool_call_id=tool_call.id
                    )
                )
            else:
                logger.warning(
                    f"Function name {input_data.tool_calls[0].function.name} does not match the registered function {self.agent_name}."
                )
                messages.append(
                    self.to_message(response=None, tool_call_id=tool_call.id)
                )

        yield messages

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the tool instance to a dictionary representation.

        Returns:
            Dict[str, Any]: A dictionary representation of the tool.
        """
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "agent_name": self.agent_name,
            "agent_description": self.agent_description,
            "argument_description": self.argument_description,
            "agent_call": self.agent_call.__dict__,
            "oi_span_type": self.oi_span_type.value,
        }
