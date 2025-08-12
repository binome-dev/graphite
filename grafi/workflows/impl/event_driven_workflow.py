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
from grafi.common.decorators.record_workflow_a_invoke import record_workflow_a_invoke
from grafi.common.decorators.record_workflow_invoke import record_workflow_invoke
from grafi.common.events.event import Event
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.topics.in_workflow_input_topic import InWorkflowInputTopic
from grafi.common.topics.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_expression import extract_topics
from grafi.common.topics.topic_types import TopicType
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.llm import LLM
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker
from grafi.workflows.impl.async_output_queue import AsyncOutputQueue
from grafi.workflows.impl.utils import a_publish_events
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
    _invoke_queue: deque[Node] = PrivateAttr(default=deque())

    _tracker: AsyncNodeTracker = AsyncNodeTracker()

    # Optional callback that handles output events
    # Including agent output event, stream event and hil event

    def model_post_init(self, _context: Any) -> None:
        self._add_topics()
        self._handle_function_calling_nodes()

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
                    self._add_topic(t)
                    self._topic_nodes.setdefault(t.name, []).append(node_name)

            # For each publish topic, ensure it's registered
            for topic in node.publish_to:
                self._add_topic(topic)

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
            raise ValueError(
                "EventDrivenWorkflow must have at least one topic of type 'agent_input_topic'."
            )
        if not has_output_topic:
            raise ValueError(
                "EventDrivenWorkflow must have at least one topic of type 'agent_output_topic'."
            )

    def _add_topic(self, topic: TopicBase) -> None:
        """
        Registers the topic within the workflow if it's not already present
        and sets a default publish handler.
        """
        if topic.name not in self._topics:
            # Default event handler
            topic.publish_event_handler = self.on_event
            self._topics[topic.name] = topic

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
        published_topics_to_nodes: Dict[str, List[Node]] = {}

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

    def _get_output_events(self) -> List[ConsumeFromTopicEvent]:
        consumed_events: List[ConsumeFromTopicEvent] = []

        output_topics = [
            topic
            for topic in self._topics.values()
            if topic.type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
            or topic.type == TopicType.AGENT_OUTPUT_TOPIC_TYPE
        ]

        for output_topic in output_topics:
            if output_topic.can_consume(self.name):
                events = output_topic.consume(self.name)
                for event in events:
                    consumed_events.append(
                        ConsumeFromTopicEvent(
                            topic_name=event.topic_name,
                            topic_type=event.topic_type,
                            consumer_name=self.name,
                            consumer_type=self.type,
                            invoke_context=event.invoke_context,
                            offset=event.offset,
                            data=event.data,
                        )
                    )

        return consumed_events

    async def _a_commit_events(
        self, consumer_name: str, events: List[ConsumeFromTopicEvent]
    ) -> None:
        if not events:
            return
        # commit all consumed events
        topic_max_offset: Dict[str, int] = {}

        for event in events:
            topic_max_offset[event.topic_name] = max(
                topic_max_offset.get(event.topic_name, 0), event.offset
            )

        for topic, offset in topic_max_offset.items():
            await self._topics[topic].a_commit(consumer_name, offset)

    @record_workflow_invoke
    def invoke(self, input_event: PublishToTopicEvent) -> List[ConsumeFromTopicEvent]:
        """
        Invoke the workflow with the given context and input.
        Returns results when all nodes complete processing.
        """
        # Reset stop flag at the beginning of new execution
        self.reset_stop_flag()

        invoke_context = input_event.invoke_context

        consumed_events: List[ConsumeFromTopicEvent] = []
        try:
            self.initial_workflow(input_event)

            # Process nodes until invoke queue is empty or workflow is stopped
            while self._invoke_queue:
                # Check if workflow should be stopped
                if self._stop_requested:
                    logger.info("Workflow execution stopped by assistant request")
                    break

                node = self._invoke_queue.popleft()

                # Given node, collect all the messages can be linked to it

                node_consumed_events: List[ConsumeFromTopicEvent] = get_node_input(node)

                # Invoke node with collected inputs
                if node_consumed_events:
                    result = node.invoke(invoke_context, node_consumed_events)

                    published_events = publish_events(node, result)

                    events: List[TopicEvent] = []
                    events.extend(node_consumed_events)
                    events.extend(published_events)

                    container.event_store.record_events(events)  # type: ignore[arg-type]

            consumed_events = self._get_output_events()

            return consumed_events
        finally:
            if consumed_events:
                container.event_store.record_events(consumed_events)  # type: ignore[arg-type]

    @record_workflow_a_invoke
    async def a_invoke(
        self, input_event: PublishToTopicEvent
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """
        Run the workflow with streaming output.
        """
        # Reset stop flag at the beginning of new execution
        self.reset_stop_flag()

        await self.a_init_workflow(input_event)

        invoke_context = input_event.invoke_context

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
                # Now yield the data after committing
                consumed_event = ConsumeFromTopicEvent(
                    topic_name=event.topic_name,
                    topic_type=event.topic_type,
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

            # Commit all consumed output events
            await self._a_commit_events(
                consumer_name=self.name, events=consumed_output_events
            )

            # 4. graceful shutdown all the nodes
            self.stop()

            # process events after stopping
            if consumed_output_events:
                container.event_store.record_events(get_async_output_events(consumed_output_events))  # type: ignore[arg-type]

            # Wait for all node tasks to complete with proper error handling
            for t in node_processing_task:
                t.cancel()
            node_results = await asyncio.gather(
                *node_processing_task, return_exceptions=True
            )

            # Log any exceptions from node tasks
            for i, result in enumerate(node_results):
                if isinstance(result, Exception):
                    node_name = (
                        list(self.nodes.keys())[i]
                        if i < len(self.nodes)
                        else f"node_{i}"
                    )
                    logger.error(f"Node {node_name} ended with exception: {result}")

    async def _invoke_node(self, invoke_context: InvokeContext, node: Node) -> None:
        """Enhanced node invocation with better async patterns and error handling."""
        buffer: Dict[str, List[TopicEvent]] = {}

        async def _wait_and_buffer(consumer_name: str, topic: TopicBase) -> None:
            """
            Block until *at least one* new record is available on `topic`,
            put **all** currently‑available new records into its buffer.
            """
            recs = await topic.a_consume(consumer_name)

            if topic.name not in buffer:
                buffer[topic.name] = []
            buffer[topic.name].extend(recs)

        async def _ignore_cancel(task: asyncio.Task) -> None:
            try:
                await task
            except asyncio.CancelledError:
                pass

        async def wait_node_invoke(node: Node) -> None:
            while not node.can_invoke_with_topics(list(buffer.keys())):
                # for every topic that *doesn't* have data yet, start one waiter
                tasks = [
                    asyncio.create_task(_wait_and_buffer(node.name, topic))
                    for topic in node.subscribed_topics
                ]

                _, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )

                # finished waiters have already filled their buffer inside
                # _wait_and_buffer(); we just cancel the rest for this cycle
                for t in pending:
                    t.cancel()
                    # silence "task was destroyed but it is pending"
                    asyncio.create_task(_ignore_cancel(t))

        try:
            while not self._stop_requested:
                # Check if node can be invoked

                await wait_node_invoke(node)

                await self._tracker.enter(node.name)

                try:
                    consumed_events: List[ConsumeFromTopicEvent] = []

                    for events in buffer.values():
                        for event in events:
                            consumed_event = ConsumeFromTopicEvent(
                                invoke_context=event.invoke_context,
                                topic_name=event.topic_name,
                                topic_type=event.topic_type,
                                consumer_name=node.name,
                                consumer_type=node.type,
                                offset=event.offset,
                                data=event.data,
                            )
                            consumed_events.append(consumed_event)

                    # publish before commit
                    node_output_events: List[PublishToTopicEvent] = []
                    if consumed_events:
                        async for event in node.a_invoke(
                            invoke_context, consumed_events
                        ):
                            node_output_events.extend(
                                await a_publish_events(node=node, publish_event=event)
                            )

                    await self._a_commit_events(
                        consumer_name=node.name, events=consumed_events
                    )
                    container.event_store.record_events(consumed_events)  # type: ignore[arg-type]
                    container.event_store.record_events(get_async_output_events(node_output_events))  # type: ignore[arg-type]

                except Exception as node_error:
                    logger.error(f"Error processing node {node.name}: {node_error}")
                    # Don't break the loop, just log and continue
                finally:
                    await self._tracker.leave(node.name)
                    buffer.clear()  # Clear buffer for next iteration

        except asyncio.CancelledError:
            logger.info(f"Node {node.name} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Fatal error in node {node.name} execution: {e}")
            raise
        finally:
            buffer.clear()  # Clear buffer for next iteration

    def on_event(self, event: TopicEvent) -> None:
        """Handle topic publish events and trigger node invoke if conditions are met."""
        if not isinstance(event, PublishToTopicEvent):
            return

        topic_name = event.topic_name
        if topic_name not in self._topic_nodes:
            return

        # Get all nodes subscribed to this topic
        subscribed_nodes = self._topic_nodes[topic_name]

        for node_name in subscribed_nodes:
            node = self.nodes[node_name]
            # Check if node has new messages to consume
            if node.can_invoke():
                self._invoke_queue.append(node)

    def initial_workflow(self, input_event: PublishToTopicEvent) -> Any:
        """Restore the workflow state from stored events."""

        # Reset all the topics

        for topic in self._topics.values():
            topic.reset()

        invoke_context = input_event.invoke_context

        events = [
            event
            for event in container.event_store.get_agent_events(
                invoke_context.assistant_request_id
            )
            if isinstance(event, TopicEvent)
        ]

        if len(events) == 0:
            # Initialize by publish input data to input topic
            input_topics: List[TopicBase] = [
                topic
                for topic in self._topics.values()
                if topic.type == TopicType.AGENT_INPUT_TOPIC_TYPE
            ]
            if not input_topics:
                raise ValueError("Agent input topic not found in workflow topics.")

            events_to_record: List[Event] = []
            for input_topic in input_topics:
                event = input_topic.publish_data(
                    input_event.model_copy(
                        update={
                            "publisher_name": self.name,
                            "publisher_type": self.type,
                        },
                        deep=True,
                    )
                )
                if event:
                    events_to_record.append(event)

            if events_to_record:
                container.event_store.record_events(events_to_record)
        else:
            # When there is unfinished workflow, we need to restore the workflow topics
            for topic_event in events:
                self._topics[topic_event.topic_name].restore_topic(topic_event)

            publish_events = [
                event for event in events if isinstance(event, PublishToTopicEvent)
            ]

            # If consumed_event_ids are present, get all the corresponding consumed events

            in_workflow_output_topic_names: Set[str] = set()
            consumed_events: List[TopicEvent] = [
                event
                for event in events
                if event.event_id in input_event.consumed_event_ids
            ]
            in_workflow_output_topic_names = set(
                [
                    event.topic_name
                    for event in consumed_events
                    if event.topic_type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
                ]
            )

            # restore the topics
            for publish_event in publish_events:
                topic_name = publish_event.topic_name

                if topic_name not in self._topic_nodes:
                    continue

                topic = self._topics[topic_name]

                # Get all nodes subscribed to this topic
                subscribed_nodes = self._topic_nodes[topic_name]

                for node_name in subscribed_nodes:
                    node = self.nodes[node_name]
                    # add unprocessed node to the invoke queue
                    if topic.can_consume(node_name) and node.can_invoke():
                        self._invoke_queue.append(node)

            # Process in-workflow topics
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
                            paired_event = paired_in_workflow_input_topic.publish_data(
                                input_event.model_copy(
                                    update={
                                        "publisher_name": self.name,
                                        "publisher_type": self.type,
                                    },
                                    deep=True,
                                )
                            )
                            if paired_event:
                                container.event_store.record_event(paired_event)

                            for node_name in self._topic_nodes[
                                paired_in_workflow_input_topic.name
                            ]:
                                node = self.nodes[node_name]
                                # add unprocessed node to the invoke queue
                                if topic.can_consume(node_name) and node.can_invoke():
                                    self._invoke_queue.append(node)

    async def a_init_workflow(self, input_event: PublishToTopicEvent) -> Any:
        # 1 – initial seeding
        self._tracker.reset()
        for topic in self._topics.values():
            await topic.a_reset()

        invoke_context = input_event.invoke_context

        events = [
            event
            for event in container.event_store.get_agent_events(
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
                event = await input_topic.a_publish_data(
                    input_event.model_copy(
                        update={
                            "publisher_name": self.name,
                            "publisher_type": self.type,
                        },
                        deep=True,
                    )
                )
                if event:
                    events_to_record.append(event)

            if events_to_record:
                container.event_store.record_events(events_to_record)
        else:
            # When there is unfinished workflow, we need to restore the workflow topics
            for topic_event in events:
                await self._topics[topic_event.topic_name].a_restore_topic(topic_event)

            in_workflow_output_topic_names: Set[str] = set()
            consumed_event_ids = input_event.consumed_event_ids
            consumed_events = [
                event for event in events if event.event_id in consumed_event_ids
            ]
            in_workflow_output_topic_names = set(
                [
                    event.topic_name
                    for event in consumed_events
                    if event.topic_type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
                ]
            )

            # Process in-workflow topics
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
                                await paired_in_workflow_input_topic.a_publish_data(
                                    input_event.model_copy(
                                        update={
                                            "publisher_name": self.name,
                                            "publisher_type": self.type,
                                        },
                                        deep=True,
                                    )
                                )
                            )
                            if paired_event:
                                container.event_store.record_event(paired_event)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "topics": {name: topic.to_dict() for name, topic in self._topics.items()},
            "topic_nodes": self._topic_nodes,
        }
