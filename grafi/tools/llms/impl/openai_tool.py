import asyncio
import os
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
from openai import OpenAI
from openai import OpenAIError
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from pydantic import Field

from grafi.common.decorators.record_tool_a_invoke import record_tool_a_invoke
from grafi.common.decorators.record_tool_invoke import record_tool_invoke
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm import LLMBuilder


class OpenAITool(LLM):
    """
    A class representing the OpenAI language model implementation.

    This class provides methods to interact with OpenAI's API for natural language processing tasks.

    Attributes:
        api_key (str): The API key for authenticating with OpenAI.
        model (str): The name of the OpenAI model to use (default is 'gpt-4o-mini').
    """

    name: str = Field(default="OpenAITool")
    type: str = Field(default="OpenAITool")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")

    @classmethod
    def builder(cls) -> "OpenAIToolBuilder":
        """
        Return a builder for OpenAITool.

        This method allows for the construction of an OpenAITool instance with specified parameters.
        """
        return OpenAIToolBuilder(cls)

    def prepare_api_input(
        self, input_data: Messages
    ) -> tuple[
        List[ChatCompletionMessageParam], Union[List[ChatCompletionToolParam], NotGiven]
    ]:
        """
        Prepare the input data for the OpenAI API.

        Args:
            input_data (Messages): A list of Message objects.

        Returns:
            tuple: A tuple containing:
                - A list of dictionaries representing the messages for the API.
                - A list of function specifications for the API, or None if no functions are present.
        """
        api_messages = (
            [
                cast(
                    ChatCompletionMessageParam,
                    {"role": "system", "content": self.system_message},
                )
            ]
            if self.system_message
            else []
        )

        for message in input_data:
            api_message = {
                "name": message.name,
                "role": message.role,
                "content": message.content or "",
                "tool_calls": message.tool_calls,
                "tool_call_id": message.tool_call_id,
            }
            api_messages.append(cast(ChatCompletionMessageParam, api_message))

        # Extract function specifications if present in latest message

        api_tools = [
            function_spec.to_openai_tool()
            for function_spec in self.get_function_specs()
        ] or NOT_GIVEN

        return api_messages, api_tools

    @record_tool_invoke
    def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> Messages:
        """
        Invoke a request to the OpenAI API.

        This method sends a request to the OpenAI API with the provided input data and functions,
        and returns the response as a Message object.

        Args:
            input_data (Messages): A list of Message objects representing the input messages.

        Returns:
            Message: The response from the OpenAI API converted to a Message object.

        Raises:
            RuntimeError: If there's an error in the OpenAI API call.
        """
        api_messages, api_tools = self.prepare_api_input(input_data)

        try:
            client = OpenAI(api_key=self.api_key)

            req_func = (
                client.chat.completions.create
                if not self.structured_output
                else client.beta.chat.completions.parse
            )

            response = req_func(
                model=self.model,
                messages=api_messages,
                tools=api_tools,
                **self.chat_params,
            )
            # Return the raw response
            return self.to_messages(response)

        except Exception as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

    @record_tool_a_invoke
    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        api_messages, api_tools = self.prepare_api_input(input_data)
        try:
            client = AsyncClient(api_key=self.api_key)

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
            # turn client‑specific exceptions into your domain error
            raise RuntimeError(f"OpenAI API call failed: {exc}") from exc

    def to_stream_messages(self, chunk: ChatCompletionChunk) -> Messages:
        """
        Convert an OpenAI API response to a Message object.

        This method extracts relevant information from the API response and constructs a Message object.

        Args:
            response (ChatCompletion): The response object from the OpenAI API.

        Returns:
            Message: A Message object containing the extracted information from the API response.
        """

        # Extract the first choice
        choice = chunk.choices[0]
        message_data = choice.delta
        data = message_data.model_dump()
        if data.get("role") is None:
            data["role"] = "assistant"
        data["is_streaming"] = True
        return [Message.model_validate(data)]

    def to_messages(self, response: ChatCompletion) -> Messages:
        """
        Convert an OpenAI API response to a Message object.

        This method extracts relevant information from the API response and constructs a Message object.

        Args:
            response (ChatCompletion): The response object from the OpenAI API.

        Returns:
            Message: A Message object containing the extracted information from the API response.
        """

        # Extract the first choice
        choice = response.choices[0]
        return [Message.model_validate(choice.message.model_dump())]

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the OpenAITool instance to a dictionary.

        Returns:
            dict: A dictionary containing the attributes of the OpenAITool instance.
        """
        return {
            **super().to_dict(),
        }


class OpenAIToolBuilder(LLMBuilder[OpenAITool]):
    def api_key(self, api_key: Optional[str]) -> Self:
        self.kwargs["api_key"] = api_key
        return self
