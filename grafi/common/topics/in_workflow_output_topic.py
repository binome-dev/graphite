from typing import Self

from grafi.common.topics.output_topic import OutputTopic
from grafi.common.topics.output_topic import OutputTopicBuilder
from grafi.common.topics.topic_base import IN_WORKFLOW_OUTPUT_TOPIC_TYPE


# OutputTopic handles sync and async publishing of messages to the agent output topic.
class InWorkflowOutputTopic(OutputTopic):
    """
    Represents an output topic for in-workflow processing.
    """

    type: str = IN_WORKFLOW_OUTPUT_TOPIC_TYPE
    paired_in_workflow_input_topic_name: str

    @classmethod
    def builder(cls) -> "InWorkflowOutputTopicBuilder":
        """
        Returns a builder for OutputTopic.
        """
        return InWorkflowOutputTopicBuilder(cls)

    def to_dict(self):

        return {
            **super().to_dict(),
            "paired_in_workflow_input_topic_name": self.paired_in_workflow_input_topic_name,
        }


class InWorkflowOutputTopicBuilder(OutputTopicBuilder[InWorkflowOutputTopic]):
    """
    Builder for creating instances of Topic.
    """

    def paired_in_workflow_input_topic_name(
        self, paired_in_workflow_input_topic_name: str
    ) -> Self:
        self.kwargs["paired_in_workflow_input_topic_name"] = (
            paired_in_workflow_input_topic_name
        )
        return self
