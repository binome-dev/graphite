"""One invocation of an event-driven workflow.

A workflow is a pub/sub graph: a node runs when the unread events on its
subscribed topics satisfy its subscription, and what it publishes can make
other nodes ready. A ``WorkflowRun`` executes one invocation with a single
coordinator task that owns all of the run's state:

* A node is ready when its unread inputs satisfy its subscription and no step
  of it is running. The coordinator takes those inputs and starts a step task:
  one step at a time per node, and one at a time overall when sequential.
* A step invokes the node and returns what it published. The coordinator then
  commits it: one atomic ``record_events`` write of the step's consumptions and
  publications, and only then appends the publications to their topics, where
  they can make other nodes ready. A caller streaming the run also gets the
  deltas its steps emit, as they emit them (see :mod:`grafi.runtime.deltas`);
  they are neither published nor stored.
* The run ends when no step is running and no node is ready.
* A failure, a stop request or the caller leaving early stops the run: the
  running steps are cancelled at once and the coordinator waits for them. A
  step that stopped the run itself (by failing or calling stop()) is left to
  finish, unless a later stop comes from outside it.
* The caller then gets the run's failure: the first one recorded, or an
  interrupt or exit if one occurred, as a WorkflowError caused by it.
  _closing_error() says how it ranks against the caller's own error.

Run state changes only in synchronous code on the run's loop, so it needs no
locks (except one guarding stop() from another thread) and nothing polls. Tools
and stores run in the coordinator and step tasks; the caller's task only reads
finished outputs from a queue. When the caller closes the stream, the outputs it
received are acknowledged; the rest are delivered again when the request
resumes.
"""

import asyncio
import contextvars
import threading
from collections import deque
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING
from typing import Any
from typing import AsyncGenerator
from typing import Deque
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Set
from typing import Tuple
from typing import Type
from typing import Union

from loguru import logger

from grafi.common.async_lifecycle import INTERRUPT_OR_EXIT
from grafi.common.async_lifecycle import cancellation_of
from grafi.common.async_lifecycle import cancelling
from grafi.common.async_lifecycle import error_rank
from grafi.common.async_lifecycle import log_not_raised
from grafi.common.async_lifecycle import note_failure
from grafi.common.async_lifecycle import note_on_primary
from grafi.common.async_lifecycle import owned_iterator
from grafi.common.async_lifecycle import unexpected_cancellation
from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.event import TOPIC_EVENT_TYPES
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.exceptions import WorkflowError
from grafi.common.models.invoke_context import InvokeContext
from grafi.nodes.node_base import NodeBase
from grafi.runtime.deltas import Delta
from grafi.runtime.deltas import deltas_to
from grafi.runtime.execution_services import current_services
from grafi.runtime.wiring import Wiring
from grafi.runtime.wiring import wired
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_types import OUTPUT_TOPIC_TYPES
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.utils import consumption_of

if TYPE_CHECKING:
    from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

_END = object()  # Ends the caller's stream of outputs.
# The steps a task belongs to, one per nested workflow: each step adds its
# marker, and the tasks and threads it starts inherit them.
_current_steps: "contextvars.ContextVar[Tuple[object, ...]]" = contextvars.ContextVar(
    "grafi_current_steps", default=()
)


class _TopicLog:
    """A topic's publications in this run, and how far each consumer read.

    Only publications that a node reading the topic has not taken yet are
    kept; for a topic no node reads, only their number matters (the caller gets
    outputs through the run's queue).
    """

    def __init__(self, topic: TopicBase, readers: List[str]) -> None:
        self.topic = topic
        self.readers = readers
        self.events: List[PublishToTopicEvent] = []  # From position `start`.
        self.start = 0
        self.size = 0  # The position of the next publication.
        self.next_position: Dict[str, int] = {}  # By consumer.

    def append(self, publication: PublishToTopicEvent) -> None:
        if self.readers:
            self.events.append(publication)
        self.size += 1

    def has_unread(self, consumer: str) -> bool:
        return self.next_position.get(consumer, 0) < self.size

    def take(self, consumer: str) -> List[PublishToTopicEvent]:
        """Everything ``consumer`` (a node reading the topic) has not read yet."""
        taken = self.events[self.next_position.get(consumer, 0) - self.start :]
        self.next_position[consumer] = self.size
        self.trim()
        return taken

    def trim(self) -> None:
        """Drop the publications every reader has taken."""
        if self.readers:
            low = min(self.next_position.get(reader, 0) for reader in self.readers)
            if low > self.start:
                del self.events[: low - self.start]
                self.start = low


