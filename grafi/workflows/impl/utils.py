from typing import Dict
from typing import List
from typing import Sequence

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.message import Message


def get_async_output_events(events: Sequence[TopicEvent]) -> List[TopicEvent]:
    """
    Build a derived display view, grouping streaming text by topic.

    Projections keep the first event's identity and offset. They must not be
    persisted as canonical publications or consumption records for recovery.
    Source events and messages remain unchanged.
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
            aggregated_content_parts: List[str] = []
            for event in streaming_events:
                messages = event.data if isinstance(event.data, list) else [event.data]
                for message in messages:
                    # Streaming text chunks carry str content; ignore non-str
                    # content (which ``str.join`` could not concatenate anyway).
                    if isinstance(message.content, str) and message.content:
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

            # Build a NEW event for the aggregated output. Mutating base_event in
            # place would rewrite an event that has already been yielded to the
            # caller and recorded in the event store, corrupting the audit log.
            # A shallow copy suffices: `update` replaces `data` with a fresh list
            # and the other (unmutated) fields can be shared, avoiding an O(payload)
            # deep clone of the original streaming messages on the hot path.
            aggregated_event = base_event.model_copy(
                update={"data": [aggregated_message]}
            )
            output_events.append(aggregated_event)

    return output_events


def consumption_of(
    event: TopicEvent, consumer_name: str, consumer_type: str
) -> ConsumeFromTopicEvent:
    """The record of a consumer taking ``event`` from its topic."""
    return ConsumeFromTopicEvent(
        name=event.name,
        type=event.type,
        consumer_name=consumer_name,
        consumer_type=consumer_type,
        invoke_context=event.invoke_context,
        offset=event.offset,
        data=event.data,
    )
