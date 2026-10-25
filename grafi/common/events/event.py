from datetime import datetime
from datetime import timezone
from enum import Enum
from typing import Any
from typing import Final
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from grafi.common.legacy import warn_never_called
from grafi.common.models.default_id import default_id
from grafi.common.models.event_id import EventId
from grafi.common.models.invoke_context import InvokeContext

# The revision of the events' JSON form this grafi writes: see
# grafi.common.events.event_codec, which reads earlier revisions too.
EVENT_VERSION: Final = 2


class EventType(Enum):
    NODE_INVOKE = "NodeInvoke"
    NODE_RESPOND = "NodeRespond"
    NODE_FAILED = "NodeFailed"
    TOOL_INVOKE = "ToolInvoke"
    TOOL_RESPOND = "ToolRespond"
    TOOL_FAILED = "ToolFailed"
    WORKFLOW_INVOKE = "WorkflowInvoke"
    WORKFLOW_RESPOND = "WorkflowRespond"
    WORKFLOW_FAILED = "WorkflowFailed"
    ASSISTANT_INVOKE = "AssistantInvoke"
    ASSISTANT_RESPOND = "AssistantRespond"
    ASSISTANT_FAILED = "AssistantFailed"

    TOPIC_EVENT = "TopicEvent"
    PUBLISH_TO_TOPIC = "PublishToTopic"
    CONSUME_FROM_TOPIC = "ConsumeFromTopic"


# The types of the events of topics, which a run's history is made of.
TOPIC_EVENT_TYPES = frozenset(
    {EventType.TOPIC_EVENT, EventType.PUBLISH_TO_TOPIC, EventType.CONSUME_FROM_TOPIC}
)


# The methods an event of grafi 0.0.36 and earlier had, which nothing calls.
_REMOVED_METHODS = {
    name: 'an event is stored as model_dump(mode="json"), and read back with '
    "model_validate; read rows its to_dict() stored in a "
    'model_validator(mode="before") (see Custom Event Types).'
    for name in ("to_dict", "from_dict")
}


class Event(BaseModel):
    """A fact an event store records.

    Its JSON form, ``model_dump(mode="json")``, is what a store keeps: its
    fields, flat, with ``event_version`` naming the form's revision. An
    :class:`~grafi.common.events.event_codec.EventCodec` decodes it back,
    choosing the class by ``event_type``, which each class fixes. An event is
    saved as its own class even where a field declares one of its bases.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True, polymorphic_serialization=True
    )

    event_id: EventId = default_id
    # This revision: decoding upgrades an earlier one before validating.
    event_version: Literal[2] = EVENT_VERSION
    invoke_context: InvokeContext
    event_type: EventType

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        warn_never_called(cls, Event, lambda _: _REMOVED_METHODS)

    @field_validator("event_type")
    @classmethod
    def _of_this_class(cls, event_type: EventType) -> EventType:
        """A class with an event type of its own holds only that type."""
        own = cls.model_fields["event_type"].default
        if isinstance(own, EventType) and event_type is not own:
            raise ValueError(
                f"A {cls.__name__} has event_type {own.value!r}, "
                f"not {event_type.value!r}"
            )
        return event_type
