"""Provides decorators for recording workflow invoke events and adding tracing."""

import functools
import json
from typing import AsyncGenerator
from typing import Callable
from typing import List

from openinference.semconv.trace import OpenInferenceSpanKindValues
from openinference.semconv.trace import SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.common.containers.container import container
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.workflow_events.workflow_failed_event import (
    WorkflowFailedEvent,
)
from grafi.common.events.workflow_events.workflow_invoke_event import (
    WorkflowInvokeEvent,
)
from grafi.common.events.workflow_events.workflow_respond_event import (
    WorkflowRespondEvent,
)
from grafi.common.models.message import Message
from grafi.workflows.workflow import T_W


def record_workflow_a_invoke(
    func: Callable[
        [T_W, PublishToTopicEvent], AsyncGenerator[ConsumeFromTopicEvent, None]
    ],
) -> Callable[[T_W, PublishToTopicEvent], AsyncGenerator[ConsumeFromTopicEvent, None]]:
    """
    Decorator to record workflow invoke events and add tracing.

    Args:
        func: The workflow function to be decorated.

    Returns:
        Wrapped function that records events and adds tracing.
    """

    @functools.wraps(func)
    async def wrapper(
        self: T_W,
        input_data: PublishToTopicEvent,
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        id: str = self.workflow_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        name: str = self.name or ""
        type: str = self.type or ""

        # Record the 'invoke' event
        container.event_store.record_event(
            WorkflowInvokeEvent(
                id=id,
                invoke_context=input_data.invoke_context,
                type=type,
                name=name,
                input_data=input_data,
            )
        )

        # Invoke the original function
        result: List[ConsumeFromTopicEvent] = []
        try:
            with container.tracer.start_as_current_span(f"{name}.invoke") as span:
                span.set_attribute("id", id)
                span.set_attribute("name", name)
                span.set_attribute("type", type)
                span.set_attributes(input_data.model_dump())
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    oi_span_type.value,
                )

                # Invoke the original function
                result_content = ""
                is_streaming = False
                async for event in func(self, input_data):
                    for message in event.data:
                        if message.is_streaming:
                            if message.content is not None and isinstance(
                                message.content, str
                            ):
                                result_content += message.content
                            is_streaming = True
                    yield event
                    result.append(event)

                if is_streaming:
                    streaming_consumed_event = result[-1].model_copy(
                        update={
                            "data": [Message(role="assistant", content=result_content)]
                        },
                        deep=True,
                    )
                    result = [streaming_consumed_event]

                output_data_dict = json.dumps(result, default=to_jsonable_python)
                span.set_attribute("output", output_data_dict)

        except Exception as e:
            # Exception occurred during invoke
            span.set_attribute("error", str(e))
            container.event_store.record_event(
                WorkflowFailedEvent(
                    id=id,
                    invoke_context=input_data.invoke_context,
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
                WorkflowRespondEvent(
                    id=id,
                    invoke_context=input_data.invoke_context,
                    type=type,
                    name=name,
                    input_data=input_data,
                    output_data=result,
                )
            )

    return wrapper
