from typing import Any
from typing import Dict
from typing import Optional

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic_core import PydanticSerializationError
from pydantic_core import to_json


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

    @field_validator("kwargs")
    @classmethod
    def _storable(cls, kwargs: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Each value must be one JSON can hold, as the events storing this
        context do: a datetime is stored as its ISO text, an object refused."""
        for key, value in (kwargs or {}).items():
            try:
                to_json(value)
            except PydanticSerializationError as error:
                raise ValueError(
                    f"kwargs[{key!r}] cannot be stored with the events: {error}"
                ) from error
        return kwargs
