import functools
import json
from typing import Callable

from openinference.semconv.trace import SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.assistants.assistant_base import A
from grafi.common.containers.container import container
from grafi.common.events.assistant_events.assistant_event import ASSISTANT_ID
from grafi.common.events.assistant_events.assistant_event import ASSISTANT_NAME
from grafi.common.events.assistant_events.assistant_event import ASSISTANT_TYPE
from grafi.common.events.assistant_events.assistant_failed_event import (
    AssistantFailedEvent,
)
from grafi.common.events.assistant_events.assistant_invoke_event import (
    AssistantInvokeEvent,
)
from grafi.common.events.assistant_events.assistant_respond_event import (
    AssistantRespondEvent,
)
from grafi.common.instrumentations.tracing import tracer
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages


def record_assistant_execution(
    func: Callable[[A, ExecutionContext, Messages], Messages],
) -> Callable[[A, ExecutionContext, Messages], Messages]:
    """
    Decorator to record assistant execution events and add tracing.

    Args:
        func: The assistant function to be decorated.

    Returns:
        Wrapped function that records events and adds tracing.
    """

    @functools.wraps(func)
    def wrapper(
        self: A,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Messages:
        assistant_id = self.assistant_id
        assistant_name = self.name or ""
        assistant_type = self.type or ""
        model = getattr(self, "model", "")
        input_data_dict = json.dumps(input_data, default=to_jsonable_python)

        if container.event_store:
            # Record the 'invoke' event
            container.event_store.record_event(
                AssistantInvokeEvent(
                    assistant_id=assistant_id,
                    assistant_name=assistant_name,
                    assistant_type=assistant_type,
                    execution_context=execution_context,
                    input_data=input_data,
                )
            )

        # Execute the original function
        try:
            with tracer.start_as_current_span(f"{assistant_name}.run") as span:
                # Set span attributes of the assistant
                span.set_attribute(ASSISTANT_ID, assistant_id)
                span.set_attribute(ASSISTANT_NAME, assistant_name)
                span.set_attribute(ASSISTANT_TYPE, assistant_type)
                span.set_attributes(execution_context.model_dump())
                span.set_attribute("input", input_data_dict)
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    self.oi_span_type.value,
                )
                span.set_attribute("model", model)

                # Execute the original function
                result = func(self, execution_context, input_data)

                # Record the output data
                output_data_dict = json.dumps(result, default=to_jsonable_python)
                span.set_attribute("output", output_data_dict)
        except Exception as e:
            # Exception occurred during execution
            if container.event_store:
                span.set_attribute("error", str(e))
                container.event_store.record_event(
                    AssistantFailedEvent(
                        assistant_id=assistant_id,
                        assistant_name=assistant_name,
                        assistant_type=assistant_type,
                        execution_context=execution_context,
                        input_data=input_data,
                        error=str(e),
                    )
                )
            raise
        else:
            # Successful execution
            if container.event_store:
                container.event_store.record_event(
                    AssistantRespondEvent(
                        assistant_id=assistant_id,
                        assistant_name=assistant_name,
                        assistant_type=assistant_type,
                        execution_context=execution_context,
                        input_data=input_data,
                        output_data=result,
                    )
                )
        return result

    return wrapper
