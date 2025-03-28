import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger
from pydantic import Field

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
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
    model: str = Field(default="qwen2.5")

    class Builder(LLM.Builder):
        """Concrete builder for OllamaTool."""

        def __init__(self):
            self._tool = self._init_tool()

        def _init_tool(self) -> "OllamaTool":
            return OllamaTool()

        def api_url(self, api_url: str) -> "OllamaTool.Builder":
            self._tool.api_url = api_url
            return self

        def model(self, model: str) -> "OllamaTool.Builder":
            self._tool.model = model
            return self

    def prepare_api_input(
        self, input_data: List[Message]
    ) -> tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
        api_messages = (
            [{"role": "system", "content": self.system_message}]
            if self.system_message
            else []
        )
        api_functions = []

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
        input_data: List[Message],
    ) -> Message:
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
            return self.to_message(response)
        except Exception as e:
            logger.error("Ollama API error: %s", e)
            raise RuntimeError(f"Ollama API error: {e}") from e

    @record_tool_a_execution
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        input_data: List[Message],
    ) -> AsyncGenerator[Message, None]:
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
            yield self.to_message(response)
        except Exception as e:
            logger.error("Ollama API error: %s", e)
            raise RuntimeError(f"Ollama API error: {e}") from e

    def to_message(self, response: Dict[str, Any]) -> Message:
        """
        Convert the Ollama API response to a Message object.
        """
        message_data = response.get("message", {})

        # Handle the basic fields
        role = message_data.get("role", "assistant")
        content = message_data.get("content", "No content provided")

        message_args = {
            "role": role,
            "content": content,
        }

        # Process tool calls if they exist
        if "tool_calls" in message_data and message_data["tool_calls"]:
            raw_tool_calls = message_data["tool_calls"]

            if content == "No content provided":
                message_args["content"] = (
                    ""  # Clear content when function call is included
                )

            tool_calls = []
            for raw_tool_call in raw_tool_calls:
                # Include the function call if provided
                if "function" in raw_tool_call:
                    function = raw_tool_call["function"]
                    tool_call = {
                        "id": raw_tool_call.get("id", uuid.uuid4().hex),
                        "type": "function",
                        "function": {
                            "name": function["name"],
                            "arguments": json.dumps(function["arguments"]),
                        },
                    }
                    tool_calls.append(tool_call)

            message_args["tool_calls"] = tool_calls

        # Include the name if provided
        if "name" in message_data:
            message_args["name"] = message_data["name"]

        return Message(**message_args)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "api_url": self.api_url,
            "model": self.model,
        }
