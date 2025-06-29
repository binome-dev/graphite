"""Decorator for recording node invoke events and tracing."""

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
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node_base import T_N


def record_node_a_invoke(
    func: Callable[[T_N, InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen],
) -> Callable[[T_N, InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]:
    """Decorator to record node invoke events and tracing."""

    @functools.wraps(func)
    async def wrapper(
        self: T_N,
        invoke_context: InvokeContext,
        input_data: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        node_id: str = self.node_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        publish_to_topics = [topic.name for topic in self.publish_to]
        node_name: str = self.name or ""
        node_type: str = self.type or ""

        input_data_dict = [event.to_dict() for event in input_data]

        subscribed_topics = [topic.name for topic in self._subscribed_topics.values()]

        # Record the 'invoke' event
        container.event_store.record_event(
            NodeInvokeEvent(
                node_id=node_id,
                subscribed_topics=subscribed_topics,
                publish_to_topics=publish_to_topics,
                invoke_context=invoke_context,
                node_type=node_type,
                node_name=node_name,
                input_data=input_data,
            )
        )

        result: Messages = []
        # Invoke the original function
        try:
            with container.tracer.start_as_current_span(f"{node_name}.invoke") as span:
                span.set_attribute(NODE_ID, node_id)
                span.set_attribute(NODE_NAME, node_name)
                span.set_attribute(NODE_TYPE, node_type)
                span.set_attributes(invoke_context.model_dump())
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    oi_span_type.value,
                )
                span.set_attribute(
                    "input", json.dumps(input_data_dict, default=to_jsonable_python)
                )

                # Invoke the node function
                result_content = ""
                is_streaming = False
                async for data in func(self, invoke_context, input_data):
                    for message in data:
                        if message.is_streaming:
                            if message.content is not None and isinstance(
                                message.content, str
                            ):
                                result_content += message.content
                            is_streaming = True
                        else:
                            result.append(message)
                    yield data

                if is_streaming:
                    result = [Message(role="assistant", content=result_content)]

                output_data_dict = json.dumps(result, default=to_jsonable_python)
                span.set_attribute("output", output_data_dict)
        except Exception as e:
            # Exception occurred during invoke
            span.set_attribute("error", str(e))
            container.event_store.record_event(
                NodeFailedEvent(
                    node_id=node_id,
                    subscribed_topics=subscribed_topics,
                    publish_to_topics=publish_to_topics,
                    invoke_context=invoke_context,
                    node_type=node_type,
                    node_name=node_name,
                    input_data=input_data,
                    error=str(e),
                )
            )
            raise
        else:
            # Successful invoke
            container.event_store.record_event(
                NodeRespondEvent(
                    node_id=node_id,
                    subscribed_topics=subscribed_topics,
                    publish_to_topics=publish_to_topics,
                    invoke_context=invoke_context,
                    node_type=node_type,
                    node_name=node_name,
                    input_data=input_data,
                    output_data=result,
                )
            )

    return wrapper
