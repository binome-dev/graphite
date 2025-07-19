from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_base import AGENT_INPUT_TOPIC_TYPE


class InputTopic(Topic):
    """
    Represents an input topic in a message queue system.
    """

    type: str = AGENT_INPUT_TOPIC_TYPE
