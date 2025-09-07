from enum import Enum


class TopicType(Enum):
    NONE_TOPIC_TYPE = "NoneTopic"
    DEFAULT_TOPIC_TYPE = "Topic"
    AGENT_INPUT_TOPIC_TYPE = "AgentInputTopic"
    AGENT_OUTPUT_TOPIC_TYPE = "AgentOutputTopic"
    IN_WORKFLOW_INPUT_TOPIC_TYPE = "InWorkflowInputTopic"
    IN_WORKFLOW_OUTPUT_TOPIC_TYPE = "InWorkflowOutputTopic"
