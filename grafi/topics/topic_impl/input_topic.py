import base64
from typing import Any

import cloudpickle
from pydantic import Field

from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType


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

    type: TopicType = Field(default=TopicType.AGENT_INPUT_TOPIC_TYPE)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InputTopic":
        """
        Create a Topic instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the Topic.

        Returns:
            InputTopic: A Topic instance created from the dictionary.

        """
        return cls(
            name=data["name"],
            type=data["type"],
            condition=cloudpickle.loads(
                base64.b64decode(data["condition"].encode("utf-8"))
            ),
        )
