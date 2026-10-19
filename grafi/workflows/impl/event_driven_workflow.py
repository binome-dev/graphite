from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List
from typing import Set

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import PrivateAttr

from grafi.common.async_lifecycle import owned_iterator
from grafi.common.decorators.record_decorators import record_workflow_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.nodes.node import Node
from grafi.nodes.node_base import NodeBase
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.llm import LLM
from grafi.topics.expressions.topic_expression import extract_topics
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_factory import TopicFactory
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.workflow_run import WorkflowRun
from grafi.workflows.workflow import Workflow
from grafi.workflows.workflow import WorkflowBuilder

# Instance methods for using a topic on its own: a workflow run calls only
# prepare_publication() (and serializes the topic), so it would skip an
# override of any of these.
_SKIPPED_TOPIC_METHODS = tuple(
    name
    for name, value in vars(TopicBase).items()
    if callable(value)
    and not name.startswith("_")
    and name not in {"prepare_publication", "to_dict"}
)


class EventDrivenWorkflow(Workflow):
    """
    An event-driven workflow that invokes a directed graph of Nodes in response to topic publish events.

    This class is the immutable *definition*: it owns the topology (nodes, topic
    configuration, and the topic→node subscription map) and links function-tool
    specs onto LLM nodes. Each ``invoke()`` creates a
    :class:`~grafi.workflows.impl.workflow_run.WorkflowRun` that holds all mutable
    per-invocation state (the topics' events, running steps, stop flag), so
    concurrent invocations of one instance are isolated from each other; the
    definition only keeps a registry of its runs in flight, which stop() uses.
    """

    name: str = "EventDrivenWorkflow"
    type: str = "EventDrivenWorkflow"

    # OpenInference semantic attribute
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.AGENT

    # Topics known to this workflow (e.g., "agent_input", "agent_stream_output").
    # This is the definition's topic *template*; each run keeps its own events.
    _topics: Dict[str, TopicBase] = PrivateAttr(default_factory=dict)

    # Mapping of topic_name -> list of node_names that subscribe to that topic
    _topic_nodes: Dict[str, List[str]] = PrivateAttr(default_factory=dict)

    # Output topics that stream to the caller before their producing step commits.
    _streamed_topics: Set[str] = PrivateAttr(default_factory=set)

    # In-flight runs, keyed by id(run), so stop() can reach them.
    _active_runs: Dict[int, WorkflowRun] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _context: Any) -> None:
        for key, node in self.nodes.items():
            if key != node.name:
                raise WorkflowError(
                    message=(
                        f"Node {node.name!r} is registered under the key {key!r}; "
                        "a workflow keys each node by its name."
                    ),
                    severity="CRITICAL",
                )
            if not node.subscribed_expressions or not node.subscribed_topics:
                raise WorkflowError(
                    message=f"Node {node.name!r} requires at least one subscription.",
                    severity="CRITICAL",
                )
        self._add_topics()
        self._handle_function_calling_nodes()

    def stop(self) -> None:
        """Stop every run of this workflow in flight.

        A run is in flight once its ``invoke()`` is first iterated. Running
        steps are cancelled, except a step that called stop() itself, which is
        left to finish unless a later stop comes from outside it. Safe from
        any thread; the stop takes effect when the run's loop next runs its
        callbacks. To stop on a signal, use ``loop.add_signal_handler()``: a
        ``signal.signal()`` handler runs in the context of the step code it
        interrupts, which is then left to finish.
        """
        super().stop()
        for run in list(self._active_runs.values()):
            run.stop()

    @classmethod
    def builder(cls) -> WorkflowBuilder:
        """
        Return a builder for EventDrivenWorkflow.
        This allows for a fluent interface to construct the workflow.
        """
        return WorkflowBuilder(cls)

    def _find_streamed_topics(self, producers: Dict[str, Set[str]]) -> Set[str]:
        """Agent output topics whose chunks may reach the caller before commit.

        Only the workflow reads these topics, and a single node writes each of
        them, so a producer that fails mid-stream cannot leave a gap before a
        position another producer has already persisted. In-workflow output
        topics carry requests that a later call answers by event ID, so they
        reach the caller only once committed. Every other topic is staged until
        its producing step commits.
        """
        return {
            name
            for name, topic in self._topics.items()
            if topic.type == TopicType.AGENT_OUTPUT_TOPIC_TYPE
            and not self._topic_nodes.get(name)
            and len(producers.get(name, ())) == 1
        }

    def _add_topics(self) -> None:
        """Set up topics, node-to-topic mappings and the streamed output topics.

        Raises WorkflowError for a topic that overrides a method runs do not
        call (see _SKIPPED_TOPIC_METHODS) or has a custom event_queue, and for
        a workflow without an agent input or an agent output topic.
        """

        # 1) Gather all topics from node subscriptions/publishes
        producers: Dict[str, Set[str]] = {}
        for node_name, node in self.nodes.items():
            # For each subscription expression, parse out one or more topics
            for expr in node.subscribed_expressions:
                found_topics = extract_topics(expr)
                for t in found_topics:
                    self._topics[t.name] = t
                    readers = self._topic_nodes.setdefault(t.name, [])
                    if node_name not in readers:  # A topic named more than once.
                        readers.append(node_name)

            # For each publish topic, ensure it's registered
            for topic in node.publish_to:
                self._topics[topic.name] = topic
                producers.setdefault(topic.name, set()).add(node_name)

        self._streamed_topics = self._find_streamed_topics(producers)

        for topic in self._topics.values():
            for method in _SKIPPED_TOPIC_METHODS:
                if getattr(type(topic), method) is not getattr(TopicBase, method):
                    raise WorkflowError(
                        message=(
                            f"Topic {topic.name!r} overrides {method}(), which "
                            "workflows do not call; override "
                            "prepare_publication() instead."
                        ),
                        severity="CRITICAL",
                    )
            if type(topic.event_queue) is not InMemTopicEventQueue:
                raise WorkflowError(
                    message=(
                        f"Topic {topic.name!r} has a custom event_queue, which "
                        "workflows do not use: a run keeps its topics' events "
                        "itself and stores them in the event store."
                    ),
                    severity="CRITICAL",
                )

        # 2) Verify there is an agent input topic
        # Check if any topic has the required type
        has_input_topic = any(
            topic.type == TopicType.AGENT_INPUT_TOPIC_TYPE
            for topic in self._topics.values()
        )
        has_output_topic = any(
            topic.type == TopicType.AGENT_OUTPUT_TOPIC_TYPE
            for topic in self._topics.values()
        )

        if not has_input_topic:
            raise WorkflowError(
                message="EventDrivenWorkflow must have at least one topic of type 'agent_input_topic'.",
                severity="CRITICAL",
            )
        if not has_output_topic:
            raise WorkflowError(
                message="EventDrivenWorkflow must have at least one topic of type 'agent_output_topic'.",
                severity="CRITICAL",
            )

    def _handle_function_calling_nodes(self) -> None:
        """
        If there are LLMNode(s), we link them with the Node(s)
        that publish to the same topic, so that the LLM can carry the function specs.
        """
        # Find all function-calling nodes
        function_calling_nodes = [
            node
            for node in self.nodes.values()
            if isinstance(node.tool, FunctionCallTool)
        ]

        # Map each topic -> the nodes that publish to it
        published_topics_to_nodes: Dict[str, List[NodeBase]] = {}

        for node in self.nodes.values():
            if isinstance(node.tool, LLM):
                # If the node is an LLM node, we need to check its published topics
                for topic in node.publish_to:
                    if topic.name not in published_topics_to_nodes:
                        published_topics_to_nodes[topic.name] = []
                    published_topics_to_nodes[topic.name].append(node)
                    # If the topic is an in-workflow output topic,
                    # we need to link its paired input topics with the function calling nodes
                    if isinstance(topic, InWorkflowOutputTopic):
                        for (
                            in_workflow_input_topic_name
                        ) in topic.paired_in_workflow_input_topic_names:
                            if (
                                in_workflow_input_topic_name
                                not in published_topics_to_nodes
                            ):
                                published_topics_to_nodes[
                                    in_workflow_input_topic_name
                                ] = []
                            published_topics_to_nodes[
                                in_workflow_input_topic_name
                            ].append(node)

        # If a function node subscribes to a topic that an Node publishes to,
        # we add the function specs to the LLM node.
        for function_node in function_calling_nodes:
            for topic_name in function_node._subscribed_topics:
                for publisher_node in published_topics_to_nodes.get(topic_name, []):
                    if isinstance(publisher_node.tool, LLM) and isinstance(
                        function_node.tool, FunctionCallTool
                    ):
                        publisher_node.tool.add_function_specs(
                            function_node.tool.get_function_specs()
                        )

    async def invoke(
        self, input_data: PublishToTopicEvent, is_sequential: bool = False
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """
        Run the workflow with streaming output.

        Each call executes on its own :class:`WorkflowRun`, so the definition
        instance carries no per-invocation state and concurrent invocations are
        isolated. The run is registered before anything is awaited, so
        :meth:`stop` reaches it as soon as iteration has started.
        """
        run = WorkflowRun(self)
        self._active_runs[id(run)] = run
        try:
            async with owned_iterator(
                self._recorded_run(input_data, is_sequential, run)
            ) as stream:
                async for event in stream:
                    yield event
        finally:
            self._active_runs.pop(id(run), None)

    @record_workflow_invoke
    def _recorded_run(
        self, input_data: PublishToTopicEvent, is_sequential: bool, run: WorkflowRun
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """The run's outputs, with the workflow's invoke events recorded."""
        return run.run(input_data, is_sequential)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "topics": {name: topic.to_dict() for name, topic in self._topics.items()},
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "EventDrivenWorkflow":
        """
        Create a EventDrivenWorkflow instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the EventDrivenWorkflow.
        """
        workflow_builder = (
            cls.builder()
            .name(data["name"])
            .type(data["type"])
            .oi_span_type(
                OpenInferenceSpanKindValues(data.get("oi_span_type", "AGENT"))
            )
        )
        topics: Dict[str, TopicBase] = {}
        for topic_dict in data.get("topics", {}).values():
            topic = await TopicFactory.from_dict(topic_dict)
            topics[topic.name] = topic

        for node_dict in data.get("nodes", {}).values():
            node = await Node.from_dict(node_dict, topics)
            workflow_builder = workflow_builder.node(node)

        return workflow_builder.build()
