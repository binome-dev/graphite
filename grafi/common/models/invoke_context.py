from typing import Any
from typing import Dict
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class InvokeContext(BaseModel):
    """Invoke context for a conversation.
    conversation_id: user start a conversation with the assistant, there could be multiple conversations between the user and the assistant.
    invoke_id: invoke id of each conversation, an invoke can involve multiple agents
    assistant_request_id: assistant_request_id is create when agent receive a request from the user
    user_id: user id
    kwargs: optional field for any additional context or keyword arguments that need to be passed through the workflow
    """

    conversation_id: str = Field(
        description="Unique identifier for a conversation between user and assistant"
    )
    invoke_id: str = Field(
        description="Unique identifier for each conversation invoke - an invoke can involve multiple agents"
    )
    assistant_request_id: str = Field(
        description="Created when an agent receives a request from the user"
    )
    user_id: Optional[str] = Field(
        default="", description="Optional user identifier, defaults to empty string"
    )
    kwargs: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional keyword arguments and context for the workflow",
    )
