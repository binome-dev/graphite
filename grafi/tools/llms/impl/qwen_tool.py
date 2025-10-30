"""
QwenTool – Alibaba Qwen implementation of grafi.tools.llms.llm.LLM

Qwen's HTTP interface is 100% OpenAI-compatible, so we reuse the
official `openai` Python SDK and simply change `base_url`.

Docs: https://help.aliyun.com/zh/model-studio/getting-started/models
The API is compatible with OpenAI SDK by setting 
`base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"`
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


class QwenTool(LLM):
    """
    QwenTool – Alibaba Qwen implementation of grafi.tools.llms.llm.LLM
    
    This tool uses the OpenAI-compatible API provided by Alibaba Cloud DashScope.
    """

    name: str = Field(default="QwenTool")
    type: str = Field(default="QwenTool")
    api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("DASHSCOPE_API_KEY")
    )
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )  # Beijing region; use https://dashscope-intl.aliyuncs.com/compatible-mode/v1 for Singapore
    model: str = Field(default="qwen-plus")  # or qwen-turbo, qwen-max, etc.

    @classmethod
    def builder(cls) -> "QwenToolBuilder":
        """
        Return a builder for QwenTool.

        This method allows for the construction of a QwenTool instance with specified parameters.
        """
        return QwenToolBuilder(cls)

    # ------------------------------------------------------------------ #
    # Shared helper to map grafi → SDK input                             #
    # ------------------------------------------------------------------ #
    def prepare_api_input(
        self, input_data: Messages
    ) -> tuple[
        List[ChatCompletionMessageParam], Union[List[ChatCompletionToolParam], NotGiven]
    ]:
        """
        Prepare the input data for the Qwen API.

        Args:
            input_data (Messages): A list of Message objects.

        Returns:
            tuple: A tuple containing:
                - A list of message parameters for the API.
                - A list of tool parameters for the API, or NotGiven if no tools are present.
        """
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
        """
        Invoke the Qwen API with the given input data.

        Args:
            invoke_context (InvokeContext): The context for this invocation.
            input_data (Messages): The input messages to send to the API.

        Yields:
            Messages: The response messages from the API.

        Raises:
            LLMToolException: If the API call fails.
        """
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
                message=f"Qwen API call failed: {exc}",
                invoke_context=invoke_context,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise LLMToolException(
                tool_name=self.name,
                model=self.model,
                message=f"Unexpected error during Qwen API call: {exc}",
                invoke_context=invoke_context,
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------ #
    # Response converters                                                #
    # ------------------------------------------------------------------ #
    def to_stream_messages(self, chunk: ChatCompletionChunk) -> Messages:
        """
        Convert a streaming chunk to grafi Messages.

        Args:
            chunk (ChatCompletionChunk): A streaming response chunk from the API.

        Returns:
            Messages: A list containing a single Message object with streaming flag set.
        """
        # Check if chunk has choices and is not empty
        if not chunk.choices or len(chunk.choices) == 0:
            return [Message(role="assistant", content="", is_streaming=True)]

        choice = chunk.choices[0]
        delta = choice.delta
        data = delta.model_dump()
        if data.get("role") is None:
            data["role"] = "assistant"
        data["is_streaming"] = True
        return [Message.model_validate(data)]

    def to_messages(self, resp: ChatCompletion) -> Messages:
        """
        Convert a complete API response to grafi Messages.

        Args:
            resp (ChatCompletion): The complete response from the API.

        Returns:
            Messages: A list containing a single Message object.
        """
        return [Message.model_validate(resp.choices[0].message.model_dump())]

    # ------------------------------------------------------------------ #
    # Serialisation helper                                               #
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the QwenTool instance to a dictionary.

        Returns:
            dict: A dictionary containing the attributes of the QwenTool instance.
        """
        return {
            **super().to_dict(),
            "base_url": self.base_url,
        }


class QwenToolBuilder(LLMBuilder[QwenTool]):
    """
    Builder for QwenTool instances.
    
    This builder provides a fluent interface for constructing QwenTool objects
    with custom configuration.
    """

    def base_url(self, base_url: str) -> Self:
        """
        Set the base URL for the Qwen API.

        Args:
            base_url (str): The base URL (will be stripped of trailing slashes).

        Returns:
            Self: This builder instance for method chaining.
        """
        self.kwargs["base_url"] = base_url.rstrip("/")
        return self

    def api_key(self, api_key: Optional[str]) -> Self:
        """
        Set the API key for authentication.

        Args:
            api_key (Optional[str]): The DashScope API key.

        Returns:
            Self: This builder instance for method chaining.
        """
        self.kwargs["api_key"] = api_key
        return self

