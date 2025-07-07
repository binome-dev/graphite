"""
OpenRouterTool - OpenRouter.ai implementation of grafi.tools.llms.llm.LLM
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
from openai import OpenAI
from openai import OpenAIError
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from pydantic import Field

from grafi.common.decorators.record_tool_a_invoke import record_tool_a_invoke
from grafi.common.decorators.record_tool_invoke import record_tool_invoke
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm import LLMBuilder


class OpenRouterTool(LLM):
    """
    OpenRouterTool - OpenRouter.ai implementation of grafi.tools.llms.llm.LLM
    """

    name: str = Field(default="OpenRouterTool")
    type: str = Field(default="OpenRouterTool")

    api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY")
    )
    base_url: str = Field(default="https://openrouter.ai/api/v1")
    model: str = Field(default="openrouter/auto")  # Auto-router chooses best model

    # extra headers for leader-board visibility (optional)
    extra_headers: Dict[str, str] = Field(default_factory=dict)

    chat_params: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def builder(cls) -> "OpenRouterToolBuilder":
        """
        Return a builder for OpenRouterTool.

        This method allows for the construction of an OpenRouterTool instance with specified parameters.
        """
        return OpenRouterToolBuilder(cls)

    # ------------------------------------------------------------------ #
    # Request conversion helper                                          #
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

        # Extract function specifications from self.get_function_specs()
        api_tools = [
            function_spec.to_openai_tool()
            for function_spec in self.get_function_specs()
        ] or None

        return api_messages, api_tools

    # ------------------------------------------------------------------ #
    # Blocking call                                                      #
    # ------------------------------------------------------------------ #
    @record_tool_invoke
    def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> Messages:
        messages, tools = self.prepare_api_input(input_data)

        try:
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            resp: ChatCompletion = client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                extra_headers=self.extra_headers or None,
                **self.chat_params,
            )
            return self.to_messages(resp)
        except Exception as exc:
            raise RuntimeError(f"OpenRouter API error: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Async call                                                         #
    # ------------------------------------------------------------------ #
    @record_tool_a_invoke
    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        messages, tools = self.prepare_api_input(input_data)

        try:
            client = AsyncClient(api_key=self.api_key, base_url=self.base_url)

            if self.is_streaming:
                async for chunk in await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    stream=True,
                    extra_headers=self.extra_headers or None,
                    **self.chat_params,
                ):
                    yield self.to_stream_messages(chunk)
            else:
                resp: ChatCompletion = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    extra_headers=self.extra_headers or None,
                    **self.chat_params,
                )
                yield self.to_messages(resp)
        except asyncio.CancelledError:
            raise
        except OpenAIError as exc:
            raise RuntimeError(f"OpenRouter async call failed: {exc}") from exc

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
    # Serialisation                                                      #
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "base_url": self.base_url,
            "extra_headers": self.extra_headers,
        }


class OpenRouterToolBuilder(LLMBuilder[OpenRouterTool]):
    """
    Builder for OpenRouterTool.
    """

    def base_url(self, base_url: str) -> Self:
        self.kwargs["base_url"] = base_url.rstrip("/")
        return self

    def extra_headers(self, headers: Dict[str, str]) -> Self:
        self.kwargs["extra_headers"] = headers
        return self

    def api_key(self, api_key: Optional[str]) -> Self:
        self.kwargs["api_key"] = api_key
        return self
