from typing import Dict
from typing import List

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.message import Message
from grafi.nodes.node_base import NodeBase


def get_async_output_events(events: List[TopicEvent]) -> List[TopicEvent]:
    """
    Process a list of TopicEvents, grouping by name and aggregating streaming messages.

    Args:
        events: List of TopicEvents to process

    Returns:
        List of processed TopicEvents with streaming messages aggregated
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
            # Check if event.data contains streaming messages
            is_streaming_event = False
            # Handle both single message and list of messages
            messages = event.data
            if messages and len(messages) > 0 and messages[0].is_streaming:
                is_streaming_event = True

            if is_streaming_event:
                streaming_events.append(event)
            else:
                non_streaming_events.append(event)

        # Add non-streaming events as-is
        output_events.extend(non_streaming_events)

        # Aggregate streaming events if any exist
        if streaming_events:
            # Use the first streaming event as the base for creating the aggregated event
            base_event = streaming_events[0]

            # Aggregate content from all streaming messages
            aggregated_content_parts = []
            for event in streaming_events:
                messages = event.data if isinstance(event.data, list) else [event.data]
                for message in messages:
                    if message.content:
                        aggregated_content_parts.append(message.content)
            aggregated_content = "".join(aggregated_content_parts)  # type: ignore[arg-type]

            # Create a new message with aggregated content
            # Copy properties from the first message but update content and streaming flag
            first_message = (
                base_event.data
                if isinstance(base_event.data, list)
                else [base_event.data]
            )[0]
            aggregated_message = Message(
                role=first_message.role,
                content=aggregated_content,
                is_streaming=False,  # Aggregated message is no longer streaming
            )

            # Create new event based on the base event type
            aggregated_event = base_event
            aggregated_event.data = [aggregated_message]

            output_events.append(aggregated_event)

    return output_events


async def a_publish_events(
    node: NodeBase, publish_event: PublishToTopicEvent
) -> List[PublishToTopicEvent]:
    published_events: List[PublishToTopicEvent] = []
    for topic in node.publish_to:
        event = await topic.a_publish_data(publish_event)

        if event:
            published_events.append(event)

    return published_events


async def get_node_input(node: NodeBase) -> List[ConsumeFromTopicEvent]:
    consumed_events: List[ConsumeFromTopicEvent] = []

    node_subscribed_topics = node._subscribed_topics.values()

    # Process each topic the node is subscribed to
    for subscribed_topic in node_subscribed_topics:
        if await subscribed_topic.a_can_consume(node.name):
            # Get messages from topic and create consume events
            node_consumed_events = await subscribed_topic.a_consume(node.name)
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
