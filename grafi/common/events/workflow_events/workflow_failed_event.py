from typing import Any
from typing import Dict

from grafi.common.events.event import EventType
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.workflow_events.workflow_event import WorkflowEvent


class WorkflowFailedEvent(WorkflowEvent):
    event_type: EventType = EventType.WORKFLOW_FAILED
    input_event: PublishToTopicEvent
    error: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.workflow_event_dict(),
            "data": {
                "input_event": self.input_event.to_dict(),
                "error": self.error,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowFailedEvent":
        base_event = cls.workflow_event_base(data)
        input_event = PublishToTopicEvent.from_dict(data["data"]["input_event"])

        return cls(
            **base_event.model_dump(),
            input_event=input_event,
            error=data["data"]["error"],
        )
