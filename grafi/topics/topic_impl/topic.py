from typing import Self
from typing import TypeVar

from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_base import TopicBaseBuilder


class Topic(TopicBase):
    """
    Represents a topic in a message queue system.
    """

    @classmethod
    def builder(cls) -> "TopicBuilder[Self]":
        """
        Returns a builder for Topic.
        """
        return TopicBuilder(cls)


T_T = TypeVar("T_T", bound=Topic)


class TopicBuilder(TopicBaseBuilder[T_T]):
    """
    Builder for creating instances of Topic.
    """

    pass
