import base64
from typing import Any
from typing import TypeVar

import cloudpickle

from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_base import TopicBaseBuilder


class Topic(TopicBase):
    """
    Represents a topic in a message queue system.
    """

    @classmethod
    def builder(cls) -> "TopicBuilder":
        """
        Returns a builder for Topic.
        """
        return TopicBuilder(cls)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the topic to a dictionary.
        """
        return {
            **super().to_dict(),
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "Topic":
        """
        Create a Topic instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the Topic.

        Returns:
            Topic: A Topic instance created from the dictionary.
        """
        return cls(
            name=data["name"],
            type=data["type"],
            condition=cloudpickle.loads(
                base64.b64decode(data["condition"].encode("utf-8"))
            ),
        )


T_T = TypeVar("T_T", bound=Topic)


class TopicBuilder(TopicBaseBuilder[T_T]):
    """
    Builder for creating instances of Topic.
    """

    pass
