from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import TypeVar

from loguru import logger
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.topics.topic_base import AGENT_OUTPUT_TOPIC_TYPE
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_base import TopicBaseBuilder


# OutputTopic handles sync and async publishing of messages to the agent output topic.
class OutputTopic(TopicBase):
    """
    A topic implementation for output events.
    """

    type: str = AGENT_OUTPUT_TOPIC_TYPE
    publish_event_handler: Optional[Callable[[OutputTopicEvent], None]] = Field(
        default=None
    )

    @classmethod
    def builder(cls) -> "OutputTopicBuilder":
        """
        Returns a builder for OutputTopic.
        """
        return OutputTopicBuilder(cls)

    def publish_data(
        self,
        invoke_context: InvokeContext,
        publisher_name: str,
        publisher_type: str,
        data: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> Optional[OutputTopicEvent]:
        """
        Publishes a message's event ID to this topic if it meets the condition.
        """
        if self.condition(data):
            event = OutputTopicEvent(
                invoke_context=invoke_context,
                topic_name=self.name,
                publisher_name=publisher_name,
                publisher_type=publisher_type,
                data=data,
                consumed_event_ids=[
                    consumed_event.event_id for consumed_event in consumed_events
                ],
                offset=self.event_cache.num_events(),
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
        self,
        invoke_context: InvokeContext,
        publisher_name: str,
        publisher_type: str,
        data: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> Optional[OutputTopicEvent]:
        if self.condition(data):
            event = OutputTopicEvent(
                invoke_context=invoke_context,
                topic_name=self.name,
                publisher_name=publisher_name,
                publisher_type=publisher_type,
                data=data,
                consumed_event_ids=[
                    consumed_event.event_id for consumed_event in consumed_events
                ],
                offset=self.event_cache.num_events(),
            )

            return await self.a_add_event(event)
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict()}


T_O = TypeVar("T_O", bound=OutputTopic)


class OutputTopicBuilder(TopicBaseBuilder[T_O]):
    """
    Builder for creating instances of Topic.
    """

    def publish_event_handler(
        self, publish_event_handler: Callable[[OutputTopicEvent], None]
    ) -> Self:
        self.kwargs["publish_event_handler"] = publish_event_handler
        return self
