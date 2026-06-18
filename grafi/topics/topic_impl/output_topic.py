from typing import Any

from pydantic import Field

from grafi.common.pickle_guard import safe_b64_pickle_loads
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
