"""OpenAI adapter: convert provider-neutral Grafi models to OpenAI SDK types.

Keeping vendor conversion here (rather than on the core ``FunctionSpec`` model)
lets ``grafi.common.models`` stay free of the OpenAI SDK, and concentrates
OpenAI-specific knowledge in the OpenAI tool layer (Open/Closed + DIP).
"""

from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from openai.types.shared_params.function_definition import FunctionDefinition

from grafi.common.models.function_spec import FunctionSpec


def to_openai_tool(spec: FunctionSpec) -> ChatCompletionToolParam:
    """Convert a Grafi :class:`FunctionSpec` into an OpenAI tool parameter."""
    return ChatCompletionToolParam(
        type="function",
        function=FunctionDefinition(
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters.model_dump(),
        ),
    )
