import time
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Union

from openai.types.chat.chat_completion_audio import ChatCompletionAudio
from openai.types.chat.chat_completion_message import Annotation
from openai.types.chat.chat_completion_message import FunctionCall
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_role import ChatCompletionRole
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from pydantic import BaseModel
from pydantic import Field

from grafi.common.models.default_id import default_id


# Message class is based on the ChatCompletionMessage from OpenAI, extended to include all the different type of input


class Message(BaseModel):
    name: Optional[str] = None
    message_id: str = default_id
    timestamp: int = Field(default_factory=time.time_ns)
    content: Union[
        str,
        Dict[str, Any],
        List[Dict[str, Any]],
        BaseModel,
        List[BaseModel],
        None,
    ] = None
    refusal: Optional[str] = None
    """The refusal message generated by the model."""

    annotations: Optional[List[Annotation]] = None
    """
    Annotations for the message, when applicable, as when using the
    [web search tool](https://platform.openai.com/docs/guides/tools-web-search?api-mode=chat).
    """

    audio: Optional[ChatCompletionAudio] = None
    """
    If the audio output modality is requested, this object contains data about the
    audio response from the model.
    [Learn more](https://platform.openai.com/docs/guides/audio).
    """
    role: ChatCompletionRole
    tool_call_id: Optional[str] = None
    tools: Optional[Iterable[ChatCompletionToolParam]] = None
    function_call: Optional[FunctionCall] = None
    """Deprecated and replaced by `tool_calls`.

    The name and arguments of a function that should be called, as generated by the
    model.
    """

    tool_calls: Optional[List[ChatCompletionMessageToolCall]] = None
    """The tool calls generated by the model, such as function calls."""

    is_streaming: bool = False


Messages = List[Message]
MsgsAGen = AsyncGenerator[Messages, None]
