from pydantic import Field

from grafi.topics.topic import Topic
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
