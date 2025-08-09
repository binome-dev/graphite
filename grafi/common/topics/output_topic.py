from pydantic import Field

from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_types import TopicType


# OutputTopic handles sync and async publishing of messages to the agent output topic.
class OutputTopic(Topic):
    """
    A topic implementation for output events.
    """

    type: TopicType = Field(default=TopicType.AGENT_OUTPUT_TOPIC_TYPE)
