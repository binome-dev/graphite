import os
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Optional

from pydantic import Field

from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleTool
from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleToolBuilder


class OpenAITool(OpenAICompatibleTool):
    """
    OpenAI implementation of the OpenAI-compatible chat-completions tool.

    Attributes:
        api_key (str): The API key for authenticating with OpenAI.
        model (str): The name of the OpenAI model to use (default is 'gpt-4o-mini').
    """

    name: str = Field(default="OpenAITool")
    type: str = Field(default="OpenAITool")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")

    _provider_label: ClassVar[str] = "OpenAI"

    @classmethod
    def builder(cls) -> "OpenAIToolBuilder":
        """Return a builder for OpenAITool."""
        return OpenAIToolBuilder(cls)

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "OpenAITool":
        """Create an OpenAITool instance from a dictionary representation."""
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            cls.builder()
            .name(data.get("name", "OpenAITool"))
            .type(data.get("type", "OpenAITool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .chat_params(data.get("chat_params", {}))
            .is_streaming(data.get("is_streaming", False))
            .system_message(data.get("system_message", ""))
            .api_key(os.getenv("OPENAI_API_KEY"))
            .model(data.get("model", "gpt-4o-mini"))
            .build()
        )


class OpenAIToolBuilder(OpenAICompatibleToolBuilder[OpenAITool]):
    """Builder for OpenAITool instances."""
