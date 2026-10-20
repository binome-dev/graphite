import json
import os
from typing import Any
from typing import Dict
from typing import Optional
from typing import Self
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field
from pydantic import PrivateAttr

from grafi.common.exceptions import LLMToolException
from grafi.common.manifest import ModelRef
from grafi.common.manifest import env_secret
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.message import Messages
from grafi.runtime.deltas import streaming
from grafi.tools.command import use_command
from grafi.tools.llms.llm_command import LLMCommand
from grafi.tools.tool import Tool
from grafi.tools.tool import ToolBuilder


@use_command(LLMCommand)
class LLM(Tool):
    """A tool that calls a language model, and yields its answer as one
    message. While a caller streams the run, it streams the answer's text too,
    as the provider produces it (see :mod:`grafi.runtime.deltas`), unless
    ``is_streaming`` is off."""

    system_message: Optional[str] = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.LLM
    api_key: Optional[str] = env_secret(description="API key for the LLM service.")
    model: str = Field(
        default="",
        description="The name of the LLM model to use (e.g., 'gpt-4o-mini').",
    )
    # Request parameters, such as ``temperature``; a pydantic model class in
    # them, such as a ``response_format``, is saved as its import path.
    chat_params: ModelRef[Dict[str, Any]] = Field(default_factory=dict)

    # Whether to stream the answer to a caller that streams the run.
    is_streaming: bool = Field(default=True)

    structured_output: bool = Field(
        default=False,
        description="Whether the output is structured (e.g., JSON) or unstructured (e.g., plain text).",
    )

    _function_specs: FunctionSpecs = PrivateAttr(default_factory=list)

    def add_function_specs(self, function_spec: FunctionSpecs) -> None:
        """Add function specifications to the LLM, deduplicated by name.

        This is idempotent: a workflow links function specs into its LLM tools
        as it is built, and one tool can be in several workflows built from
        the same nodes, so without dedup the same specs would accumulate,
        bloating prompts and confusing the model.
        """
        if not function_spec:
            return
        existing = {spec.name for spec in self._function_specs}
        for spec in function_spec:
            if spec.name not in existing:
                self._function_specs.append(spec)
                existing.add(spec.name)

    def get_function_specs(self) -> FunctionSpecs:
        """Return the function specifications for this LLM."""
        return self._function_specs.copy()

    def required_api_key(self) -> str:
        """The API key, to give an OpenAI-compatible SDK: one given none would
        read ``OPENAI_API_KEY``, another provider's key perhaps, and send it
        wherever ``base_url`` points. Without a key of its own, the tool reads
        its variable again, as it may be set after the tool was made.

        Raises:
            LLMToolException: If there is none.
        """
        var = self.secret_variable("api_key")
        key = self.api_key or (os.getenv(var) if var else None)
        if not key:
            where = f": set {var}" if var else ""
            raise LLMToolException(
                tool_name=self.name or type(self).__name__,
                model=self.model,
                message=f"{type(self).__name__} has no API key{where}.",
            )
        return key

    def should_stream(self) -> bool:
        """Whether to ask the provider for a stream: a caller streams the run,
        and ``is_streaming`` is on."""
        return self.is_streaming and streaming()

    @staticmethod
    def parse_tool_arguments(arguments: Optional[str]) -> Dict[str, Any]:
        """Parse a tool call's JSON ``arguments`` string into a dict.

        Returns ``{}`` for empty/None input or malformed JSON, so a single bad
        tool-call argument string never crashes request preparation. Shared by
        provider tools to keep tool-argument handling uniform.
        """
        if not arguments:
            return {}
        try:
            return json.loads(arguments)
        except (ValueError, TypeError):
            return {}

    def prepare_api_input(self, input_data: Messages) -> Any:
        """Prepare input data for API consumption."""
        raise NotImplementedError


T_L = TypeVar("T_L", bound=LLM)


class LLMBuilder(ToolBuilder[T_L]):
    """Builder for LLM instances."""

    def model(self, model: str) -> Self:
        """Set the LLM model identifier.

        Args:
            model: Model name (e.g., 'gpt-4', 'claude-3-opus').

        Returns:
            Self for method chaining.
        """
        self.kwargs["model"] = model
        return self

    def chat_params(self, params: Dict[str, Any]) -> Self:
        """Set additional chat completion parameters.

        Args:
            params: Dictionary of parameters (temperature, max_tokens, etc.).
                If 'response_format' is included, structured_output is enabled.

        Returns:
            Self for method chaining.
        """
        self.kwargs["chat_params"] = params
        if "response_format" in params:
            self.kwargs["structured_output"] = True
        return self

    def is_streaming(self, is_streaming: bool) -> Self:
        """Stream the answer, token by token, to a caller that streams the run
        (the default), or not.

        Args:
            is_streaming: False to send a streaming caller the whole answer only.

        Returns:
            Self for method chaining.
        """
        self.kwargs["is_streaming"] = is_streaming
        return self

    def system_message(self, system_message: Optional[str]) -> Self:
        """Set the system message for the LLM.

        Args:
            system_message: Instructions that guide the LLM's behavior.

        Returns:
            Self for method chaining.
        """
        self.kwargs["system_message"] = system_message
        return self
