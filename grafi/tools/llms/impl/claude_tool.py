"""
ClaudeTool - Anthropic Claude implementation of grafi.tools.llms.llm.LLM
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from typing import Dict
from typing import Generator
from typing import List
from typing import Optional
from typing import Self
from typing import Union

from deprecated import deprecated
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


try:
    from anthropic import NOT_GIVEN
    from anthropic import Anthropic
    from anthropic import AsyncAnthropic
    from anthropic import NotGiven
    from anthropic.types import Message as AnthropicMessage
    from anthropic.types import MessageParam
    from anthropic.types import ToolParam
    from anthropic.types.text_block import TextBlock
    from anthropic.types.tool_use_block import ToolUseBlock
except ImportError:
    raise ImportError(
        "`anthropic` not installed. Please install using `pip install anthropic`"
    )


class ClaudeTool(LLM):
    """
    Anthropic Claude implementation of the LLM tool interface used by *grafi*.
    """

    name: str = Field(default="ClaudeTool")
    type: str = Field(default="ClaudeTool")
    api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY")
    )
    max_tokens: int = Field(default=4096)
    model: str = Field(default="claude-3-5-haiku-20241022")  # or haiku, opus…

    chat_params: Dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Builder (fluent)                                                   #
    # ------------------------------------------------------------------ #
    class Builder(LLM.Builder):
        _tool: "ClaudeTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "ClaudeTool":
            return ClaudeTool.model_construct()

        def api_key(self, api_key: Optional[str]) -> Self:
            self._tool.api_key = api_key
            return self

        def max_tokens(self, max_tokens: int) -> Self:
            self._tool.max_tokens = max_tokens
            return self

        def model(self, model: str) -> Self:
            self._tool.model = model
            return self

        def build(self) -> "ClaudeTool":
            if not self._tool.api_key:
                raise ValueError("API key must be set for ClaudeTool.")
            return self._tool

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _client(self) -> Anthropic:
        return Anthropic(api_key=self.api_key)

    def prepare_api_input(
        self, input_data: Messages
    ) -> tuple[List[MessageParam], Union[List[ToolParam], NotGiven]]:
        """grafi → Anthropic message list (& optional tools)."""
        messages: List[MessageParam] = []

        if self.system_message:
            messages.append({"role": "system", "content": self.system_message})

        for m in input_data:
            if m.content is not None and isinstance(m.content, str) and m.content != "":
                messages.append(
                    {
                        "role": "user" if m.role == "tool" else m.role,
                        "content": m.content or "",
                    }
                )

        tools: List[ToolParam] = []
        if input_data and input_data[-1].tools:
            for tool in input_data[-1].tools:
                function = tool.get("function")
                if function is not None:
                    tools.append(
                        {
                            "name": function["name"],
                            "description": function["description"],
                            "input_schema": function["parameters"],
                        }
                    )
        return messages, tools or NOT_GIVEN

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

        client = self._client()
        try:
            resp: AnthropicMessage = client.messages.create(
                max_tokens=self.max_tokens,
                model=self.model,
                messages=messages,
                tools=tools,  # None is fine here
                **self.chat_params,
            )
        except Exception as exc:
            raise RuntimeError(f"Anthropic API error: {exc}") from exc

        return self.to_messages(resp)

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
        client = AsyncAnthropic(api_key=self.api_key)

        try:
            resp: AnthropicMessage = await client.messages.create(
                max_tokens=self.max_tokens,
                model=self.model,
                messages=messages,
                tools=tools,
                **self.chat_params,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Anthropic async call failed: {exc}") from exc

        yield self.to_messages(resp)

    # ------------------------------------------------------------------ #
    # Blocking streaming (deprecated wrapper)                            #
    # ------------------------------------------------------------------ #
    @record_tool_stream
    @deprecated("Use a_stream() instead for streaming functionality")
    def stream(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Generator[Messages, None, None]:
        messages, tools = self.prepare_api_input(input_data)
        client = self._client()

        with client.messages.stream(
            max_tokens=self.max_tokens,
            model=self.model,
            messages=messages,
            tools=tools,
            **self.chat_params,
        ) as stream:
            for text in stream.text_stream:
                yield self.to_stream_messages(text)

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
        client = self._client()

        # TODO: change to Async Streaming
        with client.messages.stream(
            max_tokens=self.max_tokens,
            model=self.model,
            messages=messages,
            tools=tools,
            **self.chat_params,
        ) as stream:
            for text in stream.text_stream:
                yield self.to_stream_messages(text)

    # ------------------------------------------------------------------ #
    # Conversion helpers                                                 #
    # ------------------------------------------------------------------ #
    def to_stream_messages(self, text: str) -> Messages:
        if text:
            return [Message(role="assistant", content=text)]
        return []

    def to_messages(self, resp: AnthropicMessage) -> Messages:
        text = ""
        tool_calls = []
        for block in resp.content:
            if isinstance(block, TextBlock):
                text = text + block.text
            elif isinstance(block, ToolUseBlock):
                tool_call = {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    },
                }
                tool_calls.append(tool_call)

        message_args: Dict[str, Any] = {
            "role": "assistant",
            "content": text,
            "tool_calls": tool_calls,
        }
        if len(tool_calls) > 0:
            message_args["content"] = ""

        return [Message.model_validate(message_args)]

    # ------------------------------------------------------------------ #
    # Serialisation                                                      #
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "api_key": "****************",
            "model": self.model,
        }
