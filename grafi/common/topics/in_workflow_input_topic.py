from loguru import logger

from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.message import Messages
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_base import IN_WORKFLOW_INPUT_TOPIC_TYPE


class InWorkflowInputTopic(Topic):
    """
    Represents an input topic in a message queue system.

    This class is a specialized type of `Topic` that is used to handle input topics
    in a message queue system. It inherits from the `Topic` base class and sets
    the `type` attribute to `IN_WORKFLOW_INPUT_TOPIC_TYPE`, indicating that it is
    specifically designed for in-workflow input topics.

    Usage:
        InputTopic instances are typically used to define and manage the input
        channels for agents in the system. These channels are responsible for
        receiving messages or data that the agents will process.

    Attributes:
        type (str): A constant indicating the type of the topic, set to
            `IN_WORKFLOW_INPUT_TOPIC_TYPE`.
    """

    type: str = IN_WORKFLOW_INPUT_TOPIC_TYPE

    def publish_input_data(
        self,
        upstream_event: PublishToTopicEvent | OutputTopicEvent,
        data: Messages,
    ) -> PublishToTopicEvent:
        if self.condition(data):
            event = PublishToTopicEvent(
                invoke_context=upstream_event.invoke_context,
                topic_name=self.name,
                publisher_name=upstream_event.publisher_name,
                publisher_type=upstream_event.publisher_type,
                data=data,
                consumed_event_ids=upstream_event.consumed_event_ids,
                offset=self.event_cache.num_events(),
            )

            self.add_event(event)
            return event
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None

    async def a_publish_input_data(
        self,
        upstream_event: PublishToTopicEvent | OutputTopicEvent,
        data: Messages,
    ) -> PublishToTopicEvent:
        if self.condition(data):
            event = PublishToTopicEvent(
                invoke_context=upstream_event.invoke_context,
                topic_name=self.name,
                publisher_name=upstream_event.publisher_name,
                publisher_type=upstream_event.publisher_type,
                data=data,
                consumed_event_ids=upstream_event.consumed_event_ids,
                offset=self.event_cache.num_events(),
            )

            await self.a_add_event(event)
            return event
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None
