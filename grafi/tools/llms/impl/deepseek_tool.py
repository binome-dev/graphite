"""
DeepseekTool – DeepSeek implementation of the OpenAI-compatible LLM tool.

DeepSeek's HTTP interface is OpenAI-compatible, so it reuses the shared
``OpenAICompatibleTool`` mechanics and only changes ``base_url`` / defaults.

Docs: https://api-docs.deepseek.com – call the API with the OpenAI SDK by
setting ``base_url="https://api.deepseek.com"``.
"""

from typing import ClassVar
from typing import Optional

from pydantic import Field

from grafi.common.manifest import env_secret
from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleTool
from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleToolBuilder


class DeepseekTool(OpenAICompatibleTool):
    """DeepSeek implementation of the OpenAI-compatible chat-completions tool."""

    name: str = Field(default="DeepseekTool")
    type: str = Field(default="DeepseekTool")
    api_key: Optional[str] = env_secret("DEEPSEEK_API_KEY")
    base_url: Optional[str] = Field(default="https://api.deepseek.com")
    model: str = Field(default="deepseek-chat")  # or deepseek-reasoner

    _provider_label: ClassVar[str] = "DeepSeek"

    @classmethod
    def builder(cls) -> "DeepseekToolBuilder":
        """Return a builder for DeepseekTool."""
        return DeepseekToolBuilder(cls)


class DeepseekToolBuilder(OpenAICompatibleToolBuilder[DeepseekTool]):
    """Builder for DeepseekTool instances."""
