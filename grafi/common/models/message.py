import time
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Literal
from typing import Optional
from typing import Union

from openai.types.chat.chat_completion import ChatCompletionMessage
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from pydantic import Field

from grafi.common.models.default_id import default_id


# from typing_extensions import Literal


class Message(ChatCompletionMessage):
    name: Optional[str] = None
    message_id: str = default_id
    timestamp: int = Field(default_factory=time.time_ns)
    content: Union[
        str,
        Dict[str, Any],
        List[Dict[str, Any]],
        None,
    ] = None
    role: Literal["system", "user", "assistant", "tool"]
    tool_call_id: Optional[str] = None
    tools: Optional[Iterable[ChatCompletionToolParam]] = None
