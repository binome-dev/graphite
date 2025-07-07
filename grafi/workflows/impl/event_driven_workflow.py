import asyncio
from collections import deque
from typing import Any
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
from grafi.common.events.topic_events.output_async_event import OutputAsyncEvent
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.human_request_topic import HumanRequestTopic
from grafi.common.topics.human_request_topic import human_request_topic
from grafi.common.topics.output_topic import AGENT_OUTPUT_TOPIC
from grafi.common.topics.output_topic import OutputTopic
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import AGENT_INPUT_TOPIC
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_expression import extract_topics
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.llm import LLM
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

                # If the topic is for streaming, attach the specialized handler
                if isinstance(topic, HumanRequestTopic):
                    topic.publish_to_human_event_handler = self.on_event

        # 2) Verify there is an agent input topic
        if AGENT_INPUT_TOPIC not in self._topics:
            raise ValueError("Agent input topic not found in workflow topics.")
        elif AGENT_OUTPUT_TOPIC not in self._topics:
            raise ValueError("Agent output topic not found in workflow topics.")

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
    def _publish_events(
        self,
        node: Node,
        invoke_context: InvokeContext,
        result: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> None:
        published_events = []
        for topic in node.publish_to:
            event = topic.publish_data(
                invoke_context=invoke_context,
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

    async def _publish_agen_events(
        self,
        node: Node,
        invoke_context: InvokeContext,
        messages_agen: MsgsAGen,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> None:
        published_events = []
        consumed_messages: Messages = []
        for topic in node.publish_to:
            if not isinstance(topic, OutputTopic):
                # Add the generator to the async topic
                if not consumed_messages:
                    async for messages in messages_agen:
                        consumed_messages.extend(
                            messages if isinstance(messages, list) else [messages]
                        )

                event = topic.publish_data(
                    invoke_context=invoke_context,
                    publisher_name=node.name,
                    publisher_type=node.type,
                    data=consumed_messages,
                    consumed_events=consumed_events,
                )
                if event:
                    published_events.append(event)

        for topic in node.publish_to:
            if isinstance(topic, OutputTopic):
                # If it's an OutputTopic, we need to handle async generator
                topic.add_generator(
                    generator=messages_agen,
                    data=consumed_messages,
                    invoke_context=invoke_context,
                    publisher_name=node.name,
                    publisher_type=node.type,
                    consumed_events=consumed_events,
                )
                break

        all_events: List[Event] = []
        all_events.extend(consumed_events)
        all_events.extend(published_events)

        container.event_store.record_events(all_events)

    def _get_consumed_events(self) -> List[ConsumeFromTopicEvent]:
        consumed_events: List[ConsumeFromTopicEvent] = []
        if human_request_topic.can_consume(self.name):
            events = human_request_topic.consume(self.name)
            for event in events:
                if isinstance(event, OutputTopicEvent):
                    consumed_event = ConsumeFromTopicEvent(
                        topic_name=event.topic_name,
                        consumer_name=self.name,
                        consumer_type=self.type,
                        invoke_context=event.invoke_context,
                        offset=event.offset,
                        data=event.data,
                    )
                    consumed_events.append(consumed_event)

        if agent_output_topic.can_consume(self.name):
            events = agent_output_topic.consume(self.name)
            for event in events:
                consumed_event = ConsumeFromTopicEvent(
                    topic_name=event.topic_name,
                    consumer_name=self.name,
                    consumer_type=self.type,
                    invoke_context=event.invoke_context,
                    offset=event.offset,
                    data=event.data,
                )
                consumed_events.append(consumed_event)

        return consumed_events

    @record_workflow_invoke
    def invoke(self, invoke_context: InvokeContext, input: Messages) -> Messages:
        """
        Invoke the workflow with the given context and input.
        Returns results when all nodes complete processing.
        """
        consumed_events: List[ConsumeFromTopicEvent] = []
        try:
            self.initial_workflow(invoke_context, input)

            # Process nodes until invoke queue is empty
            while self._invoke_queue:
                node = self._invoke_queue.popleft()

                # Given node, collect all the messages can be linked to it

                node_consumed_events: List[ConsumeFromTopicEvent] = self.get_node_input(
                    node
                )

                # Invoke node with collected inputs
                if node_consumed_events:
                    result = node.invoke(invoke_context, node_consumed_events)

                    self._publish_events(
                        node, invoke_context, result, node_consumed_events
                    )

            output: Messages = []

            consumed_events = self._get_consumed_events()

            for event in consumed_events:
                messages = event.data if isinstance(event.data, list) else [event.data]
                output.extend(messages)

            # Sort the list of messages by the timestamp attribute
            sorted_outputs = sorted(output, key=lambda msg: msg.timestamp)

            return sorted_outputs
        finally:
            if consumed_events:
                container.event_store.record_events(consumed_events)  # type: ignore[arg-type]

    @record_workflow_a_invoke
    async def a_invoke(
        self, invoke_context: InvokeContext, input: Messages
    ) -> MsgsAGen:
        """
        Run the workflow with streaming output.
        """
        # 1 – initial seeding
        self.initial_workflow(invoke_context, input)

        # Track running tasks and executing nodes
        running_tasks: Set[asyncio.Task] = set()
        executing_nodes: Set[str] = set()

        # Start a background task to process all nodes (including streaming generators)
        node_processing_task = asyncio.create_task(
            self._process_all_nodes(invoke_context, running_tasks, executing_nodes)
        )

        # Prepare to stream events as they arrive
        consumed_output_async_events: List[OutputAsyncEvent] = []
        event_queue = agent_output_topic.event_queue
        get_event_task = asyncio.create_task(event_queue.get())

        try:
            # Race between new events and node processing completion
            while True:
                done, _ = await asyncio.wait(
                    {node_processing_task, get_event_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # If an output‐event arrived, yield it immediately
                if get_event_task in done:
                    ev = get_event_task.result()
                    consumed_output_async_events.append(ev)
                    yield ev.data
                    # schedule next event retrieval
                    get_event_task = asyncio.create_task(event_queue.get())
                    continue

                consumed_events: List[OutputAsyncEvent] = []
                if human_request_topic.can_consume(self.name):
                    events = human_request_topic.consume(self.name)
                    for event in events:
                        if isinstance(event, OutputTopicEvent):
                            yield event.data
                            consumed_events.append(
                                OutputAsyncEvent(
                                    topic_name=event.topic_name,
                                    publisher_name=self.name,
                                    publisher_type=self.type,
                                    invoke_context=event.invoke_context,
                                    offset=event.offset,
                                    data=event.data,
                                )
                            )

                    consumed_output_async_events.extend(consumed_events)

                # Otherwise node processing must have finished
                if node_processing_task in done:
                    # If nothing ever arrived, that's an error
                    if not consumed_output_async_events and event_queue.empty():
                        get_event_task.cancel()
                        raise RuntimeError(
                            "Node processing completed without emitting any agent_output_topic events"
                        )
                    # Otherwise break to drain remaining events
                    break

            # Drain any leftover events
            async for ev in agent_output_topic.get_events():
                consumed_output_async_events.append(ev)
                yield ev.data

        finally:
            # Clean up the pending get_event_task
            get_event_task.cancel()

            # Ensure node processing fully completes
            if not node_processing_task.done():
                await node_processing_task

            # Record all consumed output events
            if consumed_output_async_events:
                self._record_consumed_events(consumed_output_async_events)

    async def _process_all_nodes(
        self,
        invoke_context: InvokeContext,
        running_tasks: Set[asyncio.Task],
        executing_nodes: Set[str],
    ) -> None:
        """Process all nodes without blocking event streaming."""
        while self._invoke_queue or running_tasks:
            # Start new tasks for all queued nodes
            while self._invoke_queue:
                node = self._invoke_queue.popleft()

                if node.name in executing_nodes:
                    continue

                executing_nodes.add(node.name)
                task = asyncio.create_task(
                    self._invoke_node(invoke_context, node, executing_nodes)
                )
                running_tasks.add(task)

            if not running_tasks:
                break

            # Wait for at least one task to complete
            done, pending = await asyncio.wait(
                running_tasks, return_when=asyncio.FIRST_COMPLETED
            )

            running_tasks = pending

            for task in done:
                try:
                    await task
                except Exception as e:
                    logger.error(f"Error in node invoke: {e}")
                    for pending_task in running_tasks:
                        pending_task.cancel()
                    raise

        # Wait for all generators to complete
        await agent_output_topic.wait_for_completion()

    def _record_consumed_events(self, events: List[OutputAsyncEvent]) -> None:
        """Record consumed events to event store."""
        if not events:
            return

        # TODO: Update for multimodel content
        result_content = ""

        for event in events:
            is_streaming = False
            for message in event.data:
                if message.is_streaming:
                    if message.content is not None and isinstance(message.content, str):
                        result_content += message.content
                    is_streaming = True
            if not is_streaming:
                consumed_event = ConsumeFromTopicEvent(
                    topic_name=event.topic_name,
                    consumer_name=self.name,
                    consumer_type=self.type,
                    invoke_context=event.invoke_context,
                    offset=event.offset,
                    data=event.data,
                )

                container.event_store.record_event(consumed_event)

        if is_streaming:
            consumed_event = ConsumeFromTopicEvent(
                topic_name=events[0].topic_name,
                consumer_name=self.name,
                consumer_type=self.type,
                invoke_context=events[0].invoke_context,
                offset=events[0].offset,
                data=[Message(role="assistant", content=result_content)],
            )
            container.event_store.record_event(consumed_event)

    async def _invoke_node(
        self, invoke_context: InvokeContext, node: Node, executing_nodes: Set[str]
    ) -> None:
        """
        Invoke a single node asynchronously with proper stream handling.
        """
        try:
            node_consumed_events: List[ConsumeFromTopicEvent] = self.get_node_input(
                node
            )
            if not node_consumed_events:
                return

            logger.debug(f"Executing node: {node.name}")

            # Handle streaming nodes specially
            result = node.a_invoke(invoke_context, node_consumed_events)

            await self._publish_agen_events(
                node, invoke_context, result, node_consumed_events
            )

        except Exception as e:
            logger.error(f"Error executing node {node.name}: {e}")
            raise
        finally:
            # Always remove from executing set when done
            executing_nodes.discard(node.name)

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
                        invoke_context=event.invoke_context,
                        topic_name=event.topic_name,
                        consumer_name=node.name,
                        consumer_type=node.type,
                        offset=event.offset,
                        data=event.data,
                    )
                    consumed_events.append(consumed_event)

        return consumed_events

    def on_event(self, event: TopicEvent) -> None:
        """Handle topic publish events and trigger node invoke if conditions are met."""
        if not isinstance(event, PublishToTopicEvent):
            return

        if isinstance(event, OutputTopicEvent):
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

    def initial_workflow(self, invoke_context: InvokeContext, input: Messages) -> Any:
        """Restore the workflow state from stored events."""

        # Reset all the topics

        for topic in self._topics.values():
            topic.reset()

        events = [
            event
            for event in container.event_store.get_agent_events(
                invoke_context.assistant_request_id
            )
            if isinstance(event, TopicEvent)
        ]

        if len(events) == 0:
            # Initialize by publish input data to input topic
            input_topic = self._topics.get(AGENT_INPUT_TOPIC)
            if input_topic is None:
                raise ValueError("Agent input topic not found in workflow topics.")

            event = input_topic.publish_data(
                invoke_context=invoke_context,
                publisher_name=self.name,
                publisher_type=self.type,
                data=input,
                consumed_events=[],
            )
            container.event_store.record_event(event)
        else:
            # When there is unfinished workflow, we need to restore the workflow topics
            for topic_event in events:
                self._topics[topic_event.topic_name].restore_topic(topic_event)

            publish_events = [
                event
                for event in events
                if isinstance(event, PublishToTopicEvent)
                or isinstance(event, OutputTopicEvent)
            ]
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
                        if isinstance(
                            topic, HumanRequestTopic
                        ) and topic.can_append_user_input(node_name, publish_event):
                            # if the topic is human request topic, we need to produce a new topic event
                            event = topic.append_user_input(
                                user_input_event=publish_event,
                                data=input,
                            )
                            container.event_store.record_event(event)
                        self._invoke_queue.append(node)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "topics": {name: topic.to_dict() for name, topic in self._topics.items()},
            "topic_nodes": self._topic_nodes,
        }
