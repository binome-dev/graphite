"""One invocation's mutable runtime state.

A :class:`~grafi.workflows.impl.event_driven_workflow.EventDrivenWorkflow` is a
long-lived *definition*: topology, topic configuration, tools, and LLM clients.
A ``WorkflowRun`` is created per ``invoke()`` call and owns everything that
mutates during execution -- the per-run topic queues, the quiescence tracker,
the ready-queue of invokable nodes, and the stop flag.

Because each invocation gets its own run, two concurrent invocations of one
workflow instance share only the immutable definition (and the reentrant tools /
clients hanging off it) and never each other's runtime state. The run is
discarded when the invocation finishes.

The topic *config* (name, type, condition) is shared by reference via a shallow
copy; only the queue instance is fresh, rebuilt as ``type(queue)()`` so a topic's
queue kind is preserved without cloning the node/tool graph.

This module holds the run's state plus the small helpers the engines share
(topology/quiescence accounting, output collection, commit). The execution
itself lives in focused modules: :mod:`grafi.workflows.impl.run_recovery`
(seeding/recovery), :mod:`grafi.workflows.impl.sequential_engine`, and
:mod:`grafi.workflows.impl.parallel_engine`.
"""

from collections import deque
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.exceptions import WorkflowError
from grafi.nodes.node_base import NodeBase
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker
from grafi.workflows.impl.parallel_engine import invoke_parallel
from grafi.workflows.impl.run_recovery import init_run
from grafi.workflows.impl.sequential_engine import invoke_sequential


class WorkflowRun:
    """Mutable runtime state for a single workflow invocation."""

    def __init__(self, definition: Any, event_store: Any) -> None:
        # Read-only references into the shared definition.
        self.name: str = definition.name
        self.type: str = definition.type
        self.nodes: Dict[str, NodeBase] = definition.nodes
        self.topic_nodes: Dict[str, List[str]] = definition._topic_nodes
        self.event_store = event_store

        # Per-run topic instances: same config, fresh queue.
        self.topics: Dict[str, TopicBase] = {
            name: topic.model_copy(update={"event_queue": type(topic.event_queue)()})
            for name, topic in definition._topics.items()
        }

        # Per-run runtime state.
        self.tracker: AsyncNodeTracker = AsyncNodeTracker()
        self.invoke_queue: deque[NodeBase] = deque()
        self._stop_requested: bool = False

    # ------------------------------------------------------------------ #
    # Control
    # ------------------------------------------------------------------ #

    def stop(self) -> None:
        """Stop this run. Sets the stop flag and force-stops the tracker so the
        parallel output loop and node tasks wind down."""
        self._stop_requested = True
        self.tracker.force_stop_sync()

    # ------------------------------------------------------------------ #
    # Topology / quiescence accounting (operate on this run's topics)
    # ------------------------------------------------------------------ #

    def _topic_consumers(self, topic_name: str) -> List[str]:
        """Consumers that will commit each event published to ``topic_name``:
        the subscribing nodes, plus the workflow itself for output topics. The
        single source of truth for fan-out -- one published event yields one
        delivery (and one eventual commit) per consumer. Deduplicated."""
        consumers = list(dict.fromkeys(self.topic_nodes.get(topic_name, [])))
        topic = self.topics.get(topic_name)
        if topic is not None and topic.type in (
            TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE,
        ):
            consumers.append(self.name)
        return consumers

    async def _count_pending_consumable(self) -> int:
        """Deliveries still awaiting consumption across all topics: the number of
        commits a resumed run must perform to drain restored state."""
        total = 0
        for topic_name, topic in self.topics.items():
            for consumer_name in self._topic_consumers(topic_name):
                total += await topic.unconsumed_count(consumer_name)
        return total

    async def _progress_possible(self) -> bool:
        """Whether the parallel run can still make progress: a node is active, or
        some event is still awaiting consumption. When False while the tracker is
        non-quiescent, the outstanding deliveries are parked (e.g. an unsatisfied
        ``A AND B`` subscription), so the output queue ends iteration instead of
        hanging."""
        if not await self.tracker.is_idle():
            return True
        return await self._count_pending_consumable() > 0

    async def _node_can_invoke(self, node: NodeBase) -> bool:
        """``node.can_invoke`` evaluated against *this run's* topics (not the
        definition's, whose queues are unused during a run)."""
        names_with_data = [
            topic.name
            for topic in node.subscribed_topics
            if await self.topics[topic.name].can_consume(node.name)
        ]
        return node.can_invoke_with_topics(names_with_data)

    async def _add_to_invoke_queue(self, event: TopicEvent) -> None:
        topic_name = event.name
        if topic_name not in self.topic_nodes:
            return
        topic = self.topics[topic_name]
        for node_name in self.topic_nodes[topic_name]:
            node = self.nodes[node_name]
            if await topic.can_consume(node_name) and await self._node_can_invoke(node):
                self.invoke_queue.append(node)

    # ------------------------------------------------------------------ #
    # Output collection / commit (shared by both engines)
    # ------------------------------------------------------------------ #

    async def _get_output_events(self) -> List[ConsumeFromTopicEvent]:
        consumed_events: List[ConsumeFromTopicEvent] = []
        output_topics = [
            topic
            for topic in self.topics.values()
            if topic.type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
            or topic.type == TopicType.AGENT_OUTPUT_TOPIC_TYPE
        ]
        for output_topic in output_topics:
            if await output_topic.can_consume(self.name):
                events = await output_topic.consume(self.name)
                for event in events:
                    consumed_events.append(
                        ConsumeFromTopicEvent(
                            name=event.name,
                            type=event.type,
                            consumer_name=self.name,
                            consumer_type=self.type,
                            invoke_context=event.invoke_context,
                            offset=event.offset,
                            data=event.data,
                        )
                    )
        return consumed_events

    async def _commit_events(
        self,
        consumer_name: str,
        topic_events: List[ConsumeFromTopicEvent],
        track_commit: bool = True,
    ) -> None:
        if not topic_events:
            return
        topic_max_offset: Dict[str, int] = {}
        for topic_event in topic_events:
            topic_max_offset[topic_event.name] = max(
                topic_max_offset.get(topic_event.name, 0), topic_event.offset
            )
        for topic, offset in topic_max_offset.items():
            await self.topics[topic].commit(consumer_name, offset)
        if track_commit:
            await self.tracker.on_messages_committed(
                len(topic_events), source=f"commit:{consumer_name}"
            )

    # ------------------------------------------------------------------ #
    # Lifecycle (thin dispatch to the seeding/recovery + engine modules)
    # ------------------------------------------------------------------ #

    async def init(self, input_data: PublishToTopicEvent, is_sequential: bool) -> None:
        """Seed input topics for a fresh request, or restore state on recovery."""
        await init_run(self, input_data, is_sequential)

    async def run(
        self, input_data: PublishToTopicEvent, is_sequential: bool
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """Seed/recover state, then execute sequentially or in parallel."""
        invoke_context = input_data.invoke_context
        try:
            await self.init(input_data, is_sequential)
            engine = invoke_sequential if is_sequential else invoke_parallel
            async for event in engine(self, input_data):
                yield event
        except NodeExecutionError:
            raise
        except Exception as e:
            raise WorkflowError(
                message=f"Workflow {self.name} async execution failed: {e}",
                invoke_context=invoke_context,
                cause=e,
            ) from e
