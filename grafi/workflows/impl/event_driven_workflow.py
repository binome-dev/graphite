from contextlib import AbstractContextManager
from contextlib import nullcontext
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List
from typing import Literal
from typing import Set
from typing import Union
from typing import cast
from typing import overload

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import PrivateAttr
from pydantic import computed_field

from grafi.common.async_lifecycle import owned_iterator
from grafi.common.decorators.record_decorators import record_workflow_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.common.manifest import ManifestError
from grafi.nodes.node_base import NodeBase
from grafi.runtime.deltas import Delta
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.llm import LLM
from grafi.topics.expressions.topic_expression import extract_topics
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_base import loading_topics
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.workflow_run import WorkflowRun
from grafi.workflows.workflow import Workflow
from grafi.workflows.workflow import WorkflowBuilder

# Instance methods for using a topic on its own: a workflow run calls only
# prepare_publication(), so it would skip an override of any of these.
_SKIPPED_TOPIC_METHODS = tuple(
    name
    for name, value in vars(TopicBase).items()
    if callable(value)
    and not name.startswith(("_", "model_"))
    and name != "prepare_publication"
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

    It is saved with its topics, which its nodes name.
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

    @computed_field(repr=False)  # type: ignore[prop-decorator]
    @property
    def topics(self) -> Dict[str, TopicBase]:
        """The workflow's topics, by name: those its nodes subscribe and
        publish to."""
        return dict(self._topics)

    @classmethod
    def _loading(
        cls, data: Dict[str, Any], context: Any
    ) -> AbstractContextManager[object]:
        if "topics" not in data:
            return nullcontext()
        topics = {
            name: TopicBase.model_validate(topic, context=context)
            for name, topic in data.pop("topics").items()
        }
        for name, topic in topics.items():
            if topic.name != name:
                raise ManifestError(f"The topic {topic.name!r} is keyed as {name!r}.")
        return loading_topics(topics)

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

    def _add_topics(self) -> None:
        """Set up topics and node-to-topic mappings.

        Raises WorkflowError for a topic that overrides a method runs do not
        call (see _SKIPPED_TOPIC_METHODS) or has a custom event_queue, and for
        a workflow without an agent input or an agent output topic.
        """

        # 1) Gather all topics from node subscriptions/publishes
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
        """Offer each LLM node the functions of the function-call nodes reading
        its calls: those reading a topic it publishes to, or, for an
        in-workflow output topic, a topic paired with it, where the reply
        comes. On each topic carrying calls, the first function-call node
        reading it (one answering errors, if any does) also answers the calls
        naming a function no LLM calling there was offered, so that every call
        reaching a function-call node gets a result.
        """
        offered: Dict[str, Set[str]] = {}  # By topic: what its callers offer.
        for node in self.nodes.values():
            llm = node.tool
            if not isinstance(llm, LLM):
                continue
            topics = {topic.name for topic in node.publish_to}
            for topic in node.publish_to:
                if isinstance(topic, InWorkflowOutputTopic):
                    topics.update(topic.paired_in_workflow_input_topic_names)
            for reader in self._function_call_nodes():
                if topics & reader._subscribed_topics.keys():
                    llm.add_function_specs(
                        cast(FunctionCallTool, reader.tool).get_function_specs()
                    )
            names = {spec.name for spec in llm.get_function_specs()}
            for topic_name in topics:
                offered.setdefault(topic_name, set()).update(names)
        for reader in self._function_call_nodes():
            if isinstance(reader._command, FunctionCallCommand):
                reader._command.offered = {}  # Set afresh: this runs again on a copy.
        for topic_name, names in offered.items():
            readers = [
                reader
                for reader in self._function_call_nodes()
                if topic_name in reader._subscribed_topics
                and isinstance(reader._command, FunctionCallCommand)
            ]
            readers.sort(
                key=lambda r: cast(FunctionCallTool, r.tool).on_error == "raise"
            )
            command = readers[0]._command if readers else None
            if isinstance(command, FunctionCallCommand):
                command.offered[topic_name] = frozenset(names)

    def _function_call_nodes(self) -> List[NodeBase]:
        return [
            node
            for node in self.nodes.values()
            if isinstance(node.tool, FunctionCallTool)
        ]

    @overload
    def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: Literal[False] = False,
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]: ...

    @overload
    def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]: ...

    async def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        """
        Run the workflow, yielding its outputs as their steps commit, and, if
        ``stream``, the deltas its tools emit as they emit them.

        Each call executes on its own :class:`WorkflowRun`, so the definition
        instance carries no per-invocation state and concurrent invocations are
        isolated. The run is registered before anything is awaited, so
        :meth:`stop` reaches it as soon as iteration has started.
        """
        run = WorkflowRun(self)
        self._active_runs[id(run)] = run
        try:
            async with owned_iterator(
                self._recorded_run(input_data, is_sequential, stream, run)
            ) as outputs:
                async for output in outputs:
                    yield output
        finally:
            self._active_runs.pop(id(run), None)

    @record_workflow_invoke
    def _recorded_run(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool,
        stream: bool,
        run: WorkflowRun,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        """The run's outputs, with the workflow's invoke events recorded."""
        return run.run(input_data, is_sequential, stream=stream)
