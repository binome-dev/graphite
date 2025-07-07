import json
from typing import Any
from typing import Callable
from typing import Self

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.decorators.record_tool_a_invoke import record_tool_a_invoke
from grafi.common.decorators.record_tool_invoke import record_tool_invoke
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.function_call_tool import FunctionCallToolBuilder


class AgentCallingTool(FunctionCallTool):
    name: str = "AgentCallingTool"
    type: str = "AgentCallingTool"
    agent_name: str = ""
    agent_description: str = ""
    argument_description: str = ""
    agent_call: Callable[[InvokeContext, Message], Any]
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    def model_post_init(self, _context: Any) -> None:
        self.function_specs.append(
            FunctionSpec(
                name=self.agent_name,
                description=self.agent_description,
                parameters=ParametersSchema(
                    properties={
                        "prompt": ParameterSchema(
                            type="string",
                            description=self.argument_description,
                        )
                    },
                    required=["prompt"],
                ),
            )
        )

    @classmethod
    def builder(cls) -> "AgentCallingToolBuilder":
        """
        Return a builder for AgentCallingTool.

        This method allows for the construction of an AgentCallingTool instance with specified parameters.
        """
        return AgentCallingToolBuilder(cls)

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
            logger.warning("Agent call is None.")
            raise ValueError("Agent call is None.")

        messages: Messages = []
        for tool_call in input_data[0].tool_calls if input_data[0].tool_calls else []:
            if tool_call.function.name == self.agent_name:
                func = self.agent_call

                prompt = json.loads(tool_call.function.arguments)["prompt"]
                message = Message(
                    role="assistant",
                    content=prompt,
                )
                response = func(invoke_context, message)

                messages.extend(
                    self.to_messages(
                        response=response["content"], tool_call_id=tool_call.id
                    )
                )
            else:
                logger.warning(
                    f"Function name {tool_call.function.name} does not match the registered function {self.agent_name}."
                )
                messages.extend(
                    self.to_messages(response=None, tool_call_id=tool_call.id)
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
            logger.warning("Agent call is None.")
            raise ValueError("Agent call is None.")

        messages: Messages = []
        for tool_call in input_data[0].tool_calls if input_data[0].tool_calls else []:
            if tool_call.function.name == self.agent_name:
                func = self.agent_call

                prompt = json.loads(tool_call.function.arguments)["prompt"]
                message = Message(
                    role="assistant",
                    content=prompt,
                )
                response = await func(invoke_context, message)

                messages.extend(
                    self.to_messages(
                        response=response["content"], tool_call_id=tool_call.id
                    )
                )
            else:
                logger.warning(
                    f"Function name {tool_call.function.name} does not match the registered function {self.agent_name}."
                )
                messages.extend(
                    self.to_messages(response=None, tool_call_id=tool_call.id)
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
            "agent_name": self.agent_name,
            "agent_description": self.agent_description,
            "argument_description": self.argument_description,
            "agent_call": self.agent_call.__dict__,
            "oi_span_type": self.oi_span_type.value,
        }


class AgentCallingToolBuilder(FunctionCallToolBuilder[AgentCallingTool]):
    """Builder for AgentCallingTool instances."""

    def agent_name(self, agent_name: str) -> Self:
        self.kwargs["agent_name"] = agent_name
        self.kwargs["name"] = agent_name
        return self

    def agent_description(self, agent_description: str) -> Self:
        self.kwargs["agent_description"] = agent_description
        return self

    def argument_description(self, argument_description: str) -> Self:
        self.kwargs["argument_description"] = argument_description
        return self

    def agent_call(self, agent_call: Callable) -> Self:
        self.kwargs["agent_call"] = agent_call
        return self
