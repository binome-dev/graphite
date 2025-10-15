"""
DeepseekTool – DeepSeek implementation of grafi.tools.llms.llm.LLM

DeepSeek’s HTTP interface is 100 % OpenAI‑compatible, so we reuse the
official `openai` Python SDK and simply change `base_url`.

Docs: https://api-docs.deepseek.com  – see “Your First API Call”.
The page explicitly says you can call the API with the OpenAI SDK by
setting `base_url="https://api.deepseek.com"`  :contentReference[oaicite:0]{index=0}
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import Union
from typing import cast

from openai import AsyncClient
from openai import NotGiven
from openai import OpenAIError
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from pydantic import Field

from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.exceptions import LLMToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm import LLMBuilder


class DeepseekTool(LLM):
    """
    DeepseekTool – DeepSeek implementation of grafi.tools.llms.llm.LLM
    """

    name: str = Field(default="DeepseekTool")
    type: str = Field(default="DeepseekTool")
    api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY")
    )
    base_url: str = Field(default="https://api.deepseek.com")  # SDK will append /v1
    model: str = Field(default="deepseek-chat")  # or deepseek‑reasoner

    @classmethod
    def builder(cls) -> "DeepseekToolBuilder":
        """
        Return a builder for DeepseekTool.

        This method allows for the construction of a DeepseekTool instance with specified parameters.
        """
        return DeepseekToolBuilder(cls)

    # ------------------------------------------------------------------ #
    # Shared helper to map grafi → SDK input                             #
    # ------------------------------------------------------------------ #
    def prepare_api_input(
        self, input_data: Messages
    ) -> tuple[
        List[ChatCompletionMessageParam], Union[List[ChatCompletionToolParam], NotGiven]
    ]:
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

        for m in input_data:
            api_messages.append(
                cast(
                    ChatCompletionMessageParam,
                    {
                        "name": m.name,
                        "role": m.role,
                        "content": m.content or "",
                        "tool_calls": m.tool_calls,
                        "tool_call_id": m.tool_call_id,
                    },
                )
            )

        api_tools = [
            function_spec.to_openai_tool()
            for function_spec in self.get_function_specs()
        ] or None

        return api_messages, api_tools

    # ------------------------------------------------------------------ #
    # Async call                                                         #
    # ------------------------------------------------------------------ #
    @record_tool_invoke
    async def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        api_messages, api_tools = self.prepare_api_input(input_data)
        try:
            client = AsyncClient(api_key=self.api_key, base_url=self.base_url)

            if self.is_streaming:
                async for chunk in await client.chat.completions.create(
                    model=self.model,
                    messages=api_messages,
                    tools=api_tools,
                    stream=True,
                    **self.chat_params,
                ):
                    yield self.to_stream_messages(chunk)
            else:
                req_func = (
                    client.chat.completions.create
                    if not self.structured_output
                    else client.beta.chat.completions.parse
                )
                response: ChatCompletion = await req_func(
                    model=self.model,
                    messages=api_messages,
                    tools=api_tools,
                    **self.chat_params,
                )

                yield self.to_messages(response)
        except asyncio.CancelledError:
            raise  # let caller handle
        except OpenAIError as exc:
            raise LLMToolException(
                tool_name=self.name,
                model=self.model,
                message=f"DeepSeek API streaming failed: {exc}",
                invoke_context=invoke_context,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise LLMToolException(
                tool_name=self.name,
                model=self.model,
                message=f"Unexpected error during DeepSeek streaming: {exc}",
                invoke_context=invoke_context,
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------ #
    # Response converters                                                #
    # ------------------------------------------------------------------ #
    def to_stream_messages(self, chunk: ChatCompletionChunk) -> Messages:
        choice = chunk.choices[0]
        delta = choice.delta
        data = delta.model_dump()
        if data.get("role") is None:
            data["role"] = "assistant"
        data["is_streaming"] = True
        return [Message.model_validate(data)]

    def to_messages(self, resp: ChatCompletion) -> Messages:
        return [Message.model_validate(resp.choices[0].message.model_dump())]

    # ------------------------------------------------------------------ #
    # Serialisation helper                                               #
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "base_url": self.base_url,
        }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "DeepseekTool":
        """
        Create a DeepseekTool instance from a dictionary representation.

        Args:
            data (Dict[str, Any]): A dictionary representation of the DeepseekTool.

        Returns:
            DeepseekTool: A DeepseekTool instance created from the dictionary.
        """
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            cls.builder()
            .name(data.get("name", "DeepseekTool"))
            .type(data.get("type", "DeepseekTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .chat_params(data.get("chat_params", {}))
            .is_streaming(data.get("is_streaming", False))
            .system_message(data.get("system_message", ""))
            .model(data.get("model", "deepseek-chat"))
            .api_key(os.getenv("DEEPSEEK_API_KEY"))
            .base_url(data.get("base_url", "https://api.deepseek.com"))
            .build()
        )


class DeepseekToolBuilder(LLMBuilder[DeepseekTool]):
    """Builder for DeepseekTool instances."""

    def base_url(self, base_url: str) -> Self:
        self.kwargs["base_url"] = base_url.rstrip("/")
        return self

    def api_key(self, api_key: Optional[str]) -> Self:
        self.kwargs["api_key"] = api_key
        return self
