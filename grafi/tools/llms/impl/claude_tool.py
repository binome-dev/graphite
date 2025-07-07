"""
ClaudeTool - Anthropic Claude implementation of grafi.tools.llms.llm.LLM
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import Union

from pydantic import Field

from grafi.common.decorators.record_tool_a_invoke import record_tool_a_invoke
from grafi.common.decorators.record_tool_invoke import record_tool_invoke
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm import LLMBuilder


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

    @classmethod
    def builder(cls) -> "ClaudeToolBuilder":
        """
        Return a builder for ClaudeTool.
        This method allows for the construction of a ClaudeTool instance with specified parameters.
        """
        return ClaudeToolBuilder(cls)

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
        for function in self.get_function_specs():
            tools.append(
                {
                    "name": function.name,
                    "description": function.description,
                    "input_schema": function.parameters.model_dump(),
                }
            )

        return messages, tools or NOT_GIVEN

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

        client = Anthropic(api_key=self.api_key)
        try:
            resp: AnthropicMessage = client.messages.create(
                max_tokens=self.max_tokens,
                model=self.model,
                messages=messages,
                tools=tools,  # None is fine here
                **self.chat_params,
            )
            return self.to_messages(resp)
        except Exception as exc:
            raise RuntimeError(f"Anthropic API error: {exc}") from exc

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
        client = AsyncAnthropic(api_key=self.api_key)

        try:
            if self.is_streaming:
                async with client.messages.stream(
                    max_tokens=self.max_tokens,
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    **self.chat_params,
                ) as stream:
                    async for event in stream:
                        if event.type == "text":
                            yield self.to_stream_messages(event.text)
            else:
                resp: AnthropicMessage = await client.messages.create(
                    max_tokens=self.max_tokens,
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    **self.chat_params,
                )
                yield self.to_messages(resp)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Anthropic async call failed: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Conversion helpers                                                 #
    # ------------------------------------------------------------------ #
    def to_stream_messages(self, text: str) -> Messages:
        if text:
            return [Message(role="assistant", content=text, is_streaming=True)]
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
            "max_tokens": self.max_tokens,
        }


class ClaudeToolBuilder(LLMBuilder[ClaudeTool]):
    """
    Builder for ClaudeTool.
    This is a convenience class to create instances of ClaudeTool using a fluent interface.
    """

    def api_key(self, api_key: Optional[str]) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def max_tokens(self, max_tokens: int) -> Self:
        self.kwargs["max_tokens"] = max_tokens
        return self
