import asyncio
from collections import deque
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List
from typing import Set

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import PrivateAttr

from grafi.common.containers.container import container
from grafi.common.decorators.record_decorators import record_workflow_invoke
from grafi.common.events.event import Event
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.exceptions import WorkflowError
from grafi.common.models.invoke_context import InvokeContext
from grafi.nodes.node import Node
from grafi.nodes.node_base import NodeBase
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.llm import LLM
from grafi.topics.expressions.topic_expression import extract_topics
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_factory import TopicFactory
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker
from grafi.workflows.impl.async_output_queue import AsyncOutputQueue
from grafi.workflows.impl.utils import get_async_output_events
from grafi.workflows.impl.utils import get_node_input
from grafi.workflows.impl.utils import publish_events
from grafi.workflows.workflow import Workflow
from grafi.workflows.workflow import WorkflowBuilder


class EventDrivenWorkflow(Workflow):
    """
    An event-driven workflow that invokes a directed graph of Nodes in response to topic publish events.

    This workflow can handle streaming events via `StreamTopicEvent` and relay them to a custom
    `stream_event_handler`.
    """

    name: str = "EventDrivenWorkflow"
    type: str = "EventDrivenWorkflow"

    # OpenInference semantic attribute
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.AGENT

    # Topics known to this workflow (e.g., "agent_input", "agent_stream_output")
    _topics: Dict[str, TopicBase] = PrivateAttr(default={})

    # Mapping of topic_name -> list of node_names that subscribe to that topic
    _topic_nodes: Dict[str, List[str]] = PrivateAttr(default={})

    # Event graph for this workflow
    # Queue of nodes that are ready to invoke (in response to published events)
    _invoke_queue: deque[NodeBase] = PrivateAttr(default=deque())

    _tracker: AsyncNodeTracker = PrivateAttr(default_factory=AsyncNodeTracker)

    # Optional callback that handles output events
    # Including agent output event, stream event and hil event

    def model_post_init(self, _context: Any) -> None:
        self._add_topics()
        self._handle_function_calling_nodes()

    def stop(self) -> None:
        """
        Stop the workflow execution.
        Overrides base class to also trigger force stop on the tracker.
        """
        super().stop()
        self._tracker.force_stop_sync()

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

        published_topics_to_nodes = {}

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

    # Workflow invoke methods

    async def _get_output_events(self) -> List[ConsumeFromTopicEvent]:
        consumed_events: List[ConsumeFromTopicEvent] = []

        output_topics = [
            topic
            for topic in self._topics.values()
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
            await self._topics[topic].commit(consumer_name, offset)

        # Notify tracker that messages have been committed
        # (skip if already tracked elsewhere, e.g., by output listener)
        if track_commit:
            logger.debug(
                f"Committing {len(topic_events)} events for {consumer_name}, track_commit={track_commit}"
            )
            await self._tracker.on_messages_committed(
                len(topic_events), source=f"commit:{consumer_name}"
            )

    async def _add_to_invoke_queue(self, event: TopicEvent) -> None:
        topic_name = event.name

        if topic_name not in self._topic_nodes:
            return

        topic = self._topics[topic_name]

        # Get all nodes subscribed to this topic
        subscribed_nodes = self._topic_nodes[topic_name]

        for node_name in subscribed_nodes:
            node = self.nodes[node_name]
            # add unprocessed node to the invoke queue
            if await topic.can_consume(node_name) and await node.can_invoke():
                self._invoke_queue.append(node)

    async def invoke_sequential(
        self, input_data: PublishToTopicEvent
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """
        Invoke the workflow with the given context and input.
        Returns results when all nodes complete processing.
        """
        invoke_context = input_data.invoke_context

        consumed_events: List[ConsumeFromTopicEvent] = []
        try:
            # Process nodes until invoke queue is empty or workflow is stopped
            while self._invoke_queue:
                # Check if workflow should be stopped
                if self._stop_requested:
                    logger.info("Workflow execution stopped by assistant request")
                    break

                node = self._invoke_queue.popleft()

                # Given node, collect all the messages can be linked to it

                node_consumed_events: List[
                    ConsumeFromTopicEvent
                ] = await get_node_input(node)

                # Invoke node with collected inputs
                if node_consumed_events:
                    try:
                        published_events: List[PublishToTopicEvent] = []
                        async for result in node.invoke(
                            invoke_context, node_consumed_events
                        ):
                            published_events.extend(
                                await publish_events(node, result, self._tracker)
                            )

                        for event in published_events:
                            await self._add_to_invoke_queue(event)

                        events: List[TopicEvent] = []
                        events.extend(node_consumed_events)
                        events.extend(published_events)

                        await container.event_store.record_events(events)
                    except Exception as e:
                        raise NodeExecutionError(
                            node_name=node.name,
                            message=f"Node execution failed: {e}",
                            invoke_context=invoke_context,
                            cause=e,
                        ) from e

            consumed_events = await self._get_output_events()

            for event in consumed_events:
                yield event
        finally:
            if consumed_events:
                await container.event_store.record_events(consumed_events)

    async def invoke_parallel(
        self, input_data: PublishToTopicEvent
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        invoke_context = input_data.invoke_context
        logger.debug(
            f"invoke_parallel: tracker_id={id(self._tracker)}, metrics={await self._tracker.get_metrics()}"
        )

        # Start a background task to process all nodes (including streaming generators)
        node_processing_task = [
            asyncio.create_task(
                self._invoke_node(
                    invoke_context=invoke_context,
                    node=node,
                ),
                name=node.name,
            )
            for node in self.nodes.values()
        ]

        # Get output topics
        output_topics: list[TopicBase] = [
            topic
            for topic in self._topics.values()
            if topic.type == TopicType.AGENT_OUTPUT_TOPIC_TYPE
            or topic.type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
        ]

        # Create AsyncOutputQueue with output topics and tracker
        output_queue = AsyncOutputQueue(output_topics, self.name, self._tracker)
        await output_queue.start_listeners()

        consumed_output_events: List[ConsumeFromTopicEvent] = []

        # Wait for either new data or completion, with a timeout to check stop flag
        try:
            async for event in output_queue:
                # Check if any node task has failed before yielding events
                for i, task in enumerate(node_processing_task):
                    if task.done() and not task.cancelled():
                        try:
                            result = task.result()
                        except Exception as task_error:
                            node_name = (
                                list(self.nodes.keys())[i]
                                if i < len(self.nodes)
                                else f"node_{i}"
                            )
                            logger.error(
                                f"Node {node_name} failed during execution: {task_error}"
                            )
                            # Cancel remaining tasks and stop workflow
                            for t in node_processing_task:
                                if not t.done():
                                    t.cancel()
                            self.stop()

                            raise NodeExecutionError(
                                node_name=node_name,
                                message=f"Node {node_name} execution failed during workflow: {task_error}",
                                invoke_context=invoke_context,
                                cause=task_error,
                            ) from task_error

                # Now yield the data after committing
                consumed_event = ConsumeFromTopicEvent(
                    name=event.name,
                    type=event.type,
                    consumer_name=self.name,
                    consumer_type=self.type,
                    invoke_context=event.invoke_context,
                    offset=event.offset,
                    data=event.data,
                )
                yield consumed_event

                consumed_output_events.append(consumed_event)
        finally:
            await output_queue.stop_listeners()

            # Commit all consumed output events to topics
            # (tracking already done by output listener, so skip tracker update)
            await self._commit_events(
                consumer_name=self.name,
                topic_events=consumed_output_events,
                track_commit=False,
            )

            # 4. graceful shutdown all the nodes
            self.stop()

            # process events after stopping
            if consumed_output_events:
                await container.event_store.record_events(get_async_output_events(consumed_output_events))  # type: ignore[arg-type]

            # Wait for all node tasks to complete with proper error handling
            for t in node_processing_task:
                t.cancel()
            node_results = await asyncio.gather(
                *node_processing_task, return_exceptions=True
            )

            # Check for exceptions from node tasks and raise NodeExecutionError
            for i, result in enumerate(node_results):
                if isinstance(result, Exception) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    node_name = (
                        list(self.nodes.keys())[i]
                        if i < len(self.nodes)
                        else f"node_{i}"
                    )
                    logger.error(f"Node {node_name} failed with exception: {result}")
                    raise NodeExecutionError(
                        node_name=node_name,
                        message=f"Node {node_name} execution failed: {result}",
                        invoke_context=invoke_context,
                        cause=result,
                    ) from result

    async def _invoke_node(self, invoke_context: InvokeContext, node: NodeBase) -> None:
        """Enhanced node invocation with better async patterns and error handling."""
        buffer: Dict[str, List[TopicEvent]] = {}
        active_tasks: List[asyncio.Task] = []

        async def _wait_and_buffer(consumer_name: str, topic: TopicBase) -> None:
            """
            Block until *at least one* new record is available on `topic`,
            put **all** currently‑available new records into its buffer.
            """
            recs = await topic.consume(consumer_name)

            if topic.name not in buffer:
                buffer[topic.name] = []
            buffer[topic.name].extend(recs)

        async def _ignore_cancel(task: asyncio.Task) -> None:
            try:
                await task
            except asyncio.CancelledError:
                pass

        async def wait_node_invoke(node: NodeBase) -> None:
            while not node.can_invoke_with_topics(list(buffer.keys())):
                # Check for stop request before creating new tasks
                if self._stop_requested:
                    return

                # for every topic that *doesn't* have data yet, start one waiter
                tasks = [
                    asyncio.create_task(_wait_and_buffer(node.name, topic))
                    for topic in node.subscribed_topics
                ]
                active_tasks.extend(tasks)

                _, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )

                # finished waiters have already filled their buffer inside
                # _wait_and_buffer(); we just cancel the rest for this cycle
                for t in pending:
                    t.cancel()
                    # silence "task was destroyed but it is pending"
                    asyncio.create_task(_ignore_cancel(t))

                # Remove completed/cancelled tasks from active_tasks
                active_tasks[:] = [t for t in active_tasks if not t.done()]

        def _cancel_all_active_tasks() -> None:
            """Cancel all active tasks."""
            for task in active_tasks:
                if not task.done():
                    task.cancel()
            active_tasks.clear()

        try:
            while not self._stop_requested:
                # Check if node can be invoked

                await wait_node_invoke(node)

                # Check again after wait_node_invoke in case stop was requested
                if self._stop_requested:
                    break

                await self._tracker.enter(node.name)

                try:
                    consumed_events: List[ConsumeFromTopicEvent] = []

                    for events in buffer.values():
                        for event in events:
                            consumed_event = ConsumeFromTopicEvent(
                                invoke_context=event.invoke_context,
                                name=event.name,
                                type=event.type,
                                consumer_name=node.name,
                                consumer_type=node.type,
                                offset=event.offset,
                                data=event.data,
                            )
                            consumed_events.append(consumed_event)

                    # publish before commit
                    node_output_events: List[PublishToTopicEvent] = []
                    if consumed_events:
                        async for event in node.invoke(invoke_context, consumed_events):
                            node_output_events.extend(
                                await publish_events(
                                    node=node,
                                    publish_event=event,
                                    tracker=self._tracker,
                                )
                            )

                    await self._commit_events(
                        consumer_name=node.name, topic_events=consumed_events
                    )
                    await container.event_store.record_events(consumed_events)  # type: ignore[arg-type]
                    await container.event_store.record_events(get_async_output_events(node_output_events))  # type: ignore[arg-type]

                except Exception as node_error:
                    logger.error(f"Error processing node {node.name}: {node_error}")
                    raise NodeExecutionError(
                        node_name=node.name,
                        message=f"Async node execution failed: {node_error}",
                        invoke_context=invoke_context,
                        cause=node_error,
                    ) from node_error
                finally:
                    await self._tracker.leave(node.name)
                    buffer.clear()  # Clear buffer for next iteration

        except asyncio.CancelledError:
            logger.info(f"Node {node.name} was cancelled")
            _cancel_all_active_tasks()
            raise
        except NodeExecutionError:
            _cancel_all_active_tasks()
            raise  # Re-raise NodeExecutionError as-is
        except Exception as e:
            logger.error(f"Fatal error in node {node.name} execution: {e}")
            _cancel_all_active_tasks()
            raise NodeExecutionError(
                node_name=node.name,
                message=f"Fatal error in node execution: {e}",
                invoke_context=invoke_context,
                cause=e,
            ) from e
        finally:
            _cancel_all_active_tasks()
            buffer.clear()  # Clear buffer for next iteration

    @record_workflow_invoke
    async def invoke(
        self, input_data: PublishToTopicEvent, is_sequential: bool = False
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """
        Run the workflow with streaming output.
        """
        invoke_context = input_data.invoke_context
        try:
            # Reset stop flag at the beginning of new execution
            self.reset_stop_flag()

            await self.init_workflow(input_data, is_sequential)

            if is_sequential:
                # If sequential, we just call the sequential method
                async for event in self.invoke_sequential(input_data):
                    yield event
            else:
                async for event in self.invoke_parallel(input_data):
                    yield event

        except NodeExecutionError:
            raise  # Re-raise NodeExecutionError as-is
        except Exception as e:
            raise WorkflowError(
                message=f"Workflow {self.name} async execution failed: {e}",
                invoke_context=invoke_context,
                cause=e,
            ) from e

    async def init_workflow(
        self, input_data: PublishToTopicEvent, is_sequential: bool = False
    ) -> Any:
        # 1 – initial seeding
        logger.debug(
            f"init_workflow: is_sequential={is_sequential}, tracker_id={id(self._tracker)}"
        )
        if not is_sequential:
            self._tracker.reset()

        for topic in self._topics.values():
            await topic.reset()

        invoke_context = input_data.invoke_context

        events = [
            event
            for event in await container.event_store.get_agent_events(
                invoke_context.assistant_request_id
            )
            if isinstance(event, TopicEvent)
        ]

        if len(events) == 0:
            input_topics: List[TopicBase] = [
                topic
                for topic in self._topics.values()
                if topic.type == TopicType.AGENT_INPUT_TOPIC_TYPE
            ]

            events_to_record: List[Event] = []
            for input_topic in input_topics:
                event = await input_topic.publish_data(
                    input_data.model_copy(
                        update={
                            "publisher_name": self.name,
                            "publisher_type": self.type,
                        },
                        deep=True,
                    )
                )
                if event:
                    events_to_record.append(event)
                    if is_sequential:
                        await self._add_to_invoke_queue(event)

            logger.debug(
                f"init_workflow: events_to_record={len(events_to_record)}, input_topics={len(input_topics)}"
            )
            if events_to_record:
                # Track initial input messages for quiescence detection
                if not is_sequential:
                    logger.debug(
                        f"init_workflow: calling on_messages_published({len(events_to_record)})"
                    )
                    await self._tracker.on_messages_published(
                        len(events_to_record), source="init_workflow"
                    )
                    logger.debug(
                        f"init_workflow: tracker after publish: {await self._tracker.get_metrics()}"
                    )
                await container.event_store.record_events(events_to_record)
        else:
            # When there is unfinished workflow, we need to restore the workflow topics
            for topic_event in events:
                await self._topics[topic_event.name].restore_topic(topic_event)
                if is_sequential and isinstance(topic_event, PublishToTopicEvent):
                    await self._add_to_invoke_queue(topic_event)

            # Process in-workflow topics
            in_workflow_output_topic_names: Set[str] = set()
            consumed_event_ids = input_data.consumed_event_ids
            consumed_events = [
                event for event in events if event.event_id in consumed_event_ids
            ]
            in_workflow_output_topic_names = set(
                [
                    event.name
                    for event in consumed_events
                    if event.type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
                ]
            )

            for in_workflow_output_topic_name in in_workflow_output_topic_names:
                in_workflow_output_topic = self._topics.get(
                    in_workflow_output_topic_name
                )
                if in_workflow_output_topic and isinstance(
                    in_workflow_output_topic, InWorkflowOutputTopic
                ):
                    # if the topic is human request topic, we need to produce a new topic event
                    for (
                        paired_in_workflow_input_topic_name
                    ) in in_workflow_output_topic.paired_in_workflow_input_topic_names:
                        paired_in_workflow_input_topic = self._topics.get(
                            paired_in_workflow_input_topic_name
                        )
                        if paired_in_workflow_input_topic and isinstance(
                            paired_in_workflow_input_topic, InWorkflowInputTopic
                        ):
                            paired_event = (
                                await paired_in_workflow_input_topic.publish_data(
                                    input_data.model_copy(
                                        update={
                                            "publisher_name": self.name,
                                            "publisher_type": self.type,
                                        },
                                        deep=True,
                                    )
                                )
                            )
                            if paired_event:
                                # Track the published message for quiescence detection
                                if not is_sequential:
                                    await self._tracker.on_messages_published(
                                        1, source="restore_paired_input"
                                    )
                                if is_sequential:
                                    await self._add_to_invoke_queue(paired_event)
                                await container.event_store.record_event(paired_event)

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
