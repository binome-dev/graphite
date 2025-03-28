from typing import Callable, Dict, List, Optional

from loguru import logger
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_base import AGENT_RESERVED_TOPICS

AGENT_STREAM_OUTPUT_TOPIC = "agent_stream_output_topic"
AGENT_OUTPUT_TOPIC = "agent_output_topic"
AGENT_RESERVED_TOPICS.extend([AGENT_STREAM_OUTPUT_TOPIC, AGENT_OUTPUT_TOPIC])


class OutputTopic(Topic):
    """
    A topic implementation for output events.
    """

    name: str = AGENT_OUTPUT_TOPIC
    publish_event_handler: Optional[Callable[[OutputTopicEvent], None]] = Field(
        default=None
    )
    topic_events: List[OutputTopicEvent] = []
    consumption_offsets: Dict[str, int] = {}

    class Builder:
        def __init__(self):
            self._topic = OutputTopic()

        def publish_event_handler(
            self, publish_event_handler: Callable[[OutputTopicEvent], None]
        ):
            self._topic.publish_event_handler = publish_event_handler
            return self

        def build(self) -> "OutputTopic":
            return self._topic

    def publish_data(
        self,
        execution_context: ExecutionContext,
        publisher_name: str,
        publisher_type: str,
        data: List[Message],
        consumed_events: List[ConsumeFromTopicEvent],
    ):
        """
        Publishes a message's event ID to this topic if it meets the condition.
        """
        if self.condition(data):
            event = OutputTopicEvent(
                execution_context=execution_context,
                topic_name=self.name,
                publisher_name=publisher_name,
                publisher_type=publisher_type,
                data=data,
                consumed_event_ids=[
                    consumed_event.event_id for consumed_event in consumed_events
                ],
                offset=len(self.topic_events),
            )
            self.topic_events.append(event)

            self.publish_event_handler(event)
            logger.info(
                f"[{self.name}] Message published with event_id: {event.event_id}"
            )
            return event
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None


agent_stream_output_topic = OutputTopic(name=AGENT_STREAM_OUTPUT_TOPIC)
agent_output_topic = OutputTopic(name=AGENT_OUTPUT_TOPIC)
