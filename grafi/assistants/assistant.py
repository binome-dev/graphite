import base64
import json
import os
from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import Dict

import cloudpickle
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.assistants.assistant_base import AssistantBase
from grafi.common.decorators.record_decorators import record_assistant_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.nodes.node import Node
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.expressions.topic_expression import CombinedExpr
from grafi.topics.expressions.topic_expression import LogicalOp
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class Assistant(AssistantBase):
    """
    An abstract base class for assistants that use language models to process input and generate responses.

    Attributes:
        name (str): The name of the assistant
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
    """

    @record_assistant_invoke
    async def invoke(
        self, input_data: PublishToTopicEvent, is_sequential: bool = False
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """
        Process the input data through the LLM workflow, make function calls, and return the generated response.
        Args:
            invoke_context (InvokeContext): Context containing invoke information
            input_data (Messages): List of input messages to be processed

        Returns:
            Messages: List of generated response messages, sorted by timestamp

        Raises:
            ValueError: If the OpenAI API key is not provided and not found in environment variables
        """

        # Invoke the workflow with the input data
        async for output in self.workflow.invoke(input_data, is_sequential):
            yield output

    def to_dict(self) -> dict[str, Any]:
        """Convert the workflow to a dictionary."""
        return {
            **super().to_dict(),
        }

    def generate_manifest(self, output_dir: str = ".") -> str:
        """
        Generate a manifest file for the assistant.

        Args:
            output_dir (str): Directory where the manifest file will be saved

        Returns:
            str: Path to the generated manifest file
        """
        manifest_seed = self.to_dict()

        # Add dependencies between node and topics
        manifest_dict = manifest_seed

        output_path = os.path.join(output_dir, f"{self.name}_manifest.json")
        with open(output_path, "w") as f:
            f.write(json.dumps(manifest_dict, indent=4))

    @staticmethod
    def _deserialize_function(encoded_str: str) -> Callable:
        """Deserialize a cloudpickle-encoded function from base64 string."""
        pickled_bytes = base64.b64decode(encoded_str.encode("utf-8"))
        return cloudpickle.loads(pickled_bytes)

    @staticmethod
    def _deserialize_topic(topic_dict: Dict[str, Any]) -> TopicBase:
        """Deserialize a topic from its dictionary representation."""
        topic_name = topic_dict["name"]
        topic_type = topic_dict["type"]
        condition = Assistant._deserialize_function(topic_dict["condition"])

        # Create the appropriate topic type based on the type field
        if topic_type == "AgentInputTopic":
            return InputTopic(name=topic_name, condition=condition)
        elif topic_type == "AgentOutputTopic":
            return OutputTopic(name=topic_name, condition=condition)
        else:
            return Topic(name=topic_name, condition=condition)

    @staticmethod
    def _deserialize_subscription_expression(
        expr_dict: Dict[str, Any], topics: Dict[str, TopicBase]
    ) -> Any:
        """Recursively deserialize a subscription expression."""
        if "topic" in expr_dict:
            # This is a TopicExpr
            topic_name = expr_dict["topic"]
            topic = topics.get(topic_name)
            if not topic:
                raise ValueError(f"Unknown topic: {topic_name}")
            return TopicExpr(topic=topic)
        elif "op" in expr_dict:
            # This is a CombinedExpr
            op = LogicalOp(expr_dict["op"])
            left = Assistant._deserialize_subscription_expression(
                expr_dict["left"], topics
            )
            right = Assistant._deserialize_subscription_expression(
                expr_dict["right"], topics
            )
            return CombinedExpr(op=op, left=left, right=right)
        else:
            raise ValueError(f"Unknown expression type: {expr_dict}")

    @staticmethod
    def _deserialize_tool(tool_dict: Dict[str, Any]) -> Any:
        """Deserialize a tool from its dictionary representation."""
        tool_class = tool_dict["class"]

        if tool_class == "OpenAITool":
            # Get the actual API key from environment
            api_key = os.getenv("OPENAI_API_KEY", "")
            return OpenAITool(
                name=tool_dict["name"],
                api_key=api_key,
                model=tool_dict["model"],
                system_message=tool_dict["system_message"],
                chat_params=tool_dict.get("chat_params", {}),
                is_streaming=tool_dict.get("is_streaming", False),
                structured_output=tool_dict.get("structured_output", False),
            )
        elif tool_class == "TavilyTool":
            # Get the actual API key from environment
            tavily_api_key = os.getenv("TAVILY_API_KEY")
            if not tavily_api_key:
                raise ValueError("TAVILY_API_KEY environment variable not set")
            return (
                TavilyTool.builder()
                .name(tool_dict["name"])
                .api_key(tavily_api_key)
                .search_depth(tool_dict.get("search_depth", "advanced"))
                .max_tokens(tool_dict.get("max_tokens", 6000))
                .build()
            )
        else:
            raise ValueError(f"Unknown tool class: {tool_class}")

    @staticmethod
    def _deserialize_node(
        node_dict: Dict[str, Any], topics: Dict[str, TopicBase]
    ) -> Node:
        """Deserialize a node from its dictionary representation."""
        # Deserialize the tool
        tool = Assistant._deserialize_tool(node_dict["tool"])

        # Deserialize subscribed expressions
        subscribed_expressions = []
        for expr_dict in node_dict["subscribed_expressions"]:
            expr = Assistant._deserialize_subscription_expression(expr_dict, topics)
            subscribed_expressions.append(expr)

        # Deserialize publish_to topics
        publish_to_topics = []
        for topic_name in node_dict["publish_to"]:
            # Check if topic already exists in topics dict
            if topic_name in topics:
                publish_to_topics.append(topics[topic_name])
            else:
                raise ValueError(f"Unknown topic: {topic_name}")

        # Build the node
        node_builder = Node.builder().name(node_dict["name"]).tool(tool)

        # Add subscriptions
        for expr in subscribed_expressions:
            node_builder = node_builder.subscribe(expr)

        # Add publish_to topics
        for topic in publish_to_topics:
            node_builder = node_builder.publish_to(topic)

        return node_builder.build()

    @staticmethod
    def _deserialize_workflow(workflow_dict: Dict[str, Any]) -> EventDrivenWorkflow:
        """Deserialize a workflow from its dictionary representation."""
        # First, deserialize all topics
        topics: Dict[str, TopicBase] = {}
        for topic_name, topic_dict in workflow_dict["topics"].items():
            topics[topic_name] = Assistant._deserialize_topic(topic_dict)

        # Deserialize all nodes
        nodes = {}
        for node_name, node_dict in workflow_dict["nodes"].items():
            nodes[node_name] = Assistant._deserialize_node(node_dict, topics)

        # Build the workflow
        workflow_builder = EventDrivenWorkflow.builder().name(workflow_dict["name"])

        for node in nodes.values():
            workflow_builder = workflow_builder.node(node)

        return workflow_builder.build()

    @classmethod
    def load_from_manifest(cls, manifest_json: str) -> "Assistant":
        """
        Load an assistant from a manifest JSON string.

        Args:
            manifest_json (str): JSON string containing the assistant manifest

        Returns:
            Assistant: The deserialized assistant instance

        Raises:
            NotImplementedError: Subclasses must implement this method
        """
        manifest_dict = json.loads(manifest_json)

        # Create a new instance
        instance = cls.model_construct()
        instance.name = manifest_dict.get("name", "Assistant")
        instance.type = manifest_dict.get("type", "assistant")
        instance.oi_span_type = OpenInferenceSpanKindValues(
            manifest_dict.get("oi_span_type", "AGENT")
        )
        instance.workflow = cls._deserialize_workflow(manifest_dict.get("workflow", {}))

        return instance
