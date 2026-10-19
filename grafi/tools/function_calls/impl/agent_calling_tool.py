import functools
import inspect
from typing import Any
from typing import Callable
from typing import Dict
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.callable_ref import deserialize_callable
from grafi.common.callable_ref import serialize_callable
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.function_call_tool import FunctionCallToolBuilder
from grafi.tools.results import in_thread
from grafi.tools.results import is_sync


class AgentCallingTool(FunctionCallTool):
    name: str = "AgentCallingTool"
    type: str = "AgentCallingTool"
    agent_name: str = ""
    agent_description: str = ""
    argument_description: str = ""
    agent_call: Callable[[InvokeContext, Message], Any]
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    def model_post_init(self, _context: Any) -> None:
        if any(spec.name == self.agent_name for spec in self.function_specs):
            return  # A copy of a tool already set up.
        self.function_specs.append(
            FunctionSpec(
                name=self.agent_name,
                description=self.agent_description,
                parameters=ParametersSchema(
                    properties={
                        # ``type`` is an extra JSON-Schema key (ParameterSchema
                        # allows extras); validate from a dict so it is preserved
                        # without tripping the typed constructor signature.
                        "prompt": ParameterSchema.model_validate(
                            {
                                "type": "string",
                                "description": self.argument_description,
                            }
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

    async def call_function(
        self, invoke_context: InvokeContext, name: str, arguments: Dict[str, Any]
    ) -> Any:
        """Ask the agent the LLM's prompt, and return its answer's content."""
        prompt = Message(role="assistant", content=arguments["prompt"])
        call = functools.partial(self.agent_call, invoke_context, prompt)
        response = await in_thread(call) if is_sync(self.agent_call) else call()
        if inspect.isawaitable(response):
            response = await response
        return response["content"]

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
            "agent_call": serialize_callable(self.agent_call),
            "oi_span_type": self.oi_span_type.value,
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "AgentCallingTool":
        """
        Create an AgentCallingTool instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the AgentCallingTool.

        Returns:
            AgentCallingTool: An AgentCallingTool instance created from the dictionary.

        Note:
            ``agent_call`` is reconstructed (without pickle) from its import
            reference or CallableComponent config. See
            :mod:`grafi.common.callable_ref`.
        """
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            cls.builder()
            .name(data.get("name", "AgentCallingTool"))
            .type(data.get("type", "AgentCallingTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .agent_name(data.get("agent_name", ""))
            .agent_description(data.get("agent_description", ""))
            .argument_description(data.get("argument_description", ""))
            .agent_call(
                deserialize_callable(
                    data["agent_call"],
                    context=f"agent_call for '{data.get('agent_name', '')}'",
                )
            )
            .build()
        )


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
