import json
import uuid
from typing import Any
from typing import Dict
from typing import Generator
from typing import List
from typing import Literal
from typing import Optional
from typing import Self
from typing import cast

from deprecated import deprecated
from loguru import logger
from ollama import ChatResponse
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

    class Builder(LLM.Builder):
        """Concrete builder for OllamaTool."""

        _tool: "OllamaTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "OllamaTool":
            return OllamaTool.model_construct()

        def api_url(self, api_url: str) -> Self:
            self._tool.api_url = api_url
            return self

        def model(self, model: str) -> Self:
            self._tool.model = model
            return self

        def build(self) -> "OllamaTool":
            return self._tool

    def prepare_api_input(
        self, input_data: Messages
    ) -> tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
        api_messages: List[Dict[str, Any]] = (
            [{"role": "system", "content": self.system_message}]
            if self.system_message
            else []
        )
        api_functions = None

        for message in input_data:
            api_message = {
                "role": "tool" if message.role == "function" else message.role,
                "content": message.content or "",
            }
            if message.function_call:
                api_message["tool_calls"] = [
                    {
                        "function": {
                            "name": message.function_call.name,
                            "arguments": json.loads(message.function_call.arguments),
                        }
                    }
                ]
            api_messages.append(api_message)

        if input_data[-1].tools:
            api_functions = input_data[-1].tools

        return api_messages, api_functions

    @record_tool_execution
    def execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Messages:
        """
        Execute a request to the Ollama API asynchronously.
        """
        logger.debug("Input data: %s", input_data)

        # Prepare payload
        api_messages, api_functions = self.prepare_api_input(input_data)
        # Use Ollama Client to send the request
        client = ollama.Client(self.api_url)
        try:
            response = client.chat(
                model=self.model, messages=api_messages, tools=api_functions
            )

            # Return the raw response as a Message object
            return self.to_messages(response)
        except Exception as e:
            logger.error("Ollama API error: %s", e)
            raise RuntimeError(f"Ollama API error: {e}") from e

    @record_tool_a_execution
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:
        """
        Execute a request to the Ollama API asynchronously.
        """
        logger.debug("Input data: %s", input_data)

        # Prepare payload
        api_messages, api_functions = self.prepare_api_input(input_data)
        # Use Ollama Client to send the request
        client = ollama.AsyncClient(self.api_url)
        try:
            response = await client.chat(
                model=self.model, messages=api_messages, tools=api_functions
            )

            # Return the raw response as a Message object
            yield self.to_messages(response)
        except Exception as e:
            logger.error("Ollama API error: %s", e)
            raise RuntimeError(f"Ollama API error: {e}") from e

    @record_tool_stream
    @deprecated("Use a_stream() instead for streaming functionality")
    def stream(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Generator[Messages, None, None]:
        """
        Synchronous token streaming from Ollama.

        Yields incremental `Message` lists that contain only the newly
        generated chunk.
        """
        api_messages, api_functions = self.prepare_api_input(input_data)
        client = ollama.Client(self.api_url)

        try:
            for chunk in client.chat(
                model=self.model,
                messages=api_messages,
                tools=api_functions,
                stream=True,
            ):
                yield self.to_stream_messages(chunk)
        except Exception as e:
            logger.error("Ollama streaming error: %s", e)
            raise RuntimeError(f"Ollama streaming error: {e}") from e

    @record_tool_a_stream
    async def a_stream(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:
        """
        Asynchronous token streaming from Ollama.

        Follows the same semantics as `stream()` but returns an
        asynchronous generator.
        """
        api_messages, api_functions = self.prepare_api_input(input_data)
        client = ollama.AsyncClient(self.api_url)

        try:
            stream = await client.chat(  # returns an *async* generator
                model=self.model,
                messages=api_messages,
                tools=api_functions,
                stream=True,
            )
            async for chunk in stream:
                yield self.to_stream_messages(chunk)
        except Exception as e:
            logger.error("Ollama async streaming error: %s", e)
            raise RuntimeError(f"Ollama async streaming error: {e}") from e

    def to_stream_messages(self, chunk: ChatResponse | dict[str, Any]) -> Messages:
        """
        Convert a single streaming chunk coming from the Ollama client to
        the grafi `Message` envelope expected by downstream nodes.

        Ollama yields either a `ChatResponse` object or a plain dict that
        contains a `"message"` entry with incremental text.
        Only the **delta** is propagated so the caller can assemble the
        final answer.
        """
        if isinstance(chunk, ChatResponse):
            # `chunk.message.content` is the incremental bit
            msg = chunk.message
            role_value = msg.role or "assistant"
            content = msg.content or ""
        else:  # plain dict (↔ ollama.chat(..., stream=True) docs)
            msg = chunk.get("message", {})
            role_value = msg.get("role", "assistant")
            content = msg.get("content", "")

        if role_value in ("system", "user", "assistant", "tool"):
            safe_role: Literal["system", "user", "assistant", "tool"] = cast(
                Literal["system", "user", "assistant", "tool"], role_value
            )
        else:
            safe_role = "assistant"

        # skip empty deltas to avoid emitting blank messages
        if not content:
            return []

        return [Message(role=safe_role, content=content)]

    def to_messages(self, response: ChatResponse) -> Messages:
        """
        Convert the Ollama API response to a Message object.
        """
        message_data = response.message

        # Handle the basic fields
        role = message_data.role or "assistant"
        content = message_data.content or "No content provided"

        message_args: Dict[str, Any] = {
            "role": role,
            "content": content,
        }

        # Process tool calls if they exist
        if "tool_calls" in message_data and message_data.tool_calls:
            raw_tool_calls = message_data.tool_calls

            if content == "No content provided":
                message_args["content"] = (
                    ""  # Clear content when function call is included
                )

            tool_calls = []
            for raw_tool_call in raw_tool_calls:
                # Include the function call if provided
                function = raw_tool_call.function
                tool_call = {
                    "id": uuid.uuid4().hex,
                    "type": "function",
                    "function": {
                        "name": function.name,
                        "arguments": json.dumps(function.arguments),
                    },
                }
                tool_calls.append(tool_call)

            message_args["tool_calls"] = tool_calls

        # Include the name if provided
        if "name" in message_data:
            message_args["name"] = message_data["name"]

        return [Message.model_validate(message_args)]

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "api_url": self.api_url,
            "model": self.model,
        }
