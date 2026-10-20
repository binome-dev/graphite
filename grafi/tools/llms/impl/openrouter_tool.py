"""
OpenRouterTool - OpenRouter.ai implementation of the OpenAI-compatible LLM tool.
"""

from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Optional
from typing import Self

from pydantic import Field

from grafi.common.manifest import env_secret
from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleTool
from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleToolBuilder


class OpenRouterTool(OpenAICompatibleTool):
    """OpenRouter.ai implementation of the OpenAI-compatible chat-completions tool."""

    name: str = Field(default="OpenRouterTool")
    type: str = Field(default="OpenRouterTool")
    api_key: Optional[str] = env_secret("OPENROUTER_API_KEY")
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


class OpenRouterToolBuilder(OpenAICompatibleToolBuilder[OpenRouterTool]):
    """Builder for OpenRouterTool instances."""

    def extra_headers(self, headers: Dict[str, str]) -> Self:
        self.kwargs["extra_headers"] = headers
        return self
