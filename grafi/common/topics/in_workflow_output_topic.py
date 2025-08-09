from typing import Any, List
from typing import Self

from pydantic import Field

from grafi.common.topics.topic import Topic, TopicBuilder
from grafi.common.topics.topic_types import TopicType


# OutputTopic handles sync and async publishing of messages to the agent output topic.
class InWorkflowOutputTopic(Topic):
    """
    Represents an output topic for in-workflow processing.
    """

    type: TopicType = Field(default=TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE)
    paired_in_workflow_input_topic_names: List[str] = Field(default_factory=list)

    @classmethod
    def builder(cls) -> "InWorkflowOutputTopicBuilder":
        """
        Returns a builder for OutputTopic.
        """
        return InWorkflowOutputTopicBuilder(cls)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "paired_in_workflow_input_topic_names": self.paired_in_workflow_input_topic_names,
        }


class InWorkflowOutputTopicBuilder(TopicBuilder[InWorkflowOutputTopic]):
    """
    Builder for creating instances of Topic.
    """

    def paired_in_workflow_input_topic_name(
        self, paired_in_workflow_input_topic_name: str
    ) -> Self:
        if "paired_in_workflow_input_topic_names" not in self.kwargs:
            self.kwargs["paired_in_workflow_input_topic_names"] = []
        self.kwargs["paired_in_workflow_input_topic_names"].append(
            paired_in_workflow_input_topic_name
        )
        return self
