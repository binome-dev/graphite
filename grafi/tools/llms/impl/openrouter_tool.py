"""
OpenRouterTool - OpenRouter.ai implementation of the OpenAI-compatible LLM tool.
"""

import os
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Optional
from typing import Self

from pydantic import Field

from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleTool
from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleToolBuilder


class OpenRouterTool(OpenAICompatibleTool):
    """OpenRouter.ai implementation of the OpenAI-compatible chat-completions tool."""

    name: str = Field(default="OpenRouterTool")
    type: str = Field(default="OpenRouterTool")
    api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY")
    )
    base_url: Optional[str] = Field(default="https://openrouter.ai/api/v1")
    model: str = Field(default="openrouter/auto")  # Auto-router chooses best model

    # extra headers for leader-board visibility (optional)
    extra_headers: Dict[str, str] = Field(default_factory=dict)

    _provider_label: ClassVar[str] = "OpenRouter"
    # OpenRouter emulates the chat-completions API but not OpenAI's beta
    # parsed-completions endpoint; structured output goes through response_format
    # on the standard create call.
    _supports_beta_parse: ClassVar[bool] = False

    def _extra_create_kwargs(self) -> Dict[str, Any]:
        # OpenRouter accepts optional attribution headers on each request.
        return {"extra_headers": self.extra_headers or None}

    @classmethod
    def builder(cls) -> "OpenRouterToolBuilder":
        """Return a builder for OpenRouterTool."""
        return OpenRouterToolBuilder(cls)

    def to_dict(self) -> Dict[str, Any]:
        # base_url is serialized by OpenAICompatibleTool.to_dict.
        return {
            **super().to_dict(),
            "extra_headers": self.extra_headers,
        }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "OpenRouterTool":
        """Create an OpenRouterTool instance from a dictionary representation."""
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            cls.builder()
            .name(data.get("name", "OpenRouterTool"))
            .type(data.get("type", "OpenRouterTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .chat_params(data.get("chat_params", {}))
            .is_streaming(data.get("is_streaming", False))
            .system_message(data.get("system_message", ""))
            .api_key(os.getenv("OPENROUTER_API_KEY"))
            .model(data.get("model", "openrouter/auto"))
            .base_url(data.get("base_url", "https://openrouter.ai/api/v1"))
            .extra_headers(data.get("extra_headers", {}))
            .build()
        )


class OpenRouterToolBuilder(OpenAICompatibleToolBuilder[OpenRouterTool]):
    """Builder for OpenRouterTool instances."""

    def extra_headers(self, headers: Dict[str, str]) -> Self:
        self.kwargs["extra_headers"] = headers
        return self
