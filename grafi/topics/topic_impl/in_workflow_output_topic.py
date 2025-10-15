import base64
from typing import Any
from typing import List
from typing import Self

import cloudpickle
from pydantic import Field

from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_impl.topic import TopicBuilder
from grafi.topics.topic_types import TopicType


# OutputTopic handles sync and async publishing of messages to the agent output topic.
class InWorkflowOutputTopic(Topic):
    """
    Output topic for sending messages during an active workflow that expect responses.

    In Graphite's workflow graph, this topic can pair with one or more InWorkflowInputTopics
    to route responses correctly. When an event is sent through this output topic, any
    response event knows which InWorkflowInputTopic(s) it should be routed to.

    Attributes:
        paired_in_workflow_input_topic_names: List of InWorkflowInputTopic names that
            will receive responses. The system uses this to route response events to
            the correct input topics in the workflow graph.

    Use cases:
        - Human approval workflows (route to approve/reject input topics)
        - Multi-choice interactions (route to different paths based on response)
        - External system callbacks (route responses to appropriate handlers)

    Example:
        # Single pairing for simple approval
        output = InWorkflowOutputTopic(
            name="approval_request",
            paired_in_workflow_input_topic_names=["human_response"]
        )

        # Multiple pairings for different response paths
        output = InWorkflowOutputTopic(
            name="review_request",
            paired_in_workflow_input_topic_names=["approve", "reject", "escalate"]
        )
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

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "InWorkflowOutputTopic":
        """
        Create a Topic instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the Topic.

        Returns:
            InWorkflowOutputTopic: A Topic instance created from the dictionary.
        """
        return cls(
            name=data["name"],
            type=data["type"],
            condition=cloudpickle.loads(
                base64.b64decode(data["condition"].encode("utf-8"))
            ),
            paired_in_workflow_input_topic_names=data.get(
                "paired_in_workflow_input_topic_names", []
            ),
        )


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
