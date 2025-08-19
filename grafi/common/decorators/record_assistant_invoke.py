import functools
import json
from typing import Callable
from typing import List

from openinference.semconv.trace import SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.assistants.assistant_base import T_A
from grafi.common.containers.container import container
from grafi.common.events.assistant_events.assistant_failed_event import (
    AssistantFailedEvent,
)
from grafi.common.events.assistant_events.assistant_invoke_event import (
    AssistantInvokeEvent,
)
from grafi.common.events.assistant_events.assistant_respond_event import (
    AssistantRespondEvent,
)
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent


def record_assistant_invoke(
    func: Callable[[T_A, PublishToTopicEvent], List[ConsumeFromTopicEvent]],
) -> Callable[[T_A, PublishToTopicEvent], List[ConsumeFromTopicEvent]]:
    """
    Decorator to record assistant invoke events and add tracing.

    Args:
        func: The assistant function to be decorated.

    Returns:
        Wrapped function that records events and adds tracing.
    """

    @functools.wraps(func)
    def wrapper(
        self: T_A,
        input_data: PublishToTopicEvent,
    ) -> List[ConsumeFromTopicEvent]:
        id = self.assistant_id
        name = self.name or ""
        type = self.type or ""
        model = getattr(self, "model", "")

        # Record the 'invoke' event
        container.event_store.record_event(
            AssistantInvokeEvent(
                id=id,
                name=name,
                type=type,
                input_data=input_data,
                invoke_context=input_data.invoke_context,
            )
        )

        # Invoke the original function
        try:
            with container.tracer.start_as_current_span(f"{name}.run") as span:
                # Set span attributes of the assistant
                span.set_attribute("id", id)
                span.set_attribute("name", name)
                span.set_attribute("type", type)
                span.set_attributes(input_data.to_dict())
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    self.oi_span_type.value,
                )
                span.set_attribute("model", model)

                # Invoke the original function
                result = func(self, input_data)

                # Record the output data
                output_data_dict = json.dumps(result, default=to_jsonable_python)
                span.set_attribute("output", output_data_dict)
        except Exception as e:
            # Exception occurred during invoke
            span.set_attribute("error", str(e))
            container.event_store.record_event(
                AssistantFailedEvent(
                    id=id,
                    name=name,
                    type=type,
                    input_data=input_data,
                    invoke_context=input_data.invoke_context,
                    error=str(e),
                )
            )
            raise
        else:
            # Successful invoke
            container.event_store.record_event(
                AssistantRespondEvent(
                    id=id,
                    name=name,
                    type=type,
                    input_data=input_data,
                    invoke_context=input_data.invoke_context,
                    output_data=result,
                )
            )
        return result

    return wrapper
