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
import inspect
import json
import os
import re
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import Union
from typing import cast

from openai import NOT_GIVEN
from openai import AsyncClient
from openai import NotGiven
from openai import OpenAIError
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError

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

        # Qwen-specific: requires "json" keyword in messages when using structured_output
        needs_json_keyword = (
            self.structured_output
            or (self.chat_params and "response_format" in self.chat_params)
        )
        
        if needs_json_keyword:
            last_user_message_idx = None
            for i in range(len(api_messages) - 1, -1, -1):
                if api_messages[i].get("role") == "user":
                    last_user_message_idx = i
                    break
            
            if last_user_message_idx is not None:
                user_content = api_messages[last_user_message_idx].get("content", "")
                if user_content and "json" not in user_content.lower():
                    # Qwen-specific: auto-inject "json" keyword to satisfy API requirement
                    api_messages[last_user_message_idx] = cast(
                        ChatCompletionMessageParam,
                        {
                            **api_messages[last_user_message_idx],
                            "content": f"{user_content} (return as JSON)",
                        },
                    )

        api_tools = [
            function_spec.to_openai_tool()
            for function_spec in self.get_function_specs()
        ] or NOT_GIVEN

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
        client = None
        try:
            client = AsyncClient(api_key=self.api_key, base_url=self.base_url)
            
            # Qwen-specific: serialize chat_params to convert BaseModel classes to JSON schema
            # This allows using create() instead of parse() to avoid camelCase/snake_case issues
            serialized_chat_params = self._serialize_chat_params(self.chat_params)
            original_response_format = self.chat_params.get("response_format")

            if self.is_streaming:
                async for chunk in await client.chat.completions.create(
                    model=self.model,
                    messages=api_messages,
                    tools=api_tools,
                    stream=True,
                    **serialized_chat_params,
                ):
                    yield self.to_stream_messages(chunk)
            else:
                # Qwen-specific: use create() instead of parse() for structured output
                # because Qwen may return camelCase JSON while Pydantic expects snake_case
                if original_response_format:
                    response: ChatCompletion = await client.chat.completions.create(
                        model=self.model,
                        messages=api_messages,
                        tools=api_tools,
                        **serialized_chat_params,
                    )
                    yield self.to_messages_with_camelcase_fix(response, original_response_format)
                else:
                    response: ChatCompletion = await client.chat.completions.create(
                        model=self.model,
                        messages=api_messages,
                        tools=api_tools,
                        **serialized_chat_params,
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
        finally:
            if client is not None:
                try:
                    await client.close()
                except (RuntimeError, asyncio.CancelledError):
                    pass

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

    def _camel_to_snake(self, name: str) -> str:
        """
        Convert camelCase to snake_case.
        
        Qwen-specific: helper for converting Qwen's camelCase JSON keys to snake_case
        to match Pydantic model expectations.
        
        Args:
            name (str): camelCase string
            
        Returns:
            str: snake_case string
            
        Examples:
            firstName -> first_name
            lastName -> last_name
            userID -> user_id
        """
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

    def _convert_dict_keys(self, data: Any) -> Any:
        """
        Recursively convert dictionary keys from camelCase to snake_case.
        
        Qwen-specific: converts Qwen's camelCase JSON response keys to snake_case
        for compatibility with Pydantic models.
        
        Args:
            data: Can be dict, list, or other types
            
        Returns:
            Data with dictionary keys converted from camelCase to snake_case
        """
        if isinstance(data, dict):
            return {
                self._camel_to_snake(k): self._convert_dict_keys(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._convert_dict_keys(item) for item in data]
        else:
            return data

    def to_messages_with_camelcase_fix(
        self, resp: ChatCompletion, response_format: Any
    ) -> Messages:
        """
        Convert API response to grafi Messages with camelCase to snake_case conversion.
        
        Qwen-specific: handles structured output where Qwen returns camelCase JSON
        but Pydantic models expect snake_case field names. This method converts
        the response keys before validation.
        
        Args:
            resp (ChatCompletion): Complete response from API
            response_format: Original response_format (may be BaseModel class)
            
        Returns:
            Messages: List containing a single Message object
        """
        message = resp.choices[0].message
        content = message.content
        
        if response_format and content:
            try:
                json_data = json.loads(content)
                
                if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                    # Qwen-specific: convert camelCase keys to snake_case
                    converted_data = self._convert_dict_keys(json_data)
                    
                    try:
                        # Try to validate with Pydantic model
                        pydantic_instance = response_format.model_validate(converted_data)
                        content = pydantic_instance.model_dump_json()
                    except ValidationError:
                        # If validation fails, return converted JSON with correct key names
                        content = json.dumps(converted_data, ensure_ascii=False)
            
            except json.JSONDecodeError:
                # Keep original content if JSON parsing fails
                pass
        
        message_data = message.model_dump()
        message_data["content"] = content
        return [Message.model_validate(message_data)]

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

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "QwenTool":
        """
        Create a QwenTool instance from a dictionary representation.

        Args:
            data (Dict[str, Any]): A dictionary representation of the QwenTool.

        Returns:
            QwenTool: A QwenTool instance created from the dictionary.
        """
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            cls.builder()
            .name(data.get("name", "QwenTool"))
            .type(data.get("type", "QwenTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "LLM")))
            .chat_params(data.get("chat_params", {}))
            .is_streaming(data.get("is_streaming", False))
            .system_message(data.get("system_message", ""))
            .api_key(os.getenv("DASHSCOPE_API_KEY"))
            .model(data.get("model", "qwen-plus"))
            .base_url(data.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
            .build()
        )


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

