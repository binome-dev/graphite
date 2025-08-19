"""Decorator for recording node invoke events and tracing."""

import functools
import json
from typing import Callable
from typing import List

from openinference.semconv.trace import OpenInferenceSpanKindValues
from openinference.semconv.trace import SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.common.containers.container import container
from grafi.common.events.node_events.node_failed_event import NodeFailedEvent
from grafi.common.events.node_events.node_invoke_event import NodeInvokeEvent
from grafi.common.events.node_events.node_respond_event import NodeRespondEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.nodes.node_base import T_N


def record_node_invoke(
    func: Callable[
        [T_N, InvokeContext, List[ConsumeFromTopicEvent]], PublishToTopicEvent
    ],
) -> Callable[[T_N, InvokeContext, List[ConsumeFromTopicEvent]], PublishToTopicEvent]:
    """Decorator to record node invoke events and tracing."""

    @functools.wraps(func)
    def wrapper(
        self: T_N,
        invoke_context: InvokeContext,
        input_data: List[ConsumeFromTopicEvent],
    ) -> PublishToTopicEvent:
        id: str = self.node_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        publish_to_topics = [topic.name for topic in self.publish_to]
        name: str = self.name or ""
        type: str = self.type or ""

        input_data_dict = [event.to_dict() for event in input_data]

        subscribed_topics = [topic.name for topic in self._subscribed_topics.values()]

        # Record the 'invoke' event
        container.event_store.record_event(
            NodeInvokeEvent(
                id=id,
                subscribed_topics=subscribed_topics,
                publish_to_topics=publish_to_topics,
                invoke_context=invoke_context,
                type=type,
                name=name,
                input_data=input_data,
            )
        )

        # Invoke the original function
        try:
            with container.tracer.start_as_current_span(f"{name}.invoke") as span:
                span.set_attribute("id", id)
                span.set_attribute("name", name)
                span.set_attribute("type", type)
                span.set_attributes(invoke_context.model_dump())
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    oi_span_type.value,
                )
                span.set_attribute(
                    "input", json.dumps(input_data_dict, default=to_jsonable_python)
                )

                # Invoke the node function
                result = func(self, invoke_context, input_data)

                span.set_attribute(
                    "output", json.dumps(result.to_dict(), default=to_jsonable_python)
                )

        except Exception as e:
            # Exception occurred during invoke
            span.set_attribute("error", str(e))
            container.event_store.record_event(
                NodeFailedEvent(
                    id=id,
                    subscribed_topics=subscribed_topics,
                    publish_to_topics=publish_to_topics,
                    invoke_context=invoke_context,
                    type=type,
                    name=name,
                    input_data=input_data,
                    error=str(e),
                )
            )
            raise
        else:
            # Successful invoke
            container.event_store.record_event(
                NodeRespondEvent(
                    id=id,
                    subscribed_topics=subscribed_topics,
                    publish_to_topics=publish_to_topics,
                    invoke_context=invoke_context,
                    type=type,
                    name=name,
                    input_data=input_data,
                    output_data=result,
                )
            )

        return result

    return wrapper
