from typing import Any
from typing import Dict
from typing import Optional
from typing import Self
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field
from pydantic import PrivateAttr

from grafi.common.models.command import use_command
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.message import Messages
from grafi.tools.llms.llm_command import LLMCommand
from grafi.tools.tool import Tool
from grafi.tools.tool import ToolBuilder


@use_command(LLMCommand)
class LLM(Tool):
    system_message: Optional[str] = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.LLM
    api_key: Optional[str] = Field(
        default=None, description="API key for the LLM service."
    )
    model: str = Field(
        default="",
        description="The name of the LLM model to use (e.g., 'gpt-4o-mini').",
    )
    chat_params: Dict[str, Any] = Field(default_factory=dict)

    is_streaming: bool = Field(default=False)

    structured_output: bool = Field(
        default=False,
        description="Whether the output is structured (e.g., JSON) or unstructured (e.g., plain text).",
    )

    _function_specs: FunctionSpecs = PrivateAttr(default_factory=list)

    def add_function_specs(self, function_spec: FunctionSpecs) -> None:
        """Add function specifications to the LLM."""
        if not function_spec:
            return
        self._function_specs.extend(function_spec)

    def get_function_specs(self) -> FunctionSpecs:
        """Return the function specifications for this LLM."""
        return self._function_specs.copy()

    def prepare_api_input(self, input_data: Messages) -> Any:
        """Prepare input data for API consumption."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "system_message": self.system_message,
            "api_key": "****************",
            "model": self.model,
            "chat_params": self.chat_params,
            "is_streaming": self.is_streaming,
            "structured_output": self.structured_output,
        }


T_L = TypeVar("T_L", bound=LLM)


class LLMBuilder(ToolBuilder[T_L]):
    """Builder for LLM instances."""

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def chat_params(self, params: Dict[str, Any]) -> Self:
        self.kwargs["chat_params"] = params
        if "response_format" in params:
            self.kwargs["structured_output"] = True
        return self

    def is_streaming(self, is_streaming: bool) -> Self:
        self.kwargs["is_streaming"] = is_streaming
        return self

    def system_message(self, system_message: Optional[str]) -> Self:
        self.kwargs["system_message"] = system_message
        return self
