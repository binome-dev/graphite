from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Optional
from typing import Self

from pydantic import Field

from grafi.common.manifest import env_secret
from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleTool
from grafi.tools.llms.impl.openai_compatible import OpenAICompatibleToolBuilder


class OpenAITool(OpenAICompatibleTool):
    """
    OpenAI implementation of the OpenAI-compatible chat-completions tool.

    Attributes:
        api_key (str): The API key for authenticating with OpenAI.
        model (str): The name of the OpenAI model to use (default is 'gpt-4o-mini').
        reasoning_effort (str): Reasoning depth for reasoning models (o-series, gpt-5).
        verbosity (str): Output verbosity control for gpt-5-class models.
    """

    name: str = Field(default="OpenAITool")
    type: str = Field(default="OpenAITool")
    api_key: Optional[str] = env_secret("OPENAI_API_KEY")
    # A small, low-cost chat model by default. Upgrade to "gpt-4.1-mini"/
    # "gpt-4.1" for harder tasks. For reasoning models (e.g. "gpt-5", "gpt-5-mini",
    # "o4-mini") set `reasoning_effort` and prefer `max_completion_tokens` over
    # `temperature`/`max_tokens` via chat_params.
    model: str = Field(default="gpt-4o-mini")
    reasoning_effort: Optional[str] = Field(
        default=None,
        description=(
            "Reasoning effort for reasoning models: 'minimal' | 'low' | 'medium' "
            "| 'high'. Only meaningful for o-series / gpt-5 models. Left off when None."
        ),
    )
    verbosity: Optional[str] = Field(
        default=None,
        description=(
            "Output verbosity for gpt-5-class models: 'low' | 'medium' | 'high'. "
            "Left off when None."
        ),
    )

    _provider_label: ClassVar[str] = "OpenAI"
    _openai_settings: ClassVar[bool] = True

    @classmethod
    def builder(cls) -> "OpenAIToolBuilder":
        """Return a builder for OpenAITool."""
        return OpenAIToolBuilder(cls)

    def _extra_create_kwargs(self) -> Dict[str, Any]:
        """Attach OpenAI-only request params when set (chat_params still wins)."""
        extra: Dict[str, Any] = {}
        if self.reasoning_effort is not None:
            extra["reasoning_effort"] = self.reasoning_effort
        if self.verbosity is not None:
            extra["verbosity"] = self.verbosity
        return extra


class OpenAIToolBuilder(OpenAICompatibleToolBuilder[OpenAITool]):
    """Builder for OpenAITool instances."""

    def reasoning_effort(self, reasoning_effort: Optional[str]) -> Self:
        """Set reasoning effort ('minimal' | 'low' | 'medium' | 'high')."""
        self.kwargs["reasoning_effort"] = reasoning_effort
        return self

    def verbosity(self, verbosity: Optional[str]) -> Self:
        """Set output verbosity ('low' | 'medium' | 'high')."""
        self.kwargs["verbosity"] = verbosity
        return self
