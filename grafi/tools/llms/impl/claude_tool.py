"""
ClaudeTool - Anthropic Claude implementation of grafi.tools.llms.llm.LLM
"""

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

from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.exceptions import LLMToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm import LLMBuilder

try:
    from anthropic import AsyncAnthropic
    from anthropic import Omit
    from anthropic import omit
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
    # Anthropic recommends not lowballing max_tokens; this is an upper bound, not
    # a cost floor (you pay for what is generated). Opus 4.x supports up to 128K
    # when streaming — raise this if you stream long outputs.
    max_tokens: int = Field(default=16384)
    # Default to the lowest-cost tier (Haiku). Upgrade for harder tasks, e.g.
    # "claude-sonnet-4-6" or "claude-opus-4-8".
    # NOTE: if you switch to Opus 4.7/4.8 they reject temperature/top_p/top_k/
    # budget_tokens — steer with `effort`/`thinking` instead of sampling params.
    model: str = Field(default="claude-haiku-4-5")
    thinking: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Extended/adaptive thinking config passed to the Messages API, e.g. "
            "{'type': 'adaptive'} or {'type': 'adaptive', 'display': 'summarized'}. "
            "Adaptive thinking is the supported mode on Claude 4.6+; "
            "budget_tokens is rejected on Opus 4.7/4.8. Left off when None."
        ),
    )
    effort: Optional[str] = Field(
        default=None,
        description=(
            "Output/reasoning effort sent inside output_config: "
            "'low' | 'medium' | 'high' | 'xhigh' | 'max'. Supported on Opus 4.5+ "
            "and Sonnet 4.6. Left off when None (API default is 'high')."
        ),
    )

    @classmethod
    def builder(cls) -> "ClaudeToolBuilder":
        """
        Return a builder for ClaudeTool.
        This method allows for the construction of a ClaudeTool instance with specified parameters.
        """
        return ClaudeToolBuilder(cls)

    def prepare_api_input(self, input_data: Messages) -> tuple[
        Union[str, Omit],
        List[MessageParam],
        Union[List[ToolParam], Omit],
    ]:
        """grafi → Anthropic (system, message list, optional tools).

        The Anthropic Messages API only accepts ``user``/``assistant`` roles in
        the ``messages`` array; the system prompt is a top-level ``system``
        parameter. Tool calls and tool results are expressed as ``tool_use`` /
        ``tool_result`` content blocks rather than separate roles.
        """
        # System prompt: instance system_message plus any system-role messages,
        # all folded into the top-level `system` parameter.
        system_parts: List[str] = []
        if self.system_message:
            system_parts.append(self.system_message)

        messages: List[MessageParam] = []

        for m in input_data:
            if m.role == "system":
                if isinstance(m.content, str) and m.content:
                    system_parts.append(m.content)
                continue

            if m.role == "tool":
                # A tool result becomes a user turn carrying a tool_result block.
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or "",
                                "content": self._content_to_text(m.content),
                            }
                        ],
                    }
                )
                continue

            if m.role == "assistant" and m.tool_calls:
                # Assistant tool calls become tool_use content blocks, preserving
                # any accompanying text so the conversation stays linked.
                blocks: List[Dict[str, Any]] = []
                if isinstance(m.content, str) and m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.function.name,
                            "input": self.parse_tool_arguments(tc.function.arguments),
                        }
                    )
                messages.append({"role": "assistant", "content": blocks})
                continue

            # Plain text user/assistant message.
            if isinstance(m.content, str) and m.content:
                messages.append({"role": m.role, "content": m.content})

        system: Union[str, Omit] = "\n\n".join(system_parts) if system_parts else omit

        tools: List[ToolParam] = []
        for function in self.get_function_specs():
            tools.append(
                {
                    "name": function.name,
                    "description": function.description,
                    "input_schema": function.parameters.model_dump(),
                }
            )

        return system, messages, tools or omit

    @staticmethod
    def _content_to_text(content: Any) -> str:
        """Coerce a tool-result message's content to text for Anthropic."""
        if isinstance(content, str):
            return content
        if content is None:
            return ""
        return json.dumps(content, default=str)

    def _request_kwargs(
        self,
        system: Union[str, Omit],
        messages: List[MessageParam],
        tools: Union[List[ToolParam], Omit],
    ) -> Dict[str, Any]:
        """Assemble keyword arguments shared by the streaming and non-streaming
        calls.

        ``thinking`` and ``effort`` are only included when set, so a tool that
        doesn't use them keeps the API's defaults. ``effort`` is folded into
        ``output_config`` (merged with any user-supplied ``output_config`` in
        ``chat_params``). ``chat_params`` is applied last so an explicit caller
        value always wins over the first-class fields.
        """
        kwargs: Dict[str, Any] = {
            "max_tokens": self.max_tokens,
            "model": self.model,
            "system": system,
            "messages": messages,
            "tools": tools,
        }

        chat_params = dict(self.chat_params)

        if self.thinking is not None:
            kwargs["thinking"] = self.thinking

        if self.effort is not None:
            output_config = dict(chat_params.pop("output_config", {}) or {})
            output_config.setdefault("effort", self.effort)
            kwargs["output_config"] = output_config

        kwargs.update(chat_params)
        return kwargs

    # ------------------------------------------------------------------ #
    # Async call                                                         #
    # ------------------------------------------------------------------ #
    @record_tool_invoke
    async def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        system, messages, tools = self.prepare_api_input(input_data)
        request_kwargs = self._request_kwargs(system, messages, tools)

        try:
            async with AsyncAnthropic(api_key=self.api_key) as client:
                if self.is_streaming:
                    async with client.messages.stream(**request_kwargs) as stream:
                        async for event in stream:
                            if event.type == "text":
                                yield self.to_stream_messages(event.text)
                else:
                    resp: AnthropicMessage = await client.messages.create(
                        **request_kwargs
                    )
                    yield self.to_messages(resp)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise LLMToolException(
                tool_name=self.name,
                model=self.model,
                message=f"Anthropic async call failed: {exc}",
                invoke_context=invoke_context,
                cause=exc,
            ) from exc

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

        # A refused response (HTTP 200, stop_reason="refusal") carries empty or
        # partial content; surface the reason on the message so callers can react
        # instead of treating the blank text as a normal answer.
        if getattr(resp, "stop_reason", None) == "refusal":
            details = getattr(resp, "stop_details", None)
            explanation = getattr(details, "explanation", None) if details else None
            message_args["refusal"] = (
                explanation or "Request refused by the Anthropic safety system."
            )

        return [Message.model_validate(message_args)]

    # ------------------------------------------------------------------ #
    # Serialisation                                                      #
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "max_tokens": self.max_tokens,
            "thinking": self.thinking,
            "effort": self.effort,
        }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "ClaudeTool":
        """
        Create a ClaudeTool instance from a dictionary representation.

        Args:
            data (Dict[str, Any]): A dictionary representation of the ClaudeTool.

        Returns:
            ClaudeTool: A ClaudeTool instance created from the dictionary.
        """
        # Create base instance from parent and add ClaudeTool-specific fields

        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            cls.builder()
            .name(data.get("name", "ClaudeTool"))
            .type(data.get("type", "ClaudeTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .chat_params(data.get("chat_params", {}))
            .is_streaming(data.get("is_streaming", False))
            .system_message(data.get("system_message", ""))
            .api_key(os.getenv("ANTHROPIC_API_KEY"))
            .model(data.get("model", "claude-haiku-4-5"))
            .max_tokens(data.get("max_tokens", 16384))
            .thinking(data.get("thinking"))
            .effort(data.get("effort"))
            .build()
        )


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

    def thinking(self, thinking: Optional[Dict[str, Any]]) -> Self:
        """Set the extended/adaptive thinking config (e.g. {'type': 'adaptive'})."""
        self.kwargs["thinking"] = thinking
        return self

    def effort(self, effort: Optional[str]) -> Self:
        """Set output effort ('low' | 'medium' | 'high' | 'xhigh' | 'max')."""
        self.kwargs["effort"] = effort
        return self