@dataclass
class _Step:
    node: NodeBase
    consumed: List[ConsumeFromTopicEvent]
    task: "asyncio.Task[List[PublishToTopicEvent]]"
    marker: object  # Found in _current_steps by code the step runs.


class _Failing:
    """Records an error leaving the block as the run's failure, which stops
    the steps. An interrupt or exit goes on: it leaves the loop at once, from
    this task (see ``INTERRUPT_OR_EXIT``)."""

    def __init__(self, run: "WorkflowRun") -> None:
        self._run = run

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        error: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> bool:
        if error is None:
            return False
        self._run._fail(error)
        return not isinstance(error, INTERRUPT_OR_EXIT)


class WorkflowRun:
    """Executes one invocation of a workflow; see the module docstring."""

    def __init__(
        self,
        workflow: "EventDrivenWorkflow",
        event_store: Optional[EventStore] = None,
    ) -> None:
        self.name: str = workflow.name
        self.type: str = workflow.type
        # The workflow as it is now: a change to it reaches the next run.
        self.nodes: Dict[str, NodeBase] = dict(workflow.nodes)
        topics, readers, self._wiring = workflow._wire()
        self.event_store = (
            event_store if event_store is not None else current_services().event_store
        )
        self._topics: Dict[str, _TopicLog] = {
            name: _TopicLog(topic, readers.get(name, []))
            for name, topic in topics.items()
        }
        self._invoke_context: Optional[InvokeContext] = None
        self._sequential = False  # One step at a time.
        self._stream = False  # The caller gets the steps' deltas.
        # Ready nodes without a running step, in the order they became ready.
        self._ready: Dict[str, None] = {}
        self._steps: Dict[str, _Step] = {}  # Running steps, by node name.
        self._started = 0  # Steps started: their numbers, from 1.
        # Nodes whose step finished, and None for a stop request: what wakes
        # the coordinator.
        self._inbox: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        self._outputs: "asyncio.Queue[Any]" = asyncio.Queue()
        self._delivered: List[ConsumeFromTopicEvent] = []
        # A write failed, and may have landed: the run commits nothing more.
        self._store_failed = False
        self._failure: Optional[BaseException] = None
        self._recorded: List[BaseException] = []  # Every failure recorded.
        self._stop_requested = False
        # Running steps the run cancelled as it stopped: they end because of it.
        self._stopped_steps: Set["asyncio.Task[Any]"] = set()
        self._aborted = False  # The caller was cancelled while closing.
        self._closed = asyncio.Event()  # The caller closed the stream.
        # The run's loop, set as it starts; stop() may come from another thread.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Reentrant: a signal handler calling stop() may interrupt code holding it.
        self._loop_lock = threading.RLock()
        self._cancellation_recorded = False  # An outside cancellation.

    # ------------------------------------------------------------------ #
    # The caller's side
    # ------------------------------------------------------------------ #

    async def run(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        """Run the workflow, yielding its outputs as their steps commit, and,
        if ``stream``, the deltas its steps emit as they emit them.

        The run's tasks (the coordinator, its steps) first yield to the loop, so
        none runs its first step in its creator's frame under an eager task
        factory (Python 3.12+), where an interrupt or exit it raised would
        escape through the creator rather than leave the loop from the task.
        """
        with self._loop_lock:
            self._loop = asyncio.get_running_loop()
        self._invoke_context = input_data.invoke_context
        self._sequential = is_sequential
        self._stream = stream
        coordinator = asyncio.create_task(self._coordinate(input_data), name=self.name)
        coordinator.add_done_callback(self._coordinator_done)
        primary: Optional[BaseException] = None
        try:
            while True:
                event = await self._outputs.get()
                if event is _END or self._failure is not None:
                    break
                if isinstance(event, Delta):
                    yield event
                    continue
                consumed = consumption_of(event, self.name, self.type)
                # Counted as delivered once handed over: a caller that stops
                # here has received it, and resuming must find its record (for
                # example a human-input request answered by event ID).
                self._delivered.append(consumed)
                yield consumed
        except BaseException as error:
            primary = error
            raise
        finally:
            await self._close(coordinator, primary)

    async def _close(
        self, coordinator: "asyncio.Task[None]", primary: Optional[BaseException]
    ) -> None:
        """Close the caller's stream: stop the run if the caller leaves early,
        let it acknowledge what was handed over, wait for it, and raise what
        _closing_error() picks."""
        if primary is not None:
            # The caller is leaving: every step stops, including one still
            # closing after it failed. (Otherwise the run has ended or failed.)
            self._request_stop()
        self._closed.set()
        cancelled: Optional[asyncio.CancelledError] = None
        # The coordinator waits for the steps, unless an interrupt or exit in
        # its own code ended it first.
        while running := [
            task
            for task in (coordinator, *(step.task for step in self._steps.values()))
            if not task.done()
        ]:
            try:
                await asyncio.wait(running)
            except asyncio.CancelledError as error:
                # A timeout around the close: stop at once, but never abandon
                # the run, so its steps have ended when the close returns.
                cancelled = cancelled or error
                self._aborted = True
                coordinator.cancel()
                if coordinator.done():
                    self._cancel_steps(again=True)
        self._coordinator_done(coordinator)  # Its callback may not have run yet.
        for step in self._steps.values():  # Left by an exit in the coordinator.
            error = None if step.task.cancelled() else step.task.exception()
            if error is not None:
                self._log_stopping(step, error)
        raised = self._closing_error(primary, cancelled)
        if raised is not None:
            raise raised

    def _closing_error(
        self,
        primary: Optional[BaseException],
        cancelled: Optional[asyncio.CancelledError],
    ) -> Optional[BaseException]:
        """The error the close raises, or None when that is the caller's own.

        The most severe of the caller's own error (``primary``), a
        cancellation of the caller during the close, and the run's failure is
        raised, the others noted on it; the caller's comes first among equals,
        and a second cancellation of a caller already cancelled is dropped. A
        plain close (``GeneratorExit``) raises the run's failure, as closing a
        generator raises its cleanup failure, unless the caller is being
        cancelled: the failure is then logged. An interrupt or exit a task of
        the run raised already left the loop through that task (see
        ``INTERRUPT_OR_EXIT``), so it is raised as a ``WorkflowError`` caused
        by it.
        """
        failure = self._failure
        if isinstance(failure, INTERRUPT_OR_EXIT):
            failure = WorkflowError(
                message=f"Workflow {self.name} was interrupted: {failure!r}",
                invoke_context=self._invoke_context,
            )
            failure.__cause__ = self._failure
        if isinstance(primary, GeneratorExit):
            if cancelled is None and failure is not None:
                if note_on_primary(primary, failure, "Workflow failure"):
                    return None  # Closed while the caller is being cancelled.
            primary = None  # A plain close raises the run's failure.
        if isinstance(primary, asyncio.CancelledError):
            cancelled = None  # Cancelled again while closing: nothing to add.
        errors = [error for error in (primary, cancelled, failure) if error is not None]
        if not errors:
            return None
        raised = max(errors, key=error_rank)  # The first of the highest rank.
        for error in errors:
            if error is not raised:
                label = "Workflow failure" if error is failure else "Also raised"
                note_failure(raised, error, label)
        return None if raised is primary else raised

    def _coordinator_done(self, coordinator: "asyncio.Task[None]") -> None:
        """End the caller's stream however the coordinator ended, including
        cancelled before it ever ran. Called once it is done, by _close() and
        as its done callback; the second call changes nothing (the failure is
        recorded once, and the caller reads no further than the first end)."""
        if coordinator.cancelled():
            self._fail(cancellation_of(coordinator))
        elif (error := coordinator.exception()) is not None:
            self._fail(error)  # An interrupt or exit, recorded as it was raised.
        self._outputs.put_nowait(_END)

    def stop(self) -> None:
        """Ask the run to stop, from any thread (see EventDrivenWorkflow.stop()).
        The request runs on the run's loop in the asker's context, so a step
        asking for it is left to finish, until a stop from outside it."""
        with self._loop_lock:
            loop = self._loop
            if loop is None:
                self._stop_requested = True  # The run then starts nothing.
                return
        try:
            loop.call_soon_threadsafe(self._request_stop)
        except RuntimeError:
            if not loop.is_closed():
                raise

    def _request_stop(self) -> None:
        """Stop the run. A step that asks for it, by failing or by calling
        stop() from code carrying its context, is left to finish; any later
        request from outside that step cancels it too."""
        self._cancel_steps(spare=_current_steps.get())
        if not self._stop_requested:
            self._stop_requested = True
            self._inbox.put_nowait(None)

    def _cancel_steps(
        self, spare: Tuple[object, ...] = (), again: bool = False
    ) -> None:
        """Cancel the running steps at once, except those marked in ``spare``,
        so none of them can do anything more before seeing the cancellation. A
        step already cancelled is cancelled ``again`` only when asked: when the
        coordinator itself is cancelled (the caller's abort, or from outside)."""
        for step in self._steps.values():
            task = step.task
            if task.done() or step.marker in spare:
                continue
            if again or task not in self._stopped_steps:
                self._stopped_steps.add(task)
                task.cancel()

    # ------------------------------------------------------------------ #
    # The coordinator
    # ------------------------------------------------------------------ #

    async def _coordinate(self, input_data: PublishToTopicEvent) -> None:
        await asyncio.sleep(0)  # Never eagerly, in the caller's frame: see run().
        with _Failing(self):
            if not self._stop_requested:  # Stopped before it started: nothing.
                await self._start(input_data)
                await self._schedule()
        await self._wait_for_steps()
        self._outputs.put_nowait(_END)
        if self._aborted or cancelling():
            # Cancelled by the caller's abort or from outside (for example as
            # the loop shuts down): end at once, as nobody may close the stream.
            return
        with _Failing(self):  # Outputs not acknowledged come again on resume.
            await self._closed.wait()
            await self._acknowledge()

    async def _schedule(self) -> None:
        """Run ready nodes until no node is ready and no step is running."""
        self._start_ready()
        while self._steps and not self._stop_requested:
            finished = [await self._inbox.get()]
            while not self._inbox.empty():  # Commit every finished step at once.
                finished.append(self._inbox.get_nowait())
            await self._settle([name for name in finished if name is not None])
            self._start_ready()

    def _start_ready(self) -> None:
        """Start steps for ready nodes, first ready first (one at a time when
        sequential)."""
        while (
            self._ready
            and not self._stop_requested
            and not (self._sequential and self._steps)
        ):
            name = next(iter(self._ready))
            del self._ready[name]
            node = self.nodes[name]
            consumed = [
                consumption_of(event, node.name, node.type)
                for topic in node._subscribed_topics
                for event in self._topics[topic].take(node.name)
            ]
            marker = object()
            self._started += 1
            task = asyncio.create_task(
                self._run_step(node, consumed, marker, self._started), name=name
            )

            def finished(_: "asyncio.Task[Any]", name: str = name) -> None:
                self._inbox.put_nowait(name)

            task.add_done_callback(finished)
            self._steps[name] = _Step(node, consumed, task, marker)

    def _queue_if_ready(self, name: str) -> None:
        """Queue node ``name`` if its unread inputs now satisfy its subscription
        and no step of it is running."""
        if name in self._steps or name in self._ready:
            return
        node = self.nodes[name]
        unread = [
            topic
            for topic in node._subscribed_topics
            if self._topics[topic].has_unread(name)
        ]
        if node.can_invoke_with_topics(unread):
            self._ready[name] = None

    async def _settle(self, names: List[str]) -> None:
        """Judge the finished steps of nodes ``names``, then commit those that
        succeeded.

        A step the run cancelled ended because of the stop: it is not committed
        even if it returned (it may have cut its work short), its work runs
        again on resume, and an error it raised is only logged. Any other
        step's error fails the run, or is noted on its failure, as does a step
        cancelled by anything but the run. An interrupt or exit always fails
        the run.
        """
        steps: List[_Step] = []
        for name in names:
            step = self._steps.pop(name)
            self._queue_if_ready(name)  # Inputs may have arrived meanwhile.
            task = step.task
            stopped = task in self._stopped_steps
            self._stopped_steps.discard(task)
            if task.cancelled():
                if not stopped:
                    self._fail(
                        self._node_failure(
                            step.node,
                            unexpected_cancellation(
                                "Node execution was unexpectedly cancelled",
                                cancellation_of(task),
                            ),
                        )
                    )
                continue
            error = task.exception()
            if error is None:
                if not stopped:
                    steps.append(step)
            elif stopped and isinstance(error, Exception):
                self._log_stopping(step, error)
            else:
                self._fail(self._node_failure(step.node, error))
        if not self._sequential:
            # In parallel, nodes ready from committed inputs need not wait for
            # this write; a sequential run takes one step after the other.
            self._start_ready()
        if steps and not self._aborted and not self._store_failed:
            await self._commit(steps)

    async def _wait_for_steps(self) -> None:
        """Wait until every step has ended, and settle them: those that
        finished are committed.

        If the coordinator was cancelled (the caller's abort, or from outside),
        every step is cancelled again, including one that failed and is still
        closing, and still waited for.
        """
        if cancelling():
            self._cancel_steps(again=True)
        while not all(step.task.done() for step in self._steps.values()):
            try:
                await asyncio.wait([step.task for step in self._steps.values()])
            except asyncio.CancelledError as error:
                self._fail(error)  # Unless it is the caller's abort.
                self._cancel_steps(again=True)
        with _Failing(self):
            await self._settle(list(self._steps))

    def _fail(self, error: BaseException) -> None:
        """Keep the first failure to reach the run as its failure; later ones
        become notes on it.

        An interrupt or exit outranks an ordinary failure, which then becomes a
        note on it. Recording a failure again does nothing. The first stops the
        run; a step failing with it is left to close.
        """
        if isinstance(error, asyncio.CancelledError):
            if self._aborted or self._cancellation_recorded:
                return  # The caller's own, or already recorded.
            self._cancellation_recorded = True
            error = unexpected_cancellation(
                "Workflow run was unexpectedly cancelled", error
            )
        if isinstance(error, Exception) and not isinstance(error, WorkflowError):
            wrapped = WorkflowError(
                message=f"Workflow {self.name} execution failed",
                invoke_context=self._invoke_context,
                cause=error,
            )
            wrapped.__cause__ = error
            error = wrapped
        if self._is_recorded(error):
            return
        self._recorded.append(error)
        first = self._failure
        if first is None:
            self._failure = error
            self._request_stop()
        elif error_rank(error) > error_rank(first):
            self._failure = error  # An interrupt or exit outranks a failure.
            note_failure(error, first, "Workflow failure")
        else:
            note_failure(first, error, "Later failure")

    def _is_recorded(self, error: BaseException) -> bool:
        return any(error is recorded for recorded in self._recorded)

    def _log_stopping(self, step: _Step, error: BaseException) -> None:
        """Log an error the stop explains, unless the run recorded it."""
        if not self._is_recorded(error):
            log_not_raised(error, f"node {step.node.name!r} was stopping")

    def _node_failure(self, node: NodeBase, error: BaseException) -> BaseException:
        """``error`` as ``node``'s failure: a ``NodeExecutionError`` caused by
        it. A node failure, an interrupt or an exit is kept as it is."""
        if not isinstance(error, Exception) or isinstance(error, NodeExecutionError):
            return error
        failure = NodeExecutionError(
            node_name=node.name,
            message="Node execution failed",
            invoke_context=self._invoke_context,
            cause=error,
        )
        failure.__cause__ = error
        return failure

    # ------------------------------------------------------------------ #
    # Steps, commits and publication
    # ------------------------------------------------------------------ #

    async def _run_step(
        self,
        node: NodeBase,
        consumed: List[ConsumeFromTopicEvent],
        marker: object,
        number: int,
    ) -> List[PublishToTopicEvent]:
        """Invoke ``node`` on its inputs and return its publications; the
        deltas it emits carry the step's ``number``.

        A failure fails the run at once, before the node's stream is closed, so
        that close cannot hold back stopping the other steps. A node's own
        failure reaches the run after the node has recorded its failed event; a
        failure publishing its output is thrown into the node's stream once the
        run has failed, so the node records that one too.
        """
        await asyncio.sleep(0)  # Never eagerly, in the coordinator's frame.
        _current_steps.set(_current_steps.get() + (marker,))
        published: List[PublishToTopicEvent] = []
        assert self._invoke_context is not None  # Set as the run starts.
        invocation = node.invoke(self._invoke_context, consumed)
        # None unless the caller streams, so that a run a tool starts inside
        # this step (to call an agent) streams to its own caller only.
        receive = self._outputs.put_nowait if self._stream else None
        with (
            deltas_to(receive, node.name, number),
            wired(self._wiring.get(node.name, Wiring())),
        ):
            async with owned_iterator(invocation):
                while True:
                    try:
                        event = await anext(invocation)
                    except StopAsyncIteration:
                        break
                    except Exception as error:
                        raise self._step_failed(node, error)
                    # A route whose condition raises does not match; the router
                    # logs it.
                    topics = node.publisher_router.select(event)
                    try:
                        publications = [
                            self._topics[name].topic.prepare_publication(event)
                            for name in topics
                        ]
                    except Exception as error:
                        failure = self._step_failed(node, error)
                        try:
                            await invocation.athrow(error)  # Raised again, recorded.
                        except Exception as raised:
                            if raised is not error:
                                note_failure(
                                    failure, raised, "Raised as the node closed"
                                )
                        raise failure
                    published.extend(publications)
        return published

    def _step_failed(self, node: NodeBase, error: Exception) -> BaseException:
        """``error`` as the failure of the current step of ``node``, recorded
        unless the step was stopped (an error then is a consequence of the
        stop; see _settle())."""
        failure = self._node_failure(node, error)
        step = asyncio.current_task()
        if step not in self._stopped_steps:
            self._fail(failure)
        return failure

    async def _commit(self, steps: List[_Step]) -> None:
        """Store finished steps in one write, then publish what they staged.

        No node reads a publication before it is stored, so a failure can never
        lose an event that another node already acted on.
        """
        records: List[TopicEvent] = []
        staged: List[PublishToTopicEvent] = []
        next_offsets: Dict[str, int] = {}
        for step in steps:
            records.extend(step.consumed)
            for publication in step.task.result():
                name = publication.name
                offset = next_offsets.get(name, self._topics[name].size)
                publication.offset = offset
                next_offsets[name] = offset + 1
                staged.append(publication)
                records.append(publication)
        await self._store(records)
        for publication in staged:
            self._publish(publication)

    async def _store(self, records: Sequence[TopicEvent]) -> None:
        try:
            await self.event_store.record_events(records)
        except BaseException:
            # The write may still have landed, so the positions it used are
            # uncertain: the run commits nothing more, and a resume restores
            # whatever the store holds.
            self._store_failed = True
            raise

    def _publish(self, publication: PublishToTopicEvent) -> None:
        """Make a publication visible to its topic's consumers."""
        log = self._topics[publication.name]
        log.append(publication)
        for name in log.readers:
            self._queue_if_ready(name)
        if log.topic.type in OUTPUT_TOPIC_TYPES:
            self._outputs.put_nowait(publication)

    async def _acknowledge(self) -> None:
        """Record the outputs handed to the caller, all stored before, as
        consumed by the workflow; the rest are delivered again when the request
        resumes."""
        if self._delivered:
            await self.event_store.record_events(self._delivered)

    # ------------------------------------------------------------------ #
    # Starting: a fresh request, or resuming one from its stored events
    # ------------------------------------------------------------------ #

    async def _start(self, input_data: PublishToTopicEvent) -> None:
        history = [
            event
            for event in await self.event_store.get_agent_events(
                input_data.invoke_context.assistant_request_id,
                event_types=TOPIC_EVENT_TYPES,
            )
            if isinstance(event, TopicEvent)
        ]
        if self._stop_requested:  # Stopped while the history loaded: nothing.
            return
        if history:
            self._restore(history)
            input_topics = self._answered_topics(input_data, history)
        else:
            input_topics = [
                name
                for name, log in self._topics.items()
                if log.topic.type == TopicType.AGENT_INPUT_TOPIC_TYPE
            ]
        # Published by the workflow; prepare_publication() copies it per topic.
        source = input_data.model_copy(
            update={"publisher_name": self.name, "publisher_type": self.type}
        )
        inputs: List[PublishToTopicEvent] = []
        for name in input_topics:
            publication = self._topics[name].topic.prepare_publication(source)
            publication.offset = self._topics[name].size
            inputs.append(publication)
        # Nodes ready from the stored history run first, in definition order;
        # then those the input makes ready.
        for name in self.nodes:
            self._queue_if_ready(name)
        if inputs:
            await self._store(inputs)
        for publication in inputs:
            self._publish(publication)

    def _restore(self, history: List[TopicEvent]) -> None:
        """Rebuild the topics from stored history, which must be complete:
        each topic's positions contiguous, and every consumption of a stored
        publication. Unacknowledged outputs are delivered again."""
        publications = sorted(
            (event for event in history if isinstance(event, PublishToTopicEvent)),
            key=lambda event: (event.name, event.offset),
        )
        for publication in publications:
            log = self._log_of(publication)
            if publication.offset != log.size:
                raise self._history_error(
                    f"Topic {publication.name!r} history has missing or conflicting "
                    f"offsets: expected offset {log.size}, "
                    f"found {publication.offset}"
                )
            log.append(publication)
        for event in history:
            if not isinstance(event, ConsumeFromTopicEvent):
                continue
            log = self._log_of(event)
            if not 0 <= event.offset < log.size:
                raise self._history_error(
                    f"Topic {event.name!r} history has no publication at consumed "
                    f"offset {event.offset}"
                )
            consumer = event.consumer_name
            log.next_position[consumer] = max(
                log.next_position.get(consumer, 0), event.offset + 1
            )
        # Outputs not acknowledged are delivered again: in history order across
        # topics, and in position order within each, as an acknowledgement
        # covers every earlier position of its topic.
        pending = [
            event
            for event in history
            if isinstance(event, PublishToTopicEvent)
            and event.type in OUTPUT_TOPIC_TYPES
            and event.offset >= self._topics[event.name].next_position.get(self.name, 0)
        ]
        in_position_order: Dict[str, Deque[PublishToTopicEvent]] = {}
        for event in sorted(pending, key=lambda event: event.offset):
            in_position_order.setdefault(event.name, deque()).append(event)
        for event in pending:
            self._outputs.put_nowait(in_position_order[event.name].popleft())
        for log in self._topics.values():
            log.trim()

    def _log_of(self, event: TopicEvent) -> _TopicLog:
        log = self._topics.get(event.name)
        if log is None:
            raise self._history_error(
                f"History has events of unknown topic {event.name!r}"
            )
        return log

    def _history_error(self, message: str) -> WorkflowError:
        return WorkflowError(message=message, invoke_context=self._invoke_context)

    def _answered_topics(
        self, input_data: PublishToTopicEvent, history: List[TopicEvent]
    ) -> List[str]:
        """The in-workflow input topics an answer to stored requests goes to.

        An input answering requests (``consumed_event_ids``) published on
        in-workflow output topics, for example a human's approval, goes to the
        input topics paired with them. Resending the same answer publishes
        nothing: a stored publication of it, answering the same requests, is
        enough. (Data is not compared, as a round trip through the store need
        not keep it equal.) Cited events the history does not hold, such as
        an output never acknowledged as its stream did not close cleanly, are
        logged; such an output is delivered again.
        """
        answering = set(input_data.consumed_event_ids)
        answered = {
            event.name
            for event in history
            if event.event_id in answering
            and event.type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
        }
        unknown = answering - {event.event_id for event in history}
        if unknown:
            logger.warning(
                "Input {} cites events not in the request's history: {}{}",
                input_data.event_id,
                sorted(unknown),
                "" if answered else "; it answers nothing",
            )
        already_issued = {
            event.name
            for event in history
            if isinstance(event, PublishToTopicEvent)
            and event.emission_id == input_data.event_id
            and event.consumed_event_ids == input_data.consumed_event_ids
        }
        topics: List[str] = []
        for name in sorted(answered):
            request_topic = self._topics[name].topic
            if not isinstance(request_topic, InWorkflowOutputTopic):
                continue
            for paired in request_topic.paired_in_workflow_input_topic_names:
                log = self._topics.get(paired)
                if (
                    log is not None
                    and isinstance(log.topic, InWorkflowInputTopic)
                    and paired not in already_issued
                    and paired not in topics
                ):
                    topics.append(paired)
        return topics
