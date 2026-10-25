import warnings
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import FrozenSet
from typing import List
from typing import Literal
from typing import NamedTuple
from typing import Optional
from typing import Self
from typing import Set
from typing import Tuple
from typing import Union
from typing import overload

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import PrivateAttr

from grafi.common.async_lifecycle import owned_iterator
from grafi.common.decorators.record_base import is_recorded
from grafi.common.decorators.record_decorators import record_workflow_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.common.models.function_spec import FunctionSpecs
from grafi.runtime.deltas import Delta
from grafi.runtime.wiring import Wiring
from grafi.runtime.wiring import wired
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.llm import LLM
from grafi.topics.expressions.topic_expression import extract_topics
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_base import TopicBase
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


class _Wired(NamedTuple):
    """A workflow wired from its nodes, as a run of it starts with it."""

    topics: Dict[str, TopicBase]
    readers: Dict[str, List[str]]  # By topic: the nodes reading it.
    wiring: Dict[str, Wiring]  # By node: what it is wired with.


class EventDrivenWorkflow(Workflow):
    """
    An event-driven workflow that invokes a directed graph of Nodes in response to topic publish events.

    This class is the *definition*: it owns its nodes, which each run wires
    as it starts (see :meth:`_wire`). Each ``invoke()`` creates a
    :class:`~grafi.workflows.impl.workflow_run.WorkflowRun` that holds all mutable
    per-invocation state (the topics' events, running steps, stop flag), so
    concurrent invocations of one instance are isolated from each other; the
    definition only keeps a registry of its runs in flight, which stop() uses.
    """

    name: str = "EventDrivenWorkflow"
    type: str = "EventDrivenWorkflow"

    # OpenInference semantic attribute
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.AGENT

    # In-flight runs, keyed by id(run), so stop() can reach them.
    _active_runs: Dict[int, WorkflowRun] = PrivateAttr(default_factory=dict)
    # Counts stop() calls, so a run made while one came is stopped too.
    _stops: int = PrivateAttr(default=0)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        if is_recorded(cls.invoke):
            raise TypeError(
                f"{cls.__name__}.invoke() is decorated with a record decorator, "
                "but an EventDrivenWorkflow records each of its runs itself, "
                "also through an override calling super().invoke(): leave it "
                "undecorated (a workflow with a run loop of its own subclasses "
                "Workflow)."
            )

    def model_post_init(self, _context: Any) -> None:
        self._wire(warn=True)

    def __copy__(self) -> Self:
        copied = super().__copy__()
        copied._active_runs = {}  # A copy has no runs in flight.
        return copied

    def __deepcopy__(self, memo: Optional[Dict[int, Any]] = None) -> Self:
        memo = {} if memo is None else memo
        memo[id(self._active_runs)] = {}  # A copy has no runs in flight.
        return super().__deepcopy__(memo)

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
        self._stops += 1
        for run in list(self._active_runs.values()):
            run.stop()

    @classmethod
    def builder(cls) -> WorkflowBuilder[Self]:
        """
        Return a builder for EventDrivenWorkflow.
        This allows for a fluent interface to construct the workflow.
        """
        return WorkflowBuilder(cls)

    def _wire(self, warn: bool = False) -> "_Wired":
        """The workflow wired from its nodes as they are: its topics, each
        topic's readers, and what each node is wired with (see
        :meth:`_wire_function_calls`, which ``warn`` passes on to). The
        workflow is wired as it is built, to check its nodes, and each run
        wires it as it starts, so a change to a node, its tool or what they
        hold reaches the next run, while a run in flight keeps what it
        started with.

        Raises WorkflowError for a node keyed by another name, without a
        subscription, or whose subscriptions name other topics than when it
        was built, and as _checked_topics does.
        """
        for key, node in self.nodes.items():
            if key != node.name:
                raise WorkflowError(
                    message=(
                        f"Node {node.name!r} is registered under the key {key!r}; "
                        "a workflow keys each node by its name."
                    ),
                    severity="CRITICAL",
                )
            named = {
                topic.name
                for expr in node.subscribed_expressions
                for topic in extract_topics(expr)
            }
            if not named:
                raise WorkflowError(
                    message=f"Node {node.name!r} requires at least one subscription.",
                    severity="CRITICAL",
                )
            if named != node._subscribed_topics.keys():
                raise WorkflowError(
                    message=(
                        f"The subscriptions of node {node.name!r} name other "
                        "topics than when it was built (changed in place, or "
                        "copied with model_copy(update=...)), and a node reads "
                        "the topics it was built with: build a new node, with "
                        "its builder or constructor."
                    ),
                    severity="CRITICAL",
                )
        return _Wired(*self._checked_topics(), self._wire_function_calls(warn))

    def _checked_topics(self) -> Tuple[Dict[str, TopicBase], Dict[str, List[str]]]:
        """The workflow's topics, and each one's readers, by name.

        Raises WorkflowError for a topic that overrides a method runs do not
        call (see _SKIPPED_TOPIC_METHODS) or has a custom event_queue, and for
        a workflow without an agent input or an agent output topic.
        """

        topics = self.topics
        for topic in topics.values():
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

        # Verify there is an agent input and an agent output topic
        has_input_topic = any(
            topic.type == TopicType.AGENT_INPUT_TOPIC_TYPE for topic in topics.values()
        )
        has_output_topic = any(
            topic.type == TopicType.AGENT_OUTPUT_TOPIC_TYPE for topic in topics.values()
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

        readers: Dict[str, List[str]] = {}
        for node_name, node in self.nodes.items():
            for topic_name in node._subscribed_topics:
                readers.setdefault(topic_name, []).append(node_name)
        return topics, readers

    def _wire_function_calls(self, warn: bool = False) -> Dict[str, Wiring]:
        """Wire the function calls. Each LLM node is offered the functions of
        the function-call nodes reading its calls: those reading a topic it
        publishes to, or, for an in-workflow output topic, a topic paired with
        it, where the reply comes. On each topic carrying calls, the first
        function-call node reading it (preferring one with on_error="return") also
        answers the calls naming a function no LLM calling there was offered,
        so that every call reaching a function-call node gets a result.

        Returns what each node is wired with, by name. With ``warn``, as the
        workflow is built or asked what an LLM is offered, warns
        (UserWarning) of a spec given to an LLM for a function a function-call
        node reading its calls answers, whose own spec is offered.
        """
        answerers = [
            (node, node.tool)
            for node in self.nodes.values()
            if isinstance(node.tool, FunctionCallTool)
        ]
        node_wiring: Dict[str, Wiring] = {}
        offered: Dict[str, Set[str]] = {}  # By topic: what its callers offer.
        for node in self.nodes.values():
            if not isinstance(node.tool, LLM):
                continue
            topics = {topic.name for topic in node.publish_to}
            for topic in node.publish_to:
                if isinstance(topic, InWorkflowOutputTopic):
                    topics.update(topic.paired_in_workflow_input_topic_names)
            functions = tuple(
                spec
                for reader, tool in answerers
                if topics & reader._subscribed_topics.keys()
                for spec in tool.get_function_specs()
            )
            node_wiring[node.name] = Wiring(
                tool_id=node.tool.tool_id, functions=functions
            )
            shadowed = {s.name for s in node.tool.function_specs} & {
                s.name for s in functions
            }
            if warn and shadowed:
                warnings.warn(
                    f"The LLM of node {node.name!r} is given specs for "
                    f"{sorted(shadowed)}, which function-call nodes reading "
                    "its calls answer: it is offered their own specs. Give an "
                    "LLM specs only for functions the app answers.",
                    UserWarning,
                )
            with wired(node_wiring[node.name]):  # As a step of the node sees.
                names = {spec.name for spec in node.tool.get_function_specs()}
            for topic_name in topics:
                offered.setdefault(topic_name, set()).update(names)
        answers: Dict[Tuple[str, str], Dict[str, FrozenSet[str]]] = {}
        for topic_name, names in offered.items():
            readers = [
                (reader, tool)
                for reader, tool in answerers
                if topic_name in reader._subscribed_topics
                and isinstance(reader.command, FunctionCallCommand)
            ]
            if readers:
                first, tool = min(readers, key=lambda pair: pair[1].on_error == "raise")
                answers.setdefault((first.name, tool.tool_id), {})[topic_name] = (
                    frozenset(names)
                )
        for (name, tool_id), by_topic in answers.items():
            node_wiring[name] = Wiring(tool_id=tool_id, offered=by_topic)
        return node_wiring

    def offered_to(self, node_name: str) -> FunctionSpecs:
        """The functions the LLM of the node ``node_name`` is offered in its
        steps: those of the function-call nodes reading its calls, then those
        it is given, once each by name.

        Raises:
            KeyError: If the workflow has no node ``node_name``.
            ValueError: If the node does not run an LLM.
        """
        llm = self.nodes[node_name].tool
        if not isinstance(llm, LLM):
            raise ValueError(f"Node {node_name!r} does not run an LLM.")
        with wired(self._wire(warn=True).wiring.get(node_name, Wiring())):
            return llm.get_function_specs()

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
        stream: bool = False,
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

        The run wires the workflow from its nodes as they are now (see
        :meth:`_wire`), which raises WorkflowError for nodes it cannot run.
        """
        stops = self._stops
        run = WorkflowRun(self)
        self._active_runs[id(run)] = run
        if self._stops != stops:  # Stopped while the run was being made.
            run.stop()
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
