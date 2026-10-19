"""Shared base for OpenAI-compatible chat-completions providers.

OpenAI, DeepSeek, and OpenRouter all speak the OpenAI chat-completions API via
the official ``openai`` SDK, differing only in endpoint/config (base URL, extra
headers, default model, API-key env var) and provider-specific error wording.
This base centralizes the identical request/response mechanics; concrete
providers specialize via a few small hooks.
"""

from typing import Any
from typing import ClassVar
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import TypeVar
from typing import Union
from typing import cast

from openai import AsyncClient
from openai import AsyncStream
from openai import Omit
from openai import OpenAIError
from openai import omit
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from pydantic import Field

from grafi.common.async_lifecycle import best_effort_exit
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


class OpenAICompatibleTool(LLM):
    """Base for providers exposed through the OpenAI chat-completions API."""

    # Human-readable provider name used in error messages.
    _provider_label: ClassVar[str] = "OpenAI-compatible"

    # Whether structured-output requests may use the OpenAI-specific
    # ``beta.chat.completions.parse`` endpoint. Providers that only emulate the
    # standard chat-completions API (e.g. OpenRouter) set this False and rely on
    # ``response_format`` in ``chat_params`` via the normal ``create`` call.
    _supports_beta_parse: ClassVar[bool] = True

    # Optional endpoint override (``None`` uses the SDK's default OpenAI base).
    base_url: Optional[str] = Field(default=None)

    def _extra_create_kwargs(self) -> Dict[str, Any]:
        """Provider-specific keyword arguments merged into every request.

        Defaults to none; OpenRouter overrides this to attach extra headers.
        """
        return {}

    def prepare_api_input(
        self, input_data: Messages
    ) -> tuple[
        List[ChatCompletionMessageParam], Union[List[ChatCompletionToolParam], Omit]
    ]:
        """Convert Grafi messages + function specs into SDK request parameters."""
        api_messages: List[ChatCompletionMessageParam] = (
            [
                cast(
                    ChatCompletionMessageParam,
                    {"role": "system", "content": self.system_message},
                )
            ]
            if self.system_message
            else []
        )

        for message in input_data:
            api_messages.append(
                cast(
                    ChatCompletionMessageParam,
                    {
                        "name": message.name,
                        "role": message.role,
                        "content": message.content or "",
                        # Their standard fields, whichever provider made them.
                        "tool_calls": self._tool_calls(message.tool_calls),
                        "tool_call_id": message.tool_call_id,
                    },
                )
            )

        api_tools = [
            to_openai_tool(function_spec) for function_spec in self.get_function_specs()
        ] or omit

        return api_messages, api_tools

    @record_tool_invoke
    async def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        api_messages, api_tools = self.prepare_api_input(input_data)

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        # ``name`` is Optional on the base Tool; concrete providers always set it,
        # but fall back to the provider label so the error always has a name.
        tool_name = self.name or self._provider_label

        # Base/provider kwargs merged with user chat_params (chat_params last, so
        # a caller-supplied key overrides rather than collides with a duplicate
        # keyword argument).
        call_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "tools": api_tools,
            **self._extra_create_kwargs(),
            **self.chat_params,
        }
        stream_options = call_kwargs.pop("stream_options", None)  # A stream's only.

        try:
            async with best_effort_exit(
                AsyncClient(**client_kwargs), f"{self._provider_label} client"
            ) as client:
                if self.structured_output and self._supports_beta_parse:
                    parsed = await client.beta.chat.completions.parse(**call_kwargs)
                    messages = self.to_messages(parsed)
                elif self.should_stream() and "audio" not in call_kwargs:
                    # Audio comes whole, so only text answers stream.
                    messages = [
                        await self._streamed(client, call_kwargs, stream_options)
                    ]
                else:
                    response = await client.chat.completions.create(**call_kwargs)
                    messages = self.to_messages(response)
        except OpenAIError as exc:
            raise LLMToolException(
                tool_name=tool_name,
                model=self.model,
                message=f"{self._provider_label} API call failed",
                invoke_context=invoke_context,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise LLMToolException(
                tool_name=tool_name,
                model=self.model,
                message=f"Unexpected error during {self._provider_label} call",
                invoke_context=invoke_context,
                cause=exc,
            ) from exc
        yield messages

    async def _streamed(
        self,
        client: AsyncClient,
        call_kwargs: Dict[str, Any],
        stream_options: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """The answer, its text emitted as deltas as it streams in.

        A tool call comes in fragments at its index: its id and name, then its
        arguments in pieces; a different id at the same index is another call.
        Providers differ in which fields they repeat in every chunk, such as
        the role, so only text and arguments are joined.
        """
        request: Dict[str, Any] = {
            **call_kwargs,
            # Its usage too, as a whole answer has, for traces.
            "stream_options": {"include_usage": True, **(stream_options or {})},
        }
        # ``**request`` (Any) defeats overload resolution on ``stream=True``.
        chunks = cast(
            AsyncStream[ChatCompletionChunk],
            await client.chat.completions.create(stream=True, **request),
        )
        text: List[str] = []
        refusal: List[str] = []
        annotations: List[Any] = []
        calls: List[Dict[str, Any]] = []
        at_index: Dict[Any, Dict[str, Any]] = {}  # The call each index builds.
        call: Optional[Dict[str, Any]]
        async with best_effort_exit(chunks, f"{self._provider_label} stream"):
            async for chunk in chunks:
                # Usage alone, or another choice: the answer is the first.
                if not chunk.choices or chunk.choices[0].index:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    emit_delta(delta.content)
                    text.append(delta.content)
                refusal.append(delta.refusal or "")
                annotations += (delta.model_extra or {}).get("annotations") or []
                for fragment in delta.tool_calls or []:
                    index = getattr(fragment, "index", None)
                    call = at_index.get(index)
                    if call is None or fragment.id not in (None, "", call["id"]):
                        call = {"id": "", "type": "function", "function": {}}
                        calls.append(call)
                        at_index[index] = call
                    call["id"] = fragment.id or call["id"]
                    function: Dict[str, Any] = call["function"]
                    if fragment.function and fragment.function.name:
                        function["name"] = fragment.function.name
                    if fragment.function and fragment.function.arguments:
                        function["arguments"] = (
                            function.get("arguments", "") + fragment.function.arguments
                        )
        return Message.model_validate(
            {
                "role": "assistant",
                "content": "".join(text) or None,
                "refusal": "".join(refusal) or None,
                "annotations": self._citations(annotations),
                "tool_calls": calls or None,
            }
        )

    def to_messages(self, response: ChatCompletion) -> Messages:
        """A response as a message: its text, refusal and tool calls."""
        message = response.choices[0].message
        data = message.model_dump(exclude={"parsed"})
        return [
            Message.model_validate(
                data
                | {
                    "annotations": self._citations(data.get("annotations")),
                    "tool_calls": self._tool_calls(message.tool_calls),
                }
            )
        ]

    @staticmethod
    def _citations(annotations: Optional[List[Any]]) -> Optional[List[Any]]:
        """The URL citations among ``annotations``, the kind a Message holds;
        some providers add others, such as files."""
        citations = [
            annotation
            for annotation in annotations or []
            if annotation.get("type") == "url_citation"
        ]
        return citations or None

    @staticmethod
    def _tool_calls(calls: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
        """Tool calls as their standard fields, or None if there are none."""
        if not calls:
            return None
        return [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in calls
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the tool, including base_url when a provider sets one.

        OpenAI (no base_url) omits the key, matching its prior manifest shape;
        DeepSeek/OpenRouter inherit base_url serialization here instead of
        repeating it.
        """
        data = super().to_dict()
        if self.base_url:
            data["base_url"] = self.base_url
        return data


T_OAC = TypeVar("T_OAC", bound=OpenAICompatibleTool)


class OpenAICompatibleToolBuilder(LLMBuilder[T_OAC]):
    """Builder for OpenAI-compatible tools."""

    def api_key(self, api_key: Optional[str]) -> Self:
        """Set the provider API key."""
        self.kwargs["api_key"] = api_key
        return self

    def base_url(self, base_url: str) -> Self:
        """Set the provider base URL (trailing slash trimmed)."""
        self.kwargs["base_url"] = base_url.rstrip("/")
        return self
