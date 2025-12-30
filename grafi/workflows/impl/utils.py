from typing import Dict
from typing import List

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.message import Message
from grafi.nodes.node_base import NodeBase
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker


def get_async_output_events(events: List[TopicEvent]) -> List[TopicEvent]:
    """
    Process a list of TopicEvents, grouping by name and aggregating streaming messages.

    NO CHANGES NEEDED - this is read-only aggregation.
    """
    # Group events by name
    events_by_topic: Dict[str, List[TopicEvent]] = {}
    for event in events:
        if event.name not in events_by_topic:
            events_by_topic[event.name] = []
        events_by_topic[event.name].append(event)

    output_events: List[TopicEvent] = []

    for _, topic_events in events_by_topic.items():
        # Separate streaming and non-streaming events
        streaming_events: List[TopicEvent] = []
        non_streaming_events: List[TopicEvent] = []

        for event in topic_events:
            is_streaming_event = False
            messages = event.data
            if messages and len(messages) > 0 and messages[0].is_streaming:
                is_streaming_event = True

            if is_streaming_event:
                streaming_events.append(event)
            else:
                non_streaming_events.append(event)

        output_events.extend(non_streaming_events)

        if streaming_events:
            base_event = streaming_events[0]
            aggregated_content_parts = []
            for event in streaming_events:
                messages = event.data if isinstance(event.data, list) else [event.data]
                for message in messages:
                    if message.content:
                        aggregated_content_parts.append(message.content)
            aggregated_content = "".join(aggregated_content_parts)

            first_message = (
                base_event.data
                if isinstance(base_event.data, list)
                else [base_event.data]
            )[0]
            aggregated_message = Message(
                role=first_message.role,
                content=aggregated_content,
                is_streaming=False,
            )

            aggregated_event = base_event
            aggregated_event.data = [aggregated_message]
            output_events.append(aggregated_event)

    return output_events


async def publish_events(
    node: NodeBase,
    publish_event: PublishToTopicEvent,
    tracker: AsyncNodeTracker,
) -> List[PublishToTopicEvent]:
    """
    Publish events to all topics the node publishes to.

    CHANGE: Added optional tracker parameter.
    When provided, notifies tracker of published messages.
    """
    published_events: List[PublishToTopicEvent] = []

    for topic in node.publish_to:
        event = await topic.publish_data(publish_event)
        if event:
            published_events.append(event)

    # NEW: Notify tracker of published messages
    if tracker and published_events:
        await tracker.on_messages_published(
            len(published_events), source=f"node:{node.name}"
        )

    return published_events


async def get_node_input(node: NodeBase) -> List[ConsumeFromTopicEvent]:
    """
    Get input events for a node from its subscribed topics.

    NO CHANGES NEEDED - consumption tracking happens at commit time.
    """
    consumed_events: List[ConsumeFromTopicEvent] = []

    node_subscribed_topics = node._subscribed_topics.values()

    for subscribed_topic in node_subscribed_topics:
        if await subscribed_topic.can_consume(node.name):
            node_consumed_events = await subscribed_topic.consume(node.name)
            for event in node_consumed_events:
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

    return consumed_events
