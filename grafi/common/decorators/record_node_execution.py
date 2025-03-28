"""Decorator for recording node execution events and tracing."""

import functools
import json
from typing import List

from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.common.containers.container import event_store
from grafi.common.events.node_events.node_event import (
    NODE_ID,
    NODE_NAME,
    NODE_TYPE,
    PUBLISH_TO_TOPICS,
    SUBSCRIBED_TOPICS,
)
from grafi.common.events.node_events.node_failed_event import NodeFailedEvent
from grafi.common.events.node_events.node_invoke_event import NodeInvokeEvent
from grafi.common.events.node_events.node_respond_event import NodeRespondEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.instrumentations.tracing import tracer
from grafi.common.models.execution_context import ExecutionContext
from grafi.nodes.node import Node


def record_node_execution(func):
    """Decorator to record node execution events and tracing."""

    @functools.wraps(func)
    def wrapper(self: Node, *args, **kwargs):
        node_id: str = self.node_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        execution_context: ExecutionContext = (
            args[0] if args else kwargs.get("execution_context", None)
        )
        input_data: List[ConsumeFromTopicEvent] = (
            args[1] if len(args) > 1 else kwargs.get("node_input", None)
        )
        publish_to_topics = [topic.name for topic in self.publish_to]
        node_name: str = self.name
        node_type: str = self.type

        input_data_dict = [event.to_dict() for event in input_data]

        subscribed_topics = [topic.name for topic in self._subscribed_topics.values()]

        node_event_base = {
            NODE_ID: node_id,
            SUBSCRIBED_TOPICS: subscribed_topics,
            PUBLISH_TO_TOPICS: publish_to_topics,
            "execution_context": execution_context,
            NODE_TYPE: node_type,
            NODE_NAME: node_name,
            "input_data": input_data,
        }

        if event_store:
            # Record the 'invoke' event
            invoke_event = NodeInvokeEvent(
                **node_event_base,
            )
            event_store.record_event(invoke_event)

        # Execute the original function
        try:
            with tracer.start_as_current_span(f"{node_name}.execute") as span:
                span.set_attribute(NODE_ID, node_id)
                span.set_attribute(NODE_NAME, node_name)
                span.set_attribute(NODE_TYPE, node_type)
                span.set_attributes(execution_context.model_dump())
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    oi_span_type.value,
                )
                span.set_attribute("input", input_data_dict)

                # Execute the node function
                result = func(self, *args, **kwargs)

                output_data_dict = json.dumps(result, default=to_jsonable_python)

                span.set_attribute("output", output_data_dict)

        except Exception as e:
            # Exception occurred during execution
            if event_store:
                failed_event = NodeFailedEvent(
                    **node_event_base,
                    error=str(e),
                )
                event_store.record_event(failed_event)
            raise
        else:
            # Successful execution
            if event_store:
                respond_event = NodeRespondEvent(
                    **node_event_base,
                    output_data=result,
                )
                event_store.record_event(respond_event)

        return result

    return wrapper
