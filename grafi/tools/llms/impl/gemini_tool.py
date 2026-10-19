"""
GeminiTool - Google Gemini implementation of grafi.tools.llms.llm.LLM

Uses the **new Google Gen AI SDK** (package ``google-genai>=1.5``).
Docs & examples:  https://ai.google.dev/gemini-api  :contentReference[oaicite:0]{index=0}
"""

import base64
import json
import os
import uuid
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Self

from google.genai import types
from pydantic import Field

from grafi.common.async_lifecycle import cleanup_on_exit
from grafi.common.async_lifecycle import owned_iterator
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.exceptions import LLMToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.runtime.deltas import emit_delta
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm import LLMBuilder

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

# Gemini 3 requires the first function call of each answer to carry the
# signature Gemini gave it. A call it did not make (another provider's, or one
# stored before signatures were kept) carries this value instead, which Google
# documents for exactly that.
_UNSIGNED = b"skip_thought_signature_validator"

GEMINI_ROLE_MAP = {
    "user": "user",
    "assistant": "model",
    "tool": "user",  # Function responses are the user's turn.
}


class GeminiTool(LLM):
    """
    Google Gemini implementation of the LLM tool interface used by *grafi*.
    """

    name: str = Field(default="GeminiTool")
    type: str = Field(default="GeminiTool")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    # Capable current Gemini tier; use "gemini-3.1-flash-lite" for lower cost or
    # "gemini-3.1-pro-preview" for the hardest tasks.
    model: str = Field(default="gemini-3.5-flash")
    thinking_budget: Optional[int] = Field(
        default=None,
        description=(
            "Gemini 2.5 thinking budget in tokens. 0 disables thinking; -1 lets "
            "the model decide dynamically. Mapped to types.ThinkingConfig and left "
            "off when None (model default applies)."
        ),
    )

    @classmethod
    def builder(cls) -> "GeminiToolBuilder":
        """
        Return a builder for GeminiTool.

        This method allows for the construction of a GeminiTool instance with specified parameters.
        """
        return GeminiToolBuilder(cls)

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
    ) -> tuple[ContentListUnion, Optional[List[Tool]], Optional[str]]:
        """
        Map grafi ``Message`` objects -> Gemini *contents* list.

        Gemini expects::

            contents=[
                {"role": "user", "parts": [{"text": "Hi"}]},
                {"role": "model", "parts": [{"text": "Hello!"}]},
            ]

        The system prompt (the instance ``system_message`` plus any ``system``
        role messages) is returned separately so the caller can pass it via the
        config's ``system_instruction`` field — the SDK-native way to set a
        system prompt — rather than faking it as a leading ``user`` turn.
        Function/tool declarations are likewise returned for the caller to insert.
        """
        contents: List[Content] = []

        # Collect the system prompt; folded into config.system_instruction below.
        system_parts: List[str] = []
        if self.system_message:
            system_parts.append(self.system_message)

        # A function response names its function: the call with its id did.
        call_names: Dict[str, str] = {}
        for m in input_data:
            if m.role == "system":
                if isinstance(m.content, str) and m.content:
                    system_parts.append(m.content)
                continue
            parts: List[Part] = []
            if m.role == "tool":
                parts.append(
                    Part(
                        function_response=types.FunctionResponse(
                            id=m.tool_call_id,
                            name=call_names.get(m.tool_call_id or "", ""),
                            response={"result": m.content},
                        )
                    )
                )
            elif isinstance(m.content, str) and m.content:
                parts.append(Part(text=m.content))
            for position, call in enumerate(m.tool_calls or []):
                call_names[call.id] = call.function.name
                google = (call.model_extra or {}).get("extra_content", {}).get("google")
                signature = (google or {}).get("thought_signature")
                parts.append(
                    Part(
                        function_call=types.FunctionCall(
                            id=call.id,
                            name=call.function.name,
                            args=self.parse_tool_arguments(call.function.arguments),
                        ),
                        thought_signature=(
                            base64.b64decode(signature)
                            if signature
                            else _UNSIGNED if position == 0 else None
                        ),
                    )
                )
            if parts:
                contents.append(
                    Content(role=GEMINI_ROLE_MAP.get(m.role, m.role), parts=parts)
                )

        function_declarations: List[FunctionDeclaration] = []
        for function in self.get_function_specs():
            function_declaration = FunctionDeclaration(
                name=function.name,
                description=function.description,
                parameters=Schema.model_validate(function.parameters),
            )
            function_declarations.append(function_declaration)

        tools = (
            [Tool(function_declarations=function_declarations)]
            if function_declarations
            else None
        )
        system_instruction = "\n\n".join(system_parts) if system_parts else None

        return contents, tools, system_instruction

    # --------------------------------------------------------------------- #
    # Asynchronous (async/await) one‑shot call
    # --------------------------------------------------------------------- #
    @record_tool_invoke
    async def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:  # → async generator just like OpenAITool
        contents, tools, system_instruction = self.prepare_api_input(input_data)

        # The config is chat_params, with the tools (replacing any configured
        # there) and, unless chat_params sets them, the system instruction and
        # the thinking budget.
        config_kwargs: Dict[str, Any] = dict(self.chat_params)
        if tools:
            config_kwargs["tools"] = tools
        if system_instruction:
            config_kwargs.setdefault("system_instruction", system_instruction)
        if self.thinking_budget is not None:
            config_kwargs.setdefault(
                "thinking_config",
                types.ThinkingConfig(thinking_budget=self.thinking_budget),
            )

        cfg = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        client = self._client()

        async def close_client() -> None:
            # The client has an async and a sync half, each closed on its own.
            try:
                await client.aio.aclose()
            finally:
                client.close()

        # Created per call, so closed per call.
        async with cleanup_on_exit(close_client, best_effort="Gemini client"):
            try:
                if self.should_stream():
                    parts: List[Part] = []
                    refusal: Optional[str] = None
                    stream = await client.aio.models.generate_content_stream(
                        model=self.model, contents=contents, config=cfg
                    )
                    async with owned_iterator(
                        stream, best_effort="Gemini stream"
                    ) as chunks:
                        async for chunk in chunks:
                            refusal = refusal or _refusal(chunk)
                            for part in _parts(chunk):
                                if part.text and not part.thought:
                                    emit_delta(part.text)
                                parts.append(part)
                    message = self._message(parts, refusal)
                else:
                    response = await client.aio.models.generate_content(
                        model=self.model, contents=contents, config=cfg
                    )
                    [message] = self.to_messages(response)
            except Exception as exc:
                raise LLMToolException(
                    tool_name=self.name,
                    model=self.model,
                    message="Gemini async call failed",
                    invoke_context=invoke_context,
                    cause=exc,
                ) from exc
        yield [message]

    # --------------------------------------------------------------------- #
    # Response conversion helpers
    # --------------------------------------------------------------------- #
    def to_messages(self, response: GenerateContentResponse) -> Messages:
        """A response as a message: its text, and its function calls if any."""
        return [self._message(_parts(response), _refusal(response))]

    @staticmethod
    def _message(parts: List[Part], refusal: Optional[str] = None) -> Message:
        """The message a response's parts make: their text, thoughts aside,
        and their function calls; and why Gemini refused, if it did."""
        tool_calls: List[Dict[str, Any]] = []
        for part in parts:
            if call := part.function_call:
                tool_call: Dict[str, Any] = {
                    "id": call.id or uuid.uuid4().hex,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.args or {}),
                    },
                }
                if part.thought_signature:  # Kept as Gemini's OpenAI API keeps it.
                    signature = base64.b64encode(part.thought_signature).decode()
                    tool_call["extra_content"] = {
                        "google": {"thought_signature": signature}
                    }
                tool_calls.append(tool_call)
        text = "".join(part.text for part in parts if part.text and not part.thought)
        return Message.model_validate(
            {
                "role": "assistant",
                "content": text,
                "refusal": refusal,
                "tool_calls": tool_calls or None,
            }
        )

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
            "thinking_budget": self.thinking_budget,
        }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "GeminiTool":
        """
        Create a GeminiTool instance from a dictionary representation.

        Args:
            data (Dict[str, Any]): A dictionary representation of the GeminiTool.

        Returns:
            GeminiTool: A GeminiTool instance created from the dictionary.
        """
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        # GeminiTool uses the same fields as base LLM
        return (
            cls.builder()
            .name(data.get("name", "GeminiTool"))
            .type(data.get("type", "GeminiTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .chat_params(data.get("chat_params", {}))
            .is_streaming(data.get("is_streaming", True))
            .system_message(data.get("system_message", ""))
            .api_key(os.getenv("GEMINI_API_KEY"))
            .model(data.get("model", "gemini-3.5-flash"))
            .thinking_budget(data.get("thinking_budget"))
            .build()
        )


class GeminiToolBuilder(LLMBuilder[GeminiTool]):
    """
    Builder for GeminiTool, allowing fluent configuration of the tool.
    """

    def api_key(self, api_key: Optional[str]) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def thinking_budget(self, thinking_budget: Optional[int]) -> Self:
        """Set the Gemini 2.5 thinking budget in tokens (0 off, -1 dynamic)."""
        self.kwargs["thinking_budget"] = thinking_budget
        return self


def _parts(response: GenerateContentResponse) -> List[Part]:
    """The parts of a response's first candidate, if it has any."""
    candidates = response.candidates or []
    content = candidates[0].content if candidates else None
    return list(content.parts or []) if content else []


# Finish reasons that mean Gemini would not answer.
_REFUSED = {
    "SAFETY",
    "RECITATION",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "IMAGE_SAFETY",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
}


def _refusal(response: GenerateContentResponse) -> Optional[str]:
    """Why Gemini blocked the prompt or stopped its answer, if it refused."""
    feedback = response.prompt_feedback
    if feedback and feedback.block_reason:
        return f"Prompt blocked by Gemini: {feedback.block_reason.name}"
    candidates = response.candidates or []
    reason = candidates[0].finish_reason if candidates else None
    if reason and reason.name in _REFUSED:
        return f"Answer stopped by Gemini: {reason.name}"
    return None
