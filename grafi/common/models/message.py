import time
from typing import Iterable, Literal, Optional

from openai.types.chat.chat_completion import ChatCompletionMessage
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from pydantic import Field

from grafi.common.models.default_id import default_id


class Message(ChatCompletionMessage):
    name: Optional[str] = None
    message_id: str = default_id
    timestamp: int = Field(default_factory=time.time_ns)
    role: Literal["system", "user", "assistant", "tool"]
    tool_call_id: Optional[str] = None
    tools: Optional[Iterable[ChatCompletionToolParam]] = None
