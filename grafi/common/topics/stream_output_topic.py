from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Self

from loguru import logger
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.stream_output_topic_event import (
    StreamOutputTopicEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.topic_base import AGENT_RESERVED_TOPICS
from grafi.common.topics.topic_base import TopicBase


AGENT_STREAM_OUTPUT_TOPIC = "agent_stream_output_topic"
AGENT_RESERVED_TOPICS.extend([AGENT_STREAM_OUTPUT_TOPIC])


class StreamOutputTopic(TopicBase):
    """
    A topic implementation for output events.
    """

    name: str = AGENT_STREAM_OUTPUT_TOPIC
    publish_event_handler: Optional[Callable[[StreamOutputTopicEvent], None]] = Field(
        default=None
    )
    consumption_offsets: Dict[str, int] = {}

    class Builder(TopicBase.Builder):

        _topic: "StreamOutputTopic"

        def __init__(self) -> None:
            self._topic = self._init_topic()

        def _init_topic(self) -> "StreamOutputTopic":
            return StreamOutputTopic.model_construct()

        def publish_event_handler(
            self, publish_event_handler: Callable[[StreamOutputTopicEvent], None]
        ) -> Self:
            self._topic.publish_event_handler = publish_event_handler
            return self

        def build(self) -> "StreamOutputTopic":
            return self._topic

    def publish_data(
        self,
        execution_context: ExecutionContext,
        publisher_name: str,
        publisher_type: str,
        data: MsgsAGen,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> Optional[StreamOutputTopicEvent]:
        """
        Publishes a message's event ID to this topic if it meets the condition.
        """

        event = StreamOutputTopicEvent(
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
        if self.publish_event_handler:
            self.publish_event_handler(event)
        logger.info(f"[{self.name}] Message published with event_id: {event.event_id}")
        return event

    def consume(self, consumer_name: str) -> Optional[StreamOutputTopicEvent]:
        """
        Retrieve new/unconsumed messages for the given node by fetching them
        from the event store based on event IDs. Once retrieved, the node's
        consumption offset is updated so these messages won't be retrieved again.

        :param node_id: A unique identifier for the consuming node.
        :return: A list of new messages that were not yet consumed by this node.
        """
        already_consumed = self.consumption_offsets.get(consumer_name, 0)
        total_published = len(self.topic_events)

        if already_consumed >= total_published:
            return None

        # Get the new event IDs
        new_event = self.topic_events[already_consumed]

        # Update the offset
        self.consumption_offsets[consumer_name] = already_consumed + 1

        return new_event


agent_stream_output_topic = StreamOutputTopic(name=AGENT_STREAM_OUTPUT_TOPIC)
