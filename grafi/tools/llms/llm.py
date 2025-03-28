from typing import Any, AsyncGenerator, Dict, Generator, List, Union

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.tool import Tool


class LLM(Tool):
    system_message: str = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.LLM

    chat_params: Dict[str, Any] = Field(default_factory=dict)

    class Builder(Tool.Builder):
        """Concrete builder for WorkflowDag."""

        def __init__(self):
            self._tool = self._init_tool()

        def _init_tool(self) -> "LLM":
            return LLM()

        def chat_params(self, params: Dict[str, Any]) -> "Tool.Builder":
            self._tool.chat_params = params
            return self

        def system_message(self, system_message: str):
            self._tool.system_message = system_message
            return self

    def stream(
        self,
        execution_context: ExecutionContext,
        input_data: Union[Message, List[Message]],
    ) -> Generator[Message, None, None]:
        raise NotImplementedError("Subclasses must implement this method.")

    async def a_stream(
        self,
        execution_context: ExecutionContext,
        input_data: Union[Message, List[Message]],
    ) -> AsyncGenerator[Message, None]:
        raise NotImplementedError("Subclasses must implement this method.")

    def prepare_api_input(self, input_data: List[Message]) -> Any:
        """Prepare input data for API consumption."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "system_message": self.system_message,
            "oi_span_type": self.oi_span_type.value,
        }
