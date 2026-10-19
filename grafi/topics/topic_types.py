from enum import Enum


class TopicType(Enum):
    NONE_TOPIC_TYPE = "NoneTopic"
    DEFAULT_TOPIC_TYPE = "Topic"
    AGENT_INPUT_TOPIC_TYPE = "AgentInputTopic"
    AGENT_OUTPUT_TOPIC_TYPE = "AgentOutputTopic"
    IN_WORKFLOW_INPUT_TOPIC_TYPE = "InWorkflowInputTopic"
    IN_WORKFLOW_OUTPUT_TOPIC_TYPE = "InWorkflowOutputTopic"


# Topic types the workflow itself reads as its output.
OUTPUT_TOPIC_TYPES = frozenset(
    {TopicType.AGENT_OUTPUT_TOPIC_TYPE, TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE}
)
