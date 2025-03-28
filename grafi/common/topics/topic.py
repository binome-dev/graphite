from typing import List

from loguru import logger

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.topics.topic_base import AGENT_INPUT_TOPIC, TopicBase


class Topic(TopicBase):
    """
    Represents a topic in a message queue system.
    """

    class Builder(TopicBase.Builder):
        def __init__(self):
            self._topic = Topic()

        def build(self) -> "Topic":
            return self._topic

    def publish_data(
        self,
        execution_context: ExecutionContext,
        publisher_name: str,
        publisher_type: str,
        data: List[Message],
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> PublishToTopicEvent:
        """
        Publishes a message's event ID to this topic if it meets the condition.
        """
        if self.condition(data):
            event = PublishToTopicEvent(
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

    def can_consume(self, consumer_name: str) -> bool:
        """
        Checks whether the given node can consume any new/unread messages
        from this topic (i.e., if there are event IDs that the node hasn't
        already consumed).
        """
        already_consumed = self.consumption_offsets.get(consumer_name, 0)
        total_published = len(self.topic_events)
        return already_consumed < total_published

    def consume(self, consumer_name: str) -> List[PublishToTopicEvent]:
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
            return []

        # Get the new event IDs
        new_events = self.topic_events[already_consumed:]

        # Update the offset
        self.consumption_offsets[consumer_name] = total_published

        return new_events


agent_input_topic = Topic(name=AGENT_INPUT_TOPIC)
