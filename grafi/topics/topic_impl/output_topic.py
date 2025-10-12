import base64
from typing import Any

import cloudpickle
from pydantic import Field

from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType


# OutputTopic handles sync and async publishing of messages to the agent output topic.
class OutputTopic(Topic):
    """
    Topic for publishing final workflow execution results.

    This topic serves as the terminal endpoint where completed workflow outcomes
    are delivered. It differs from InWorkflowOutputTopic by handling only final
    results rather than intermediate processing messages.

    The publication to this topic signals the completion of the assistant_request_id
    lifecycle and provides the definitive response to the user's query.

    Example:
        output_topic = OutputTopic(name="agent_response")
        await output_topic.publish(final_result)
    """

    type: TopicType = Field(default=TopicType.AGENT_OUTPUT_TOPIC_TYPE)

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "OutputTopic":
        """
        Create a Topic instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the Topic.

        Returns:
            OutputTopic: A Topic instance created from the dictionary.
        """
        return cls(
            name=data["name"],
            type=data["type"],
            condition=cloudpickle.loads(
                base64.b64decode(data["condition"].encode("utf-8"))
            ),
        )
