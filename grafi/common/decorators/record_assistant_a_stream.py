"""Decorator for recording node execution events and tracing."""

import functools
import json
from typing import AsyncGenerator, List

from openinference.semconv.trace import SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.assistants.assistant_base import AssistantBase
from grafi.common.containers.container import event_store
from grafi.common.events.assistant_events.assistant_event import (
    ASSISTANT_ID,
    ASSISTANT_NAME,
    ASSISTANT_TYPE,
)
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
from grafi.common.models.message import Message


def record_assistant_a_stream(func):
    """Decorator to record node execution events and tracing."""

    @functools.wraps(func)
    async def wrapper(self: AssistantBase, *args, **kwargs):
        assistant_id = self.assistant_id
        assistant_name = self.name
        assistant_type = self.type
        execution_context: ExecutionContext = (
            args[0] if args else kwargs.get("execution_context", None)
        )
        model = getattr(self, "model", None)
        input_data: List[Message] = (
            args[1] if (args and len(args) > 1) else kwargs.get("input_data", "")
        )
        input_data_dict = json.dumps(input_data, default=to_jsonable_python)

        assistant_event_base = {
            ASSISTANT_ID: assistant_id,
            "execution_context": execution_context,
            ASSISTANT_TYPE: assistant_type,
            ASSISTANT_NAME: assistant_name,
            "input_data": input_data,
        }

        if event_store:
            # Record the 'invoke' event
            invoke_event = AssistantInvokeEvent(
                **assistant_event_base,
            )
            event_store.record_event(invoke_event)

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
                span.set_attribute("input", input_data_dict)

                # Execute the node function
                stream_result: AsyncGenerator[Message, None] = await func(
                    self, *args, **kwargs
                )
                result_content = ""
                async for data in stream_result:
                    if data.content is not None:
                        result_content += data.content
                    yield data

                result = Message(role="assistant", content=result_content)

                output_data_dict = json.dumps(result, default=to_jsonable_python)
                span.set_attribute("output", output_data_dict)
        except Exception as e:
            # Exception occurred during execution
            if event_store:
                failed_event = AssistantFailedEvent(
                    **assistant_event_base,
                    error=str(e),
                )
                span.set_attribute("error", str(e))
                event_store.record_event(failed_event)
            raise
        else:
            # Successful execution
            if event_store:
                respond_event = AssistantRespondEvent(
                    **assistant_event_base,
                    output_data=[result],
                )
                event_store.record_event(respond_event)

    return wrapper
