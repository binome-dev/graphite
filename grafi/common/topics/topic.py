from typing import TypeVar
from typing import Any
from typing import Callable
from typing import Optional
from typing import Self

from loguru import logger
from pydantic import Field

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_base import TopicBaseBuilder


class Topic(TopicBase):
    """
    Represents a topic in a message queue system.
    """

    publish_event_handler: Optional[Callable[[PublishToTopicEvent], None]] = Field(
        default=None
    )

    @classmethod
    def builder(cls) -> "TopicBuilder":
        """
        Returns a builder for Topic.
        """
        return TopicBuilder(cls)

    def publish_data(
        self, publish_event: PublishToTopicEvent
    ) -> Optional[PublishToTopicEvent]:
        """
        Publishes a message's event ID to this topic if it meets the condition.
        """
        if self.condition(publish_event.data):
            event = publish_event.model_copy(
                update={
                    "topic_name": self.name,
                    "topic_type": self.type,
                },
                deep=True,
            )
            # Add event to cache and update total_published
            event = self.add_event(event)
            if self.publish_event_handler:
                self.publish_event_handler(event)  # type: ignore[arg-type]
            logger.info(
                f"[{self.name}] Message published with event_id: {event.event_id}"
            )
            return event
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None

    async def a_publish_data(
        self, publish_event: PublishToTopicEvent
    ) -> Optional[PublishToTopicEvent]:
        if self.condition(publish_event.data):
            event = publish_event.model_copy(
                update={
                    "topic_name": self.name,
                    "topic_type": self.type,
                },
                deep=True,
            )
            return await self.a_add_event(event)
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the topic to a dictionary.
        """
        return {
            **super().to_dict(),
        }


T_T = TypeVar("T_T", bound=Topic)


class TopicBuilder(TopicBaseBuilder[T_T]):
    """
    Builder for creating instances of Topic.
    """

    def publish_event_handler(
        self, publish_event_handler: Callable[[PublishToTopicEvent], None]
    ) -> Self:
        self.kwargs["publish_event_handler"] = publish_event_handler
        return self
