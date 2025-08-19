"""Provides decorators for recording workflow invoke events and adding tracing."""

import functools
import json
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
from grafi.workflows.workflow import T_W


def record_workflow_invoke(
    func: Callable[[T_W, PublishToTopicEvent], List[ConsumeFromTopicEvent]],
) -> Callable[[T_W, PublishToTopicEvent], List[ConsumeFromTopicEvent]]:
    """
    Decorator to record workflow invoke events and add tracing.

    Args:
        func: The workflow function to be decorated.

    Returns:
        Wrapped function that records events and adds tracing.
    """

    @functools.wraps(func)
    def wrapper(
        self: T_W,
        input_data: PublishToTopicEvent,
    ) -> List[ConsumeFromTopicEvent]:
        id: str = self.workflow_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        name: str = self.name or ""
        type: str = self.type or ""

        # Record the 'invoke' event
        container.event_store.record_event(
            WorkflowInvokeEvent(
                id=id,
                type=type,
                name=name,
                invoke_context=input_data.invoke_context,
                input_data=input_data,
            )
        )

        # Invoke the original function
        try:
            with container.tracer.start_as_current_span(f"{name}.invoke") as span:
                span.set_attribute("id", id)
                span.set_attribute("name", name)
                span.set_attribute("type", type)
                span.set_attributes(input_data.to_dict())
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    oi_span_type.value,
                )

                # Invoke the original function
                result: List[ConsumeFromTopicEvent] = func(self, input_data)

                output_data_dict = json.dumps(result, default=to_jsonable_python)
                span.set_attribute("output", output_data_dict)

        except Exception as e:
            # Exception occurred during invoke
            span.set_attribute("error", str(e))
            container.event_store.record_event(
                WorkflowFailedEvent(
                    id=id,
                    type=type,
                    name=name,
                    input_data=input_data,
                    invoke_context=input_data.invoke_context,
                    error=str(e),
                )
            )
            raise
        else:
            # Successful invoke
            container.event_store.record_event(
                WorkflowRespondEvent(
                    id=id,
                    type=type,
                    name=name,
                    input_data=input_data,
                    invoke_context=input_data.invoke_context,
                    output_data=result,
                )
            )
        return result

    return wrapper
