"""Decorator for recording node execution events and tracing."""

import functools
import json
from typing import Callable
from typing import List

from openinference.semconv.trace import OpenInferenceSpanKindValues
from openinference.semconv.trace import SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.common.containers.container import container
from grafi.common.events.node_events.node_event import NODE_ID
from grafi.common.events.node_events.node_event import NODE_NAME
from grafi.common.events.node_events.node_event import NODE_TYPE
from grafi.common.events.node_events.node_failed_event import NodeFailedEvent
from grafi.common.events.node_events.node_invoke_event import NodeInvokeEvent
from grafi.common.events.node_events.node_respond_event import NodeRespondEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.instrumentations.tracing import tracer
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import N


def record_node_a_execution(
    func: Callable[[N, ExecutionContext, List[ConsumeFromTopicEvent]], MsgsAGen],
) -> Callable[[N, ExecutionContext, List[ConsumeFromTopicEvent]], MsgsAGen]:
    """Decorator to record node execution events and tracing."""

    @functools.wraps(func)
    async def wrapper(
        self: N,
        execution_context: ExecutionContext,
        input_data: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        node_id: str = self.node_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        publish_to_topics = [topic.name for topic in self.publish_to]
        node_name: str = self.name or ""
        node_type: str = self.type or ""

        input_data_dict = [event.to_dict() for event in input_data]

        subscribed_topics = [topic.name for topic in self._subscribed_topics.values()]

        if container.event_store:
            # Record the 'invoke' event
            container.event_store.record_event(
                NodeInvokeEvent(
                    node_id=node_id,
                    subscribed_topics=subscribed_topics,
                    publish_to_topics=publish_to_topics,
                    execution_context=execution_context,
                    node_type=node_type,
                    node_name=node_name,
                    input_data=input_data,
                )
            )

        result: Messages = []
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
                span.set_attribute(
                    "input", json.dumps(input_data_dict, default=to_jsonable_python)
                )

                # Execute the node function

                async for data in func(self, execution_context, input_data):
                    result.extend(data)
                    yield data

                output_data_dict = json.dumps(result, default=to_jsonable_python)
                span.set_attribute("output", output_data_dict)
        except Exception as e:
            # Exception occurred during execution
            if container.event_store:
                failed_event = NodeFailedEvent(
                    node_id=node_id,
                    subscribed_topics=subscribed_topics,
                    publish_to_topics=publish_to_topics,
                    execution_context=execution_context,
                    node_type=node_type,
                    node_name=node_name,
                    input_data=input_data,
                    error=str(e),
                )
                container.event_store.record_event(failed_event)
            raise
        else:
            # Successful execution
            if container.event_store:
                respond_event = NodeRespondEvent(
                    node_id=node_id,
                    subscribed_topics=subscribed_topics,
                    publish_to_topics=publish_to_topics,
                    execution_context=execution_context,
                    node_type=node_type,
                    node_name=node_name,
                    input_data=input_data,
                    output_data=result,
                )
                container.event_store.record_event(respond_event)

    return wrapper
