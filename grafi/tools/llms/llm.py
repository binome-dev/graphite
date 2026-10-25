import json
from typing import Any
from typing import Dict
from typing import Literal
from typing import Optional
from typing import Self
from typing import TypeVar
from typing import overload

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.exceptions import LLMToolException
from grafi.common.legacy import warn_never_called
from grafi.common.manifest import ModelRef
from grafi.common.manifest import SecretInput
from grafi.common.manifest import env_secret
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.function_spec import GivenSpecs
from grafi.common.models.function_spec import once_each
from grafi.common.models.message import Messages
from grafi.runtime.deltas import streaming
from grafi.runtime.wiring import wiring
from grafi.tools.command import use_command
from grafi.tools.llms.llm_command import LLMCommand
from grafi.tools.tool import Tool
from grafi.tools.tool import ToolBuilder

# The methods grafi's provider tools called in 0.0.36 and earlier, in their
# invoke, which they no longer have: their removed_methods.
_PROVIDER_REMOVED_METHODS: Dict[str, str] = {
    name: "a provider makes its answer in invoke(), streamed or not: "
    "post-process the answer by overriding invoke(), decorated with "
    "@record_tool_invoke, calling super().invoke(); build the tool with "
    ".is_streaming(False) to keep the raw text from streaming."
    for name in ("to_messages", "to_stream_messages")
}

# Methods of an LLM that grafi called as hooks in 0.0.36, and no longer does.
_HOOKS_NEVER_CALLED = {
    "add_function_specs": "a workflow no longer gives an LLM its functions "
    "with it. Read those it is offered with self.get_function_specs() in "
    "invoke(), where its step binds them (to a copy of the tool too), or "
    "workflow.offered_to(node_name) beforehand.",
}


@use_command(LLMCommand)
class LLM(Tool):
    """A tool that calls a language model, and returns its answer as one
    message. While a caller streams the run, it streams the answer's text too,
    as the provider produces it (see :mod:`grafi.runtime.deltas`), unless
    ``is_streaming`` is off."""

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        warn_never_called(cls, LLM, lambda _: _HOOKS_NEVER_CALLED)

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

    # The specs of functions it is offered besides those its workflow wires
    # to it, such as those whose calls the app answers itself.
    function_specs: GivenSpecs = Field(
        default_factory=list, exclude_if=lambda specs: not specs
    )

    @overload
    def sdk_api_key(self, *, required: Literal[True] = True) -> str: ...

    @overload
    def sdk_api_key(self, *, required: bool) -> Optional[str]: ...

    def sdk_api_key(self, *, required: bool = True) -> Optional[str]:
        """The API key to give the provider's SDK: the one it holds (read from
        its variable when the tool was made, or given in code); else, holding
        none, its variable's, read now (see ``Component.secret_value``).

        It is ``required`` where the SDK, given none, would read a variable
        other than the tool's own, as an OpenAI-compatible SDK reads
        ``OPENAI_API_KEY`` whatever the provider. Where it reads only its
        provider's credentials (Claude's, Gemini's, Ollama's), pass
        ``required=False``; a key read from another variable than the tool's
        own, a tenant's, is required still.

        Raises:
            LLMToolException: If it has none, naming the variable to set, or
                holds what is not a key.
        """
        try:
            return self.secret_value("api_key", required=required)
        except (ValueError, TypeError) as error:
            raise LLMToolException(
                tool_name=self.name or type(self).__name__,
                model=self.model,
                message=str(error),
            ) from error

    def add_function_specs(self, function_spec: FunctionSpecs) -> None:
        """Add function specifications to the LLM's ``function_specs``, once
        each by name: functions it is offered beside those its workflow wires
        to it, whose calls the app answers. A workflow does not call it."""
        self.function_specs = once_each([*self.function_specs, *(function_spec or [])])

    def get_function_specs(self) -> FunctionSpecs:
        """The functions the LLM is offered: in a step of its node, those its
        workflow wires to it, of the function-call nodes reading its calls
        (see :mod:`grafi.runtime.wiring` and ``EventDrivenWorkflow.offered_to``),
        which answer them; then its ``function_specs``; once each by name. A
        provider reads them here, in its invoke."""
        return once_each([*wiring(self.tool_id).functions, *self.function_specs])

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

    def api_key(self, api_key: SecretInput) -> Self:
        """Set the API key, or the variable to read it from, ``{"env":
        "VAR"}``, as ``secret_reference()`` gives it: one read from a variable
        is saved as that variable; saving any other raises (see
        :func:`~grafi.common.manifest.env_secret`)."""
        self.kwargs["api_key"] = api_key
        return self

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
