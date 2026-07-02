from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import PrivateAttr

from grafi.common.decorators.record_decorators import record_workflow_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.nodes.impl.hooked_node import HookedNode
from grafi.nodes.node import Node
from grafi.nodes.node_base import NodeBase
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.llm import LLM
from grafi.topics.expressions.topic_expression import extract_topics
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_factory import TopicFactory
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.workflow_run import WorkflowRun
from grafi.workflows.workflow import Workflow
from grafi.workflows.workflow import WorkflowBuilder


class EventDrivenWorkflow(Workflow):
    """
    An event-driven workflow that invokes a directed graph of Nodes in response to topic publish events.

    This class is the immutable *definition*: it owns the topology (nodes, topic
    configuration, and the topic→node subscription map) and links function-tool
    specs onto LLM nodes. It owns no runtime state. Each ``invoke()`` creates a
    :class:`~grafi.workflows.impl.workflow_run.WorkflowRun` that holds all mutable
    per-invocation state (topic queues, tracker, ready-queue, stop flag), so
    concurrent invocations of one instance are isolated from each other.
    """

    name: str = "EventDrivenWorkflow"
    type: str = "EventDrivenWorkflow"

    # OpenInference semantic attribute
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.AGENT

    # Topics known to this workflow (e.g., "agent_input", "agent_stream_output").
    # This is the definition's topic *template*; each run gets its own copies with
    # fresh queues.
    _topics: Dict[str, TopicBase] = PrivateAttr(default_factory=dict)

    # Mapping of topic_name -> list of node_names that subscribe to that topic
    _topic_nodes: Dict[str, List[str]] = PrivateAttr(default_factory=dict)

    # In-flight runs, keyed by id(run), so stop() can reach them.
    _active_runs: Dict[int, WorkflowRun] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _context: Any) -> None:
        self._add_topics()
        self._validate_router_wiring()
        self._handle_function_calling_nodes()

    def _validate_router_wiring(self) -> None:
        """Build-time check of each node's HITL router wiring (pure read).

        Catches misconfigured nodes early rather than at run time:
        1. A node with a pause route also has at least one normal output route.
        2. Each ``from_stage`` is used by exactly one route, on an
           ``InWorkflowOutputTopic`` paired to the node's matching resume input.
        3. A consumer router's ``pre_hitl_input``/``post_hitl_input`` (when set)
           is subscribed by the node and is an ``InWorkflowInputTopic``.
        """
        from grafi.nodes.routing import ConsumerRouter
        from grafi.nodes.routing import Stage
        from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
        from grafi.topics.topic_impl.in_workflow_output_topic import (
            InWorkflowOutputTopic,
        )

        for node_name, node in self.nodes.items():
            routes = node.publisher_router.routes
            pause_routes = [r for r in routes if r.from_stage is not None]
            normal_routes = [r for r in routes if r.from_stage is None]
            # Plain nodes have no consumer router; validate them against the
            # no-op default so pause-route misconfigurations still surface.
            consumer = getattr(node, "consumer_router", None) or ConsumerRouter()
            stage_input = {
                Stage.PRE_HOOK: consumer.pre_hitl_input,
                Stage.POST_HOOK: consumer.post_hitl_input,
            }

            if pause_routes and not normal_routes:
                raise WorkflowError(
                    message=(
                        f"Node '{node_name}' has a pause route but no normal "
                        "output route; PROCEED/DENY emissions would have nowhere "
                        "to go."
                    ),
                    severity="CRITICAL",
                )

            seen_stages: set = set()
            for route in pause_routes:
                stage = route.from_stage
                assert stage is not None  # pause_routes are filtered to a stage
                if stage in seen_stages:
                    raise WorkflowError(
                        message=(
                            f"Node '{node_name}' has more than one pause route "
                            f"for stage {stage.value}."
                        ),
                        severity="CRITICAL",
                    )
                seen_stages.add(stage)
                if not isinstance(route.topic, InWorkflowOutputTopic):
                    raise WorkflowError(
                        message=(
                            f"Node '{node_name}' pause route for "
                            f"{stage.value} must target an "
                            "InWorkflowOutputTopic."
                        ),
                        severity="CRITICAL",
                    )
                resume_input = stage_input.get(stage)
                if (
                    resume_input is not None
                    and resume_input
                    not in route.topic.paired_in_workflow_input_topic_names
                ):
                    raise WorkflowError(
                        message=(
                            f"Node '{node_name}' pause topic "
                            f"'{route.topic.name}' is not paired to its resume "
                            f"input '{resume_input}'."
                        ),
                        severity="CRITICAL",
                    )

            for channel in (consumer.pre_hitl_input, consumer.post_hitl_input):
                if channel is None:
                    continue
                if channel not in node._subscribed_topics:
                    raise WorkflowError(
                        message=(
                            f"Node '{node_name}' consumer input '{channel}' is "
                            "not subscribed; a resume could not admit the node."
                        ),
                        severity="CRITICAL",
                    )
                topic = node._subscribed_topics.get(channel) or self._topics.get(
                    channel
                )
                if not isinstance(topic, InWorkflowInputTopic):
                    raise WorkflowError(
                        message=(
                            f"Node '{node_name}' consumer input '{channel}' must "
                            "be an InWorkflowInputTopic."
                        ),
                        severity="CRITICAL",
                    )

    def stop(self) -> None:
        """
        Stop the workflow execution.

        Sets the definition-level stop flag and forwards the stop to every
        in-flight run so their trackers and node tasks wind down.
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

    def _add_topics(self) -> None:
        """
        Construct and return the EventDrivenStreamWorkflow.
        Sets up topic subscriptions and node-to-topic mappings.
        """

        # 1) Gather all topics from node subscriptions/publishes
        for node_name, node in self.nodes.items():
            # For each subscription expression, parse out one or more topics
            for expr in node.subscribed_expressions:
                found_topics = extract_topics(expr)
                for t in found_topics:
                    self._topics[t.name] = t
                    self._topic_nodes.setdefault(t.name, []).append(node_name)

            # For each publish topic, ensure it's registered
            for topic in node.publish_to:
                self._topics[topic.name] = topic

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
        # we add the function specs to the LLM node. A hook on the LLM node may
        # augment those specs (e.g. HITLApprovalHook injects a required
        # ``tool_call_reason`` so the model justifies a call it must get approved).
        for function_node in function_calling_nodes:
            for topic_name in function_node._subscribed_topics:
                for publisher_node in published_topics_to_nodes.get(topic_name, []):
                    if isinstance(publisher_node.tool, LLM) and isinstance(
                        function_node.tool, FunctionCallTool
                    ):
                        specs = function_node.tool.get_function_specs()
                        for hook in (
                            getattr(publisher_node, "pre_tool_hook", None),
                            getattr(publisher_node, "post_tool_hook", None),
                        ):
                            augment = getattr(hook, "augment_spec", None)
                            if callable(augment):
                                specs = augment(specs)
                        publisher_node.tool.add_function_specs(specs)

    @record_workflow_invoke
    async def invoke(
        self, input_data: PublishToTopicEvent, is_sequential: bool = False
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """
        Run the workflow with streaming output.

        Each call executes on its own :class:`WorkflowRun`, so the definition
        instance carries no per-invocation state and concurrent invocations are
        isolated.
        """
        run = WorkflowRun(self)
        self._active_runs[id(run)] = run
        try:
            async for event in run.run(input_data, is_sequential):
                yield event
        finally:
            self._active_runs.pop(id(run), None)

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
            # Dispatch on the serialized class: hooked nodes carry extra fields
            # (hooks + consumer router) that plain nodes do not.
            if node_dict.get("class") == "HookedNode":
                node: Node = await HookedNode.from_dict(node_dict, topics)
            else:
                node = await Node.from_dict(node_dict, topics)
            workflow_builder = workflow_builder.node(node)

        return workflow_builder.build()
