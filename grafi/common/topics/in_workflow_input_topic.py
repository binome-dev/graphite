from pydantic import Field
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_types import TopicType


class InWorkflowInputTopic(Topic):
    """
    Represents an input topic for in-workflow processing.

    Attributes:
        type (str): A constant indicating the type of the topic, set to
            `IN_WORKFLOW_INPUT_TOPIC_TYPE`.
    """

    type: TopicType = Field(default=TopicType.IN_WORKFLOW_INPUT_TOPIC_TYPE)
