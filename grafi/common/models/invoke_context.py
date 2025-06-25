from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class InvokeContext(BaseModel):
    """Invoke context for a conversation.
    conversation_id: user start a conversation with the assistant, there could be multiple conversations between the user and the assistant.
    invoke_id: invoke id of each conversation, an invoke can involve multiple agents
    assistant_request_id: assistant_request_id is create when agent receive a request from the user
    user_id: user id
    """

    conversation_id: str
    invoke_id: str
    assistant_request_id: str
    user_id: Optional[str] = Field(default="")
