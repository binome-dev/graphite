from typing import Any
from typing import Dict

from grafi.common.events.event import EventType
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.workflow_events.workflow_event import WorkflowEvent


class WorkflowFailedEvent(WorkflowEvent):
    event_type: EventType = EventType.WORKFLOW_FAILED
    input_data: PublishToTopicEvent
    error: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.workflow_event_dict(),
            "data": {
                "input_data": self.input_data.to_dict(),
                "error": self.error,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowFailedEvent":
        base_event = cls.workflow_event_base(data)
        input_data = PublishToTopicEvent.from_dict(data["data"]["input_data"])

        return cls(
            **base_event.model_dump(),
            input_data=input_data,
            error=data["data"]["error"],
        )
