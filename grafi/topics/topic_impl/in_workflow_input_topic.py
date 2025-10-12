import base64
from typing import Any

import cloudpickle
from pydantic import Field

from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType


class InWorkflowInputTopic(Topic):
    """
    Input topic for receiving messages DURING an active workflow.

    Key differences from InputTopic (agent input):
    - InputTopic: Starts a NEW workflow (e.g., initial user query)
    - InWorkflowInputTopic: Continues EXISTING workflow (e.g., human approval, form response)

    Use this when:
    - Waiting for human responses mid-workflow
    - Receiving async callbacks from external systems
    - Implementing multi-step interactions

    Example:
        # Receive human approval during workflow execution
        approval_topic = InWorkflowInputTopic(name="human_approval")

    Attributes:
        type (str): A constant indicating the type of the topic, set to
            `IN_WORKFLOW_INPUT_TOPIC_TYPE`.
    """

    type: TopicType = Field(default=TopicType.IN_WORKFLOW_INPUT_TOPIC_TYPE)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InWorkflowInputTopic":
        """
        Create a Topic instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the Topic.

        Returns:
            InWorkflowInputTopic: A Topic instance created from the dictionary.

        """
        return cls(
            name=data["name"],
            type=data["type"],
            condition=cloudpickle.loads(
                base64.b64decode(data["condition"].encode("utf-8"))
            ),
        )
