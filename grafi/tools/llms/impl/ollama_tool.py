import inspect
import json
import uuid
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import Sequence

from ollama import ChatResponse
from pydantic import Field
from pydantic import model_validator

from grafi.common.async_lifecycle import best_effort_exit
from grafi.common.async_lifecycle import owned_iterator
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.exceptions import LLMToolException
from grafi.common.manifest import env_secret
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.runtime.deltas import emit_delta
from grafi.tools.llms.impl.openai_adapter import to_openai_tool
from grafi.tools.llms.llm import _PROVIDER_REMOVED_METHODS
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm import LLMBuilder

try:
    import ollama
except ImportError:
    raise ImportError(
        "`ollama` not installed. Please install using `pip install ollama`"
    )


# The model settings ollama's chat() takes in its options, as a chat_params key.
_OPTIONS = frozenset(ollama.Options.model_fields)
# The keys chat_params may hold: chat()'s arguments, and those settings.
_CHAT_KEYS = (
    frozenset(inspect.signature(ollama.AsyncClient.chat).parameters)
    - {"self", "messages", "tools", "stream"}  # The tool's own.
) | _OPTIONS


class OllamaTool(LLM):
    """
    A class representing the Ollama language model implementation.

    This class provides methods to interact with Ollama's API for natural language processing tasks.
    """

    removed_methods: ClassVar[Dict[str, str]] = _PROVIDER_REMOVED_METHODS

    name: str = Field(default="OllamaTool")
    type: str = Field(default="OllamaTool")
    api_key: Optional[str] = env_secret("OLLAMA_API_KEY")
    api_url: str = Field(default="http://localhost:11434")
    model: str = Field(default="qwen3")

    @classmethod
    def builder(cls) -> "OllamaToolBuilder":
        """
        Return a builder for OllamaTool.

        This method allows for the construction of an OllamaTool instance with specified parameters.
        """
        return OllamaToolBuilder(cls)

    @model_validator(mode="after")
    def _known_chat_params(self) -> Self:
        """A key ollama's chat() takes neither as an argument nor as an option,
        such as OpenAI's max_tokens, is refused when the tool is made."""
        unknown = sorted(set(self.chat_params) - _CHAT_KEYS)
        if unknown:
            raise ValueError(
                f"OllamaTool.chat_params holds {unknown}, which ollama's chat() "
                "takes neither as an argument nor as an option, or the tool "
                "sets itself (messages, tools, stream); max_tokens is "
                "num_predict, and an option the server takes that "
                'ollama.Options does not name goes in chat_params={"options": '
                "{...}}."
            )
        return self

    def _chat_params(self) -> Dict[str, Any]:
        """``chat_params`` as ``chat()`` takes them: a model setting, such as
        ``temperature``, in its ``options``, where one given there replaces
        it; any other key as an argument (unknown keys are refused when the
        tool is made)."""
        params = dict(self.chat_params)
        options = {k: params.pop(k) for k in list(params) if k in _OPTIONS}
        given = params.get("options") or {}
        if isinstance(given, ollama.Options):
            given = given.model_dump(exclude_none=True)
        if options:
            params["options"] = {**options, **given}
        return params

    def prepare_api_input(
        self, input_data: Messages
    ) -> tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
        api_messages: List[Dict[str, Any]] = (
            [{"role": "system", "content": self.system_message}]
            if self.system_message
            else []
        )
        api_functions = None

        # A tool result names its function: the call with its id did. Ollama
        # gives calls no ids, so it matches results to calls by name and order.
        call_names: Dict[str, str] = {}
        for message in input_data:
            api_message = {
                "role": "tool" if message.role == "function" else message.role,
                "content": message.content or "",
            }
            if message.tool_call_id in call_names:
                api_message["tool_name"] = call_names[message.tool_call_id]
            for call in message.tool_calls or []:
                call_names[call.id] = call.function.name
            if message.tool_calls:
                # grafi stores assistant tool calls in `tool_calls`; forward them
                # so multi-turn function calling survives (the deprecated
                # `function_call` field is handled below for backward compat).
                api_message["tool_calls"] = [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": self.parse_tool_arguments(
                                tc.function.arguments
                            ),
                        }
                    }
                    for tc in message.tool_calls
                ]
            elif message.function_call:
                api_message["tool_calls"] = [
                    {
                        "function": {
                            "name": message.function_call.name,
                            "arguments": json.loads(message.function_call.arguments),
                        }
                    }
                ]
            api_messages.append(api_message)

        # Extract function specifications from self.get_function_specs()
        api_functions = [
            to_openai_tool(function_spec) for function_spec in self.get_function_specs()
        ] or None

        return api_messages, api_functions

    @record_tool_invoke
    async def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> Messages:
        """
        Invoke a request to the Ollama API asynchronously.
        """
        api_messages, api_functions = self.prepare_api_input(input_data)
        # chat_params last, so a key it sets replaces the default.
        chat_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "tools": api_functions,
            **self._chat_params(),
        }
        # Its own key, if any: the SDK would read OLLAMA_API_KEY otherwise. A
        # local Ollama takes none; one read from another variable is required.
        key = self.sdk_api_key(required=False)
        headers = {"authorization": f"Bearer {key}"} if key else {}
        client = ollama.AsyncClient(self.api_url, headers=headers)
        # Created per call, so closed per call.
        async with best_effort_exit(client, "Ollama client"):
            try:
                if self.should_stream():
                    text: List[str] = []
                    tool_calls: List[Any] = []
                    stream = await client.chat(**{**chat_kwargs, "stream": True})
                    async with owned_iterator(
                        stream, best_effort="Ollama stream"
                    ) as chunks:
                        async for chunk in chunks:
                            if content := chunk.message.content:
                                emit_delta(content)
                                text.append(content)
                            tool_calls.extend(chunk.message.tool_calls or [])
                    message = self._message("".join(text), tool_calls)
                else:
                    response = await client.chat(**chat_kwargs)
                    [message] = self._to_messages(response)
            except Exception as e:
                # The lifecycle decorator emits the authoritative record; raise a
                # domain error with a stable message and the original cause attached.
                raise LLMToolException(
                    tool_name=self.name,
                    model=self.model,
                    message="Ollama async call failed",
                    invoke_context=invoke_context,
                    cause=e,
                ) from e
        return [message]

    def _to_messages(self, response: ChatResponse) -> Messages:
        """A response as a message: its text, and its tool calls if any."""
        return [
            self._message(
                response.message.content or "", response.message.tool_calls or []
            )
        ]

    @staticmethod
    def _message(text: str, raw_tool_calls: Sequence[Any]) -> Message:
        tool_calls = [
            {
                "id": uuid.uuid4().hex,  # Ollama gives tool calls no id.
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": json.dumps(call.function.arguments),
                },
            }
            for call in raw_tool_calls
        ]
        return Message.model_validate(
            {"role": "assistant", "content": text, "tool_calls": tool_calls or None}
        )


class OllamaToolBuilder(LLMBuilder[OllamaTool]):
    """
    Builder for OllamaTool.
    """

    def api_url(self, api_url: str) -> Self:
        self.kwargs["api_url"] = api_url
        return self
