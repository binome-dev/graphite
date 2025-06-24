"""Decorator for recording tool invoke events and tracing."""

import functools
import json
from typing import Callable

from openinference.semconv.trace import OpenInferenceSpanKindValues
from openinference.semconv.trace import SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.common.containers.container import container
from grafi.common.events.tool_events.tool_event import TOOL_ID
from grafi.common.events.tool_events.tool_event import TOOL_NAME
from grafi.common.events.tool_events.tool_event import TOOL_TYPE
from grafi.common.events.tool_events.tool_failed_event import ToolFailedEvent
from grafi.common.events.tool_events.tool_invoke_event import ToolInvokeEvent
from grafi.common.events.tool_events.tool_respond_event import ToolRespondEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.tools.tool import T_T


def record_tool_invoke(
    func: Callable[[T_T, InvokeContext, Messages], Messages],
) -> Callable[[T_T, InvokeContext, Messages], Messages]:
    """Decorator to record tool invoke events and tracing."""

    @functools.wraps(func)
    def wrapper(
        self: T_T,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> Messages:
        tool_id: str = self.tool_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        tool_name: str = self.name or ""
        tool_type: str = self.type or ""

        input_data_dict = json.dumps(input_data, default=to_jsonable_python)

        # Record the 'invoke' event
        container.event_store.record_event(
            ToolInvokeEvent(
                tool_id=tool_id,
                invoke_context=invoke_context,
                tool_type=tool_type,
                tool_name=tool_name,
                input_data=input_data,
            )
        )

        # Invoke the original function
        try:
            with container.tracer.start_as_current_span(f"{tool_name}.invoke") as span:
                span.set_attribute(TOOL_ID, tool_id)
                span.set_attribute(TOOL_NAME, tool_name)
                span.set_attribute(TOOL_TYPE, tool_type)
                span.set_attributes(invoke_context.model_dump())
                span.set_attribute("input", input_data_dict)
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    oi_span_type.value,
                )

                # Invoke the original function
                result = func(self, invoke_context, input_data)

                output_data_dict = json.dumps(result, default=to_jsonable_python)

                span.set_attribute("output", output_data_dict)
        except Exception as e:
            # Exception occurred during invoke
            span.set_attribute("error", str(e))
            container.event_store.record_event(
                ToolFailedEvent(
                    tool_id=tool_id,
                    invoke_context=invoke_context,
                    tool_type=tool_type,
                    tool_name=tool_name,
                    input_data=input_data,
                    error=str(e),
                )
            )
            raise
        else:
            # Successful invoke
            container.event_store.record_event(
                ToolRespondEvent(
                    tool_id=tool_id,
                    invoke_context=invoke_context,
                    tool_type=tool_type,
                    tool_name=tool_name,
                    input_data=input_data,
                    output_data=result,
                )
            )

        return result

    return wrapper
