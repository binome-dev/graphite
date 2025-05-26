from collections import deque
from typing import Any
from typing import Dict
from typing import List
from typing import Self

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.containers.container import container
from grafi.common.decorators.record_workflow_a_execution import (
    record_workflow_a_execution,
)
from grafi.common.decorators.record_workflow_execution import record_workflow_execution
from grafi.common.events.event import Event
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions.duplicate_node_error import DuplicateNodeError
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.human_request_topic import HumanRequestTopic
from grafi.common.topics.output_topic import AGENT_OUTPUT_TOPIC
from grafi.common.topics.stream_output_topic import StreamOutputTopic
from grafi.common.topics.topic import AGENT_INPUT_TOPIC
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_expression import extract_topics
from grafi.nodes.impl.llm_function_call_node import LLMFunctionCallNode
from grafi.nodes.impl.llm_node import LLMNode
from grafi.nodes.node import Node
from grafi.tools.llms.llm_stream_response_command import LLMStreamResponseCommand
from grafi.workflows.workflow import Workflow


class EventDrivenWorkflow(Workflow):
    """
    An event-driven workflow that executes a directed graph of Nodes in response to topic publish events.

    This workflow can handle streaming events via `StreamTopicEvent` and relay them to a custom
    `stream_event_handler`.
    """

    name: str = "EventDrivenWorkflow"
    type: str = "EventDrivenWorkflow"

    # OpenInference semantic attribute
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.AGENT

    # All nodes that belong to this workflow, keyed by node name
    nodes: Dict[str, Node] = {}

    # Topics known to this workflow (e.g., "agent_input", "agent_stream_output")
    topics: Dict[str, TopicBase] = {}

    # Mapping of topic_name -> list of node_names that subscribe to that topic
    topic_nodes: Dict[str, List[str]] = {}

    # Event graph for this workflow
    # Queue of nodes that are ready to execute (in response to published events)
    execution_queue: deque[Node] = deque()

    # Optional callback that handles output events
    # Including agent output event, stream event and hil event

    class Builder(Workflow.Builder):
        """Concrete builder for EventDrivenWorkflow."""

        _workflow: "EventDrivenWorkflow"

        def __init__(self) -> None:
            self._workflow = self._init_workflow()

        def _init_workflow(self) -> "EventDrivenWorkflow":
            return EventDrivenWorkflow.model_construct()

        def node(self, node: Node) -> Self:
            """
            Add a Node to this workflow.

            Raises:
                DuplicateNodeError: if a node with the same name is already registered.
            """
            if node.name in self._workflow.nodes:
                raise DuplicateNodeError(node)
            self._workflow.nodes[node.name] = node
            return self

        def build(self) -> "EventDrivenWorkflow":
            """
            Construct and return the EventDrivenStreamWorkflow.
            Sets up topic subscriptions and node-to-topic mappings.
            """

            # 1) Gather all topics from node subscriptions/publishes
            for node_name, node in self._workflow.nodes.items():
                # For each subscription expression, parse out one or more topics
                for expr in node.subscribed_expressions:
                    found_topics = extract_topics(expr)
                    for t in found_topics:
                        self._add_topic(t)
                        self._workflow.topic_nodes.setdefault(t.name, []).append(
                            node_name
                        )

                # For each publish topic, ensure it's registered
                for topic in node.publish_to:
                    self._add_topic(topic)

                    # If the topic is for streaming, attach the specialized handler
                    if isinstance(topic, HumanRequestTopic):
                        topic.publish_to_human_event_handler = self._workflow.on_event

            # 2) Verify there is an agent input topic
            if (
                AGENT_INPUT_TOPIC not in self._workflow.topics
                and AGENT_OUTPUT_TOPIC not in self._workflow.topics
            ):
                raise ValueError(
                    "Agent input output topic not found in workflow topics."
                )

            # 3) For any function-calling nodes, link them with the LLM nodes that produce their inputs
            self._handle_function_calling_nodes()

            return self._workflow

        def _add_topic(self, topic: TopicBase) -> None:
            """
            Registers the topic within the workflow if it's not already present
            and sets a default publish handler.
            """
            if topic.name not in self._workflow.topics:
                # Default event handler
                topic.publish_event_handler = self._workflow.on_event
                self._workflow.topics[topic.name] = topic

        def _handle_function_calling_nodes(self) -> None:
            """
            If there are LLMFunctionCallNode(s), we link them with the LLMNode(s)
            that publish to the same topic, so that the LLM can carry the function specs.
            """
            # Find all function-calling nodes
            function_calling_nodes = [
                node
                for node in self._workflow.nodes.values()
                if isinstance(node, LLMFunctionCallNode)
            ]

            # Map each topic -> the nodes that publish to it
            published_topics_to_nodes: Dict[str, List[LLMNode]] = {}

            published_topics_to_nodes = {
                topic.name: [node]
                for node in self._workflow.nodes.values()
                if isinstance(node, LLMNode)
                for topic in node.publish_to
            }

            # If a function node subscribes to a topic that an LLMNode publishes to,
            # we add the function specs to the LLM node.
            for function_node in function_calling_nodes:
                for topic_name in function_node._subscribed_topics:
                    for publisher_node in published_topics_to_nodes.get(topic_name, []):
                        publisher_node.add_function_spec(
                            function_node.get_function_specs()
                        )

    def _publish_events(
        self,
        node: Node,
        execution_context: ExecutionContext,
        result: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> None:
        published_events = []
        for topic in node.publish_to:
            event = topic.publish_data(
                execution_context=execution_context,
                publisher_name=node.name,
                publisher_type=node.type,
                data=result,
                consumed_events=consumed_events,
            )
            if event:
                published_events.append(event)

        all_events: List[Event] = []
        all_events.extend(consumed_events)
        all_events.extend(published_events)

        container.event_store.record_events(all_events)

    def _publish_stream_event(
        self,
        node: Node,
        execution_context: ExecutionContext,
        result: MsgsAGen,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> None:
        published_events = []
        for topic in node.publish_to:
            # Only publish to stream topic, other topic will raise warning
            if isinstance(topic, StreamOutputTopic):
                event = topic.publish_data(
                    execution_context=execution_context,
                    publisher_name=node.name,
                    publisher_type=node.type,
                    data=result,
                    consumed_events=consumed_events,
                )

                if event:
                    published_events.append(event)
            else:
                # Raise warning if the topic is not stream topic
                logger.warning(
                    f"Node {node.name} publish to non-stream topic {topic.name}, "
                    "please check the node configuration."
                )

        all_events: List[Event] = []
        all_events.extend(consumed_events)
        all_events.extend(published_events)

        container.event_store.record_events(all_events)

    @record_workflow_execution
    def execute(self, execution_context: ExecutionContext, input: Messages) -> None:
        """
        Execute the workflow with the given context and input.
        Returns results when all nodes complete processing.
        """
        self.initial_workflow(execution_context, input)

        # Process nodes until execution queue is empty
        while self.execution_queue:
            node = self.execution_queue.popleft()

            # Given node, collect all the messages can be linked to it

            node_consumed_events: List[ConsumeFromTopicEvent] = self.get_node_input(
                node
            )

            # Execute node with collected inputs
            if node_consumed_events:
                result = node.execute(execution_context, node_consumed_events)

                self._publish_events(
                    node, execution_context, result, node_consumed_events
                )

    @record_workflow_a_execution
    async def a_execute(
        self, execution_context: ExecutionContext, input: Messages
    ) -> None:
        """
        Run the workflow until the execution queue is empty.
        Publishes topic events as nodes finish.
        """
        # 1 – initial seeding
        self.initial_workflow(execution_context, input)

        # 2 – process nodes breadth‑first
        while self.execution_queue:
            node = self.execution_queue.popleft()

            node_input: List[ConsumeFromTopicEvent] = self.get_node_input(node)
            if not node_input:
                continue

            # Execute node with collected inputs

            if isinstance(node.command, LLMStreamResponseCommand):
                # Stream node usually would be the last node of the workflow which will return to user.
                # In this case we return the async generator to the caller
                stream_result = node.a_execute(execution_context, node_input)

                self._publish_stream_event(
                    node, execution_context, stream_result, node_input
                )
            else:
                async for messages in node.a_execute(execution_context, node_input):
                    # if the node sometimes yields a single Message, normalise to list
                    self._publish_events(node, execution_context, messages, node_input)

    def get_node_input(self, node: Node) -> List[ConsumeFromTopicEvent]:
        consumed_events: List[ConsumeFromTopicEvent] = []

        node_subscribed_topics = node._subscribed_topics.values()

        # Process each topic the node is subscribed to
        for subscribed_topic in node_subscribed_topics:
            if subscribed_topic.can_consume(node.name):
                # Get messages from topic and create consume events
                node_consumed_events = subscribed_topic.consume(node.name)
                for event in node_consumed_events:
                    consumed_event = ConsumeFromTopicEvent(
                        execution_context=event.execution_context,
                        topic_name=event.topic_name,
                        consumer_name=node.name,
                        consumer_type=node.type,
                        offset=event.offset,
                        data=event.data,
                    )
                    consumed_events.append(consumed_event)

        return consumed_events

    def on_event(self, event: TopicEvent) -> None:
        """Handle topic publish events and trigger node execution if conditions are met."""
        if not isinstance(event, PublishToTopicEvent):
            return

        if isinstance(event, OutputTopicEvent):
            return

        topic_name = event.topic_name
        if topic_name not in self.topic_nodes:
            return

        # Get all nodes subscribed to this topic
        subscribed_nodes = self.topic_nodes[topic_name]

        for node_name in subscribed_nodes:
            node = self.nodes[node_name]
            # Check if node has new messages to consume
            if node.can_execute():
                self.execution_queue.append(node)

    def initial_workflow(
        self, execution_context: ExecutionContext, input: Messages
    ) -> Any:
        """Restore the workflow state from stored events."""

        # Reset all the topics

        for topic in self.topics.values():
            topic.reset()

        events = [
            event
            for event in container.event_store.get_agent_events(
                execution_context.assistant_request_id
            )
            if isinstance(event, TopicEvent)
        ]

        if len(events) == 0:

            # Initialize by publish input data to input topic
            input_topic = self.topics.get(AGENT_INPUT_TOPIC)
            if input_topic is None:
                raise ValueError("Agent input topic not found in workflow topics.")

            event = input_topic.publish_data(
                execution_context=execution_context,
                publisher_name=self.name,
                publisher_type=self.type,
                data=input,
                consumed_events=[],
            )
            container.event_store.record_event(event)
        else:
            # When there is unfinished workflow, we need to restore the workflow topics
            for topic_event in events:
                self.topics[topic_event.topic_name].restore_topic(topic_event)

            publish_events = [
                event
                for event in events
                if isinstance(event, PublishToTopicEvent)
                or isinstance(event, OutputTopicEvent)
            ]
            # restore the topics

            for publish_event in publish_events:
                topic_name = publish_event.topic_name
                if topic_name not in self.topic_nodes:
                    continue

                topic = self.topics[topic_name]

                # Get all nodes subscribed to this topic
                subscribed_nodes = self.topic_nodes[topic_name]

                for node_name in subscribed_nodes:
                    node = self.nodes[node_name]
                    # add unprocessed node to the execution queue
                    if topic.can_consume(node_name) and node.can_execute():
                        if isinstance(
                            topic, HumanRequestTopic
                        ) and topic.can_append_user_input(node_name, publish_event):
                            # if the topic is human request topic, we need to produce a new topic event
                            event = topic.append_user_input(
                                user_input_event=publish_event,
                                data=input,
                            )
                            container.event_store.record_event(event)
                        self.execution_queue.append(node)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
            "nodes": {name: node.to_dict() for name, node in self.nodes.items()},
            "topics": {name: topic.to_dict() for name, topic in self.topics.items()},
            "topic_nodes": self.topic_nodes,
        }
