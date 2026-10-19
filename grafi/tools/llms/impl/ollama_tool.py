import json
import uuid
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import Sequence

from ollama import ChatResponse
from pydantic import Field

from grafi.common.async_lifecycle import best_effort_exit
from grafi.common.async_lifecycle import owned_iterator
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.exceptions import LLMToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.runtime.deltas import emit_delta
from grafi.tools.llms.impl.openai_adapter import to_openai_tool
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm import LLMBuilder

try:
    import ollama
except ImportError:
    raise ImportError(
        "`ollama` not installed. Please install using `pip install ollama`"
    )


class OllamaTool(LLM):
    """
    A class representing the Ollama language model implementation.

    This class provides methods to interact with Ollama's API for natural language processing tasks.
    """

    name: str = Field(default="OllamaTool")
    type: str = Field(default="OllamaTool")
    api_url: str = Field(default="http://localhost:11434")
    model: str = Field(default="qwen3")

    @classmethod
    def builder(cls) -> "OllamaToolBuilder":
        """
        Return a builder for OllamaTool.

        This method allows for the construction of an OllamaTool instance with specified parameters.
        """
        return OllamaToolBuilder(cls)

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
    ) -> MsgsAGen:
        """
        Invoke a request to the Ollama API asynchronously.
        """
        api_messages, api_functions = self.prepare_api_input(input_data)
        # chat_params last, so a key it sets replaces the default.
        chat_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "tools": api_functions,
            **self.chat_params,
        }
        client = ollama.AsyncClient(self.api_url)
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
                    [message] = self.to_messages(response)
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
        yield [message]

    def to_messages(self, response: ChatResponse) -> Messages:
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

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "api_url": self.api_url,
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "OllamaTool":
        """
        Create an OllamaTool instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the OllamaTool.

        Returns:
            OllamaTool: An OllamaTool instance created from the dictionary.
        """
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            cls.builder()
            .name(data.get("name", "OllamaTool"))
            .type(data.get("type", "OllamaTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .chat_params(data.get("chat_params", {}))
            .is_streaming(data.get("is_streaming", True))
            .system_message(data.get("system_message", ""))
            .api_url(data.get("api_url", "http://localhost:11434"))
            .model(data.get("model", "qwen3"))
            .build()
        )


class OllamaToolBuilder(LLMBuilder[OllamaTool]):
    """
    Builder for OllamaTool.
    """

    def api_url(self, api_url: str) -> Self:
        self.kwargs["api_url"] = api_url
        return self
