from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_base import AGENT_INPUT_TOPIC_TYPE


class InputTopic(Topic):
    """
    Represents an input topic in a message queue system.
    
    This class is a specialized type of `Topic` that is used to handle input topics
    in a message queue system. It inherits from the `Topic` base class and sets
    the `type` attribute to `AGENT_INPUT_TOPIC_TYPE`, indicating that it is
    specifically designed for agent input topics.
    
    Usage:
        InputTopic instances are typically used to define and manage the input
        channels for agents in the system. These channels are responsible for
        receiving messages or data that the agents will process.
    
    Attributes:
        type (str): A constant indicating the type of the topic, set to
            `AGENT_INPUT_TOPIC_TYPE`.
    """

    type: str = AGENT_INPUT_TOPIC_TYPE
