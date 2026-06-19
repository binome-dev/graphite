"""
DeepseekTool – DeepSeek implementation of the OpenAI-compatible LLM tool.

DeepSeek's HTTP interface is OpenAI-compatible, so it reuses the shared
``OpenAICompatibleTool`` mechanics and only changes ``base_url`` / defaults.

Docs: https://api-docs.deepseek.com – call the API with the OpenAI SDK by
setting ``base_url="https://api.deepseek.com"``.
"""

import os
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Optional

from pydantic import Field

from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleTool
from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleToolBuilder


class DeepseekTool(OpenAICompatibleTool):
    """DeepSeek implementation of the OpenAI-compatible chat-completions tool."""

    name: str = Field(default="DeepseekTool")
    type: str = Field(default="DeepseekTool")
    api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY")
    )
    base_url: Optional[str] = Field(default="https://api.deepseek.com")
    model: str = Field(default="deepseek-chat")  # or deepseek-reasoner

    _provider_label: ClassVar[str] = "DeepSeek"

    @classmethod
    def builder(cls) -> "DeepseekToolBuilder":
        """Return a builder for DeepseekTool."""
        return DeepseekToolBuilder(cls)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "base_url": self.base_url,
        }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "DeepseekTool":
        """Create a DeepseekTool instance from a dictionary representation."""
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            cls.builder()
            .name(data.get("name", "DeepseekTool"))
            .type(data.get("type", "DeepseekTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .chat_params(data.get("chat_params", {}))
            .is_streaming(data.get("is_streaming", False))
            .system_message(data.get("system_message", ""))
            .model(data.get("model", "deepseek-chat"))
            .api_key(os.getenv("DEEPSEEK_API_KEY"))
            .base_url(data.get("base_url", "https://api.deepseek.com"))
            .build()
        )


class DeepseekToolBuilder(OpenAICompatibleToolBuilder[DeepseekTool]):
    """Builder for DeepseekTool instances."""
