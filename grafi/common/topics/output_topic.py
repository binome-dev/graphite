from pydantic import Field

from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_types import TopicType


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
