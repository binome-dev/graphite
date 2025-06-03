"""
GeminiTool - Google Gemini implementation of grafi.tools.llms.llm.LLM

Uses the **new Google Gen AI SDK** (package ``google-genai>=1.5``).
Docs & examples:  https://ai.google.dev/gemini-api  :contentReference[oaicite:0]{index=0}
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any
from typing import Dict
from typing import Generator
from typing import List
from typing import Optional
from typing import Self

from deprecated import deprecated
from google.genai import types
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
    from google import genai
    from google.genai.types import Content
    from google.genai.types import ContentListUnion
    from google.genai.types import FunctionDeclaration
    from google.genai.types import GenerateContentResponse
    from google.genai.types import Part
    from google.genai.types import Schema
    from google.genai.types import Tool
except ImportError:
    raise ImportError(
        "`google-genai` not installed. Please install using `pip install google-genai`"
    )

GEMINI_ROLE_MAP = {
    "user": "user",
    "assistant": "model",
    "tool": "user",
    "system": "model",
}


class GeminiTool(LLM):
    """
    Google Gemini implementation of the LLM tool interface used by *grafi*.
    """

    name: str = Field(default="GeminiTool")
    type: str = Field(default="GeminiTool")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    model: str = Field(default="gemini-2.0-flash-lite")

    # Any key‑value pairs you want to pass straight through to the SDK
    chat_params: Dict[str, Any] = Field(default_factory=dict)

    # --------------------------------------------------------------------- #
    # Builder helper – same fluent style as OpenAITool.Builder
    # --------------------------------------------------------------------- #
    class Builder(LLM.Builder):
        _tool: "GeminiTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "GeminiTool":
            return GeminiTool.model_construct()

        def api_key(self, api_key: Optional[str]) -> Self:
            self._tool.api_key = api_key
            return self

        def model(self, model: str) -> Self:
            self._tool.model = model
            return self

        def build(self) -> "GeminiTool":
            if not self._tool.api_key:
                raise ValueError("API key must be provided for GeminiTool")
            return self._tool

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    def _client(self) -> genai.Client:
        """
        Initialise a *stateless* client.  The Google SDK uses a lightweight
        Client object; it's fine to create one per request.
        """
        return genai.Client(api_key=self.api_key)

    def prepare_api_input(
        self, input_data: Messages
    ) -> tuple[ContentListUnion, Optional[Tool]]:
        """
        Map grafi ``Message`` objects -> Gemini *contents* list.

        Gemini expects::

            contents=[
                {"role": "user", "parts": [{"text": "Hi"}]},
                {"role": "model", "parts": [{"text": "Hello!"}]},
            ]

        Function/tool declarations are passed via GenerateContentConfig,
        so we simply return them for the caller to insert.
        """
        contents: List[Content] = []

        # prepend system instruction in Gemini style if present
        if self.system_message:
            contents.append(
                Content(
                    role="user",
                    parts=[Part(text=self.system_message)],
                )
            )

        for m in input_data:
            # Gemini only needs role + parts; we ignore tool_call fields here
            if m.content is not None and isinstance(m.content, str) and m.content != "":
                contents.append(
                    Content(
                        role=GEMINI_ROLE_MAP.get(m.role, m.role),
                        parts=[Part(text=m.content)],
                    )
                )

        function_declarations: List[FunctionDeclaration] = []
        if input_data and input_data[-1].tools:
            for tool in input_data[-1].tools:
                function = tool.get("function")
                if function is not None:
                    function_declaration = FunctionDeclaration(
                        name=function["name"],
                        description=function["description"],
                        parameters=Schema.model_validate(function["parameters"]),
                    )
                    function_declarations.append(function_declaration)

        return contents, (
            [Tool(function_declarations=function_declarations)]
            if function_declarations
            else None
        )

    # --------------------------------------------------------------------- #
    # Synchronous (blocking) one‑shot call
    # --------------------------------------------------------------------- #
    @record_tool_execution
    def execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Messages:
        contents, tools = self.prepare_api_input(input_data)

        client = self._client()
        # Build optional config only when we actually have tools
        cfg = types.GenerateContentConfig(
            tools=tools if tools else None, **self.chat_params  # type: ignore[arg-type]
        )

        try:
            response: GenerateContentResponse = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=cfg,
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini API error: {exc}") from exc

        return self.to_messages(response)

    # --------------------------------------------------------------------- #
    # Asynchronous (async/await) one‑shot call
    # --------------------------------------------------------------------- #
    @record_tool_a_execution
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:  # → async generator just like OpenAITool
        contents, tools = self.prepare_api_input(input_data)

        client = genai.Client(api_key=self.api_key)  # same lightweight client

        cfg = (
            types.GenerateContentConfig(tools=tools)  # type: ignore[arg-type]
            if tools
            else None
        )

        try:
            response: GenerateContentResponse = (
                await client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=cfg,
                    **self.chat_params,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Gemini async call failed: {exc}") from exc

        yield self.to_messages(response)

    # --------------------------------------------------------------------- #
    # Synchronous streaming  (deprecated wrapper kept for parity)
    # --------------------------------------------------------------------- #
    @record_tool_stream
    @deprecated("Use a_stream() instead for streaming functionality")
    def stream(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Generator[Messages, None, None]:
        contents, tools = self.prepare_api_input(input_data)
        cfg = (
            types.GenerateContentConfig(tools=tools)  # type: ignore[arg-type]
            if tools
            else None
        )
        client = self._client()

        for chunk in client.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=cfg,
            **self.chat_params,
        ):
            yield self.to_stream_messages(chunk)

    # --------------------------------------------------------------------- #
    # Async streaming
    # --------------------------------------------------------------------- #
    @record_tool_a_stream
    async def a_stream(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:
        contents, tools = self.prepare_api_input(input_data)
        cfg = (
            types.GenerateContentConfig(tools=tools)  # type: ignore[arg-type]
            if tools
            else None
        )
        client = genai.Client(api_key=self.api_key)

        async for chunk in await client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=cfg,
            **self.chat_params,
        ):
            yield self.to_stream_messages(chunk)

    # --------------------------------------------------------------------- #
    # Response conversion helpers
    # --------------------------------------------------------------------- #
    def to_stream_messages(self, chunk: GenerateContentResponse) -> Messages:
        """
        Convert a streaming chunk → grafi Message list.

        The SDK's ``text`` property gives you the incremental delta; we wrap
        it in a single assistant message so grafi can assemble the full
        answer just like with OpenAI chunks.
        """
        return [Message(role="assistant", content=chunk.text)]

    def to_messages(self, response: GenerateContentResponse) -> Messages:
        """
        Convert the Gemini API response to a Message object.
        """
        message_data = response.text

        # Handle the basic fields
        role = "assistant"
        content = message_data or "No content provided"

        message_args: Dict[str, Any] = {
            "role": role,
            "content": content,
        }

        # Process tool calls if they exist
        if response.function_calls and len(response.function_calls) > 0:
            if content == "No content provided":
                message_args[
                    "content"
                ] = ""  # Clear content when function call is included
            tool_calls = []
            for raw_function_call in response.function_calls:
                # Include the function call if provided
                tool_call = {
                    "id": raw_function_call.id or uuid.uuid4().hex,
                    "type": "function",
                    "function": {
                        "name": raw_function_call.name,
                        "arguments": json.dumps(raw_function_call.args),
                    },
                }
                tool_calls.append(tool_call)

            message_args["tool_calls"] = tool_calls

        return [Message.model_validate(message_args)]

    # --------------------------------------------------------------------- #
    # Serialisation helper (do **not** expose real key)
    # --------------------------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "api_key": "****************",
            "model": self.model,
        }
