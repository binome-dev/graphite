from abc import abstractmethod
from typing import Any
from typing import Dict
from typing import Generator
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.tool import Tool


class LLM(Tool):
    system_message: Optional[str] = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.LLM

    chat_params: Dict[str, Any] = Field(default_factory=dict)

    structured_output: bool = Field(
        default=False,
        description="Whether the output is structured (e.g., JSON) or unstructured (e.g., plain text).",
    )

    class Builder(Tool.Builder):
        """Concrete builder for LLM."""

        _tool: "LLM"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "LLM":
            return LLM.model_construct()

        def chat_params(self, params: Dict[str, Any]) -> Self:
            self._tool.chat_params = params
            if "response_format" in params:
                self._tool.structured_output = True
            return self

        def system_message(self, system_message: Optional[str]) -> Self:
            self._tool.system_message = system_message
            return self

    @abstractmethod
    def stream(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Generator[Message, None, None]:
        raise NotImplementedError("Subclasses must implement this method.")

    @abstractmethod
    async def a_stream(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:
        yield []  # Too keep mypy happy
        raise NotImplementedError("Subclasses must implement this method.")

    def prepare_api_input(self, input_data: Messages) -> Any:
        """Prepare input data for API consumption."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "system_message": self.system_message,
            "oi_span_type": self.oi_span_type.value,
        }
