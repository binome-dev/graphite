from typing import Any

from pydantic import Field

from grafi.common.pickle_guard import safe_b64_pickle_loads
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
    async def from_dict(cls, data: dict[str, Any]) -> "InputTopic":
        """
        Create a Topic instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the Topic.

        Returns:
            InputTopic: A Topic instance created from the dictionary.

        """
        condition_data = data["condition"]
        if isinstance(condition_data, dict):
            encoded_condition = condition_data["base64"]
        else:
            encoded_condition = condition_data

        return cls(
            name=data["name"],
            type=data["type"],
            condition=safe_b64_pickle_loads(
                encoded_condition, context=f"topic '{data.get('name', '')}' condition"
            ),
        )
