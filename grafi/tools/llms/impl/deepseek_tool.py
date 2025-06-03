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
from typing import Generator
from typing import List
from typing import Optional
from typing import Self
from typing import Union
from typing import cast

from deprecated import deprecated
from openai import AsyncClient
from openai import NotGiven
from openai import OpenAI
from openai import OpenAIError
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from pydantic import Field

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_a_stream import record_tool_a_stream
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.decorators.record_tool_stream import record_tool_stream
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.llms.llm import LLM


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

    chat_params: Dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Builder (mirrors OpenAITool.Builder)                               #
    # ------------------------------------------------------------------ #
    class Builder(LLM.Builder):
        _tool: "DeepseekTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "DeepseekTool":
            return DeepseekTool.model_construct()

        def api_key(self, api_key: Optional[str]) -> Self:
            self._tool.api_key = api_key
            return self

        def model(self, model: str) -> Self:
            self._tool.model = model
            return self

        def base_url(self, base_url: str) -> Self:
            self._tool.base_url = base_url.rstrip("/")
            return self

        def build(self) -> "DeepseekTool":
            if not self._tool.api_key:
                raise ValueError("API key must be set for DeepseekTool")
            return self._tool

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

        api_tools = (
            input_data[-1].tools if input_data and input_data[-1].tools else None
        )
        return api_messages, api_tools

    # ------------------------------------------------------------------ #
    # Blocking call                                                      #
    # ------------------------------------------------------------------ #
    @record_tool_execution
    def execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Messages:
        messages, tools = self.prepare_api_input(input_data)

        try:
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            resp: ChatCompletion = client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                **self.chat_params,
            )
            return self.to_messages(resp)
        except Exception as exc:
            raise RuntimeError(f"DeepSeek API error: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Async call                                                         #
    # ------------------------------------------------------------------ #
    @record_tool_a_execution
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:
        messages, tools = self.prepare_api_input(input_data)

        async with AsyncClient(api_key=self.api_key, base_url=self.base_url) as client:
            try:
                resp: ChatCompletion = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    **self.chat_params,
                )
            except asyncio.CancelledError:
                raise
            except OpenAIError as exc:
                raise RuntimeError(f"DeepSeek async call failed: {exc}") from exc

        yield self.to_messages(resp)

    # ------------------------------------------------------------------ #
    # Blocking streaming (kept for parity)                               #
    # ------------------------------------------------------------------ #
    @record_tool_stream
    @deprecated("Use a_stream() instead for streaming functionality")
    def stream(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Generator[Messages, None, None]:
        messages, tools = self.prepare_api_input(input_data)
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        for chunk in client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=True,
            **self.chat_params,
        ):
            yield self.to_stream_messages(chunk)

    # ------------------------------------------------------------------ #
    # Async streaming                                                    #
    # ------------------------------------------------------------------ #
    @record_tool_a_stream
    async def a_stream(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:
        messages, tools = self.prepare_api_input(input_data)
        client = AsyncClient(api_key=self.api_key, base_url=self.base_url)

        async for chunk in await client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=True,
            **self.chat_params,
        ):
            yield self.to_stream_messages(chunk)

    # ------------------------------------------------------------------ #
    # Response converters                                                #
    # ------------------------------------------------------------------ #
    def to_stream_messages(self, chunk: ChatCompletionChunk) -> Messages:
        choice = chunk.choices[0]
        delta = choice.delta
        data = delta.model_dump()
        if data.get("role") is None:
            data["role"] = "assistant"
        return [Message.model_validate(data)]

    def to_messages(self, resp: ChatCompletion) -> Messages:
        return [Message.model_validate(resp.choices[0].message.model_dump())]

    # ------------------------------------------------------------------ #
    # Serialisation helper                                               #
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "api_key": "****************",
            "model": self.model,
            "base_url": self.base_url,
        }
