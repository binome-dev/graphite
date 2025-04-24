"""Decorator for recording tool execution events and tracing."""

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
from grafi.common.instrumentations.tracing import tracer
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.tools.tool import T


def record_tool_execution(
    func: Callable[[T, ExecutionContext, Messages], Messages],
) -> Callable[[T, ExecutionContext, Messages], Messages]:
    """Decorator to record tool execution events and tracing."""

    @functools.wraps(func)
    def wrapper(
        self: T,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Messages:
        tool_id: str = self.tool_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        tool_name: str = self.name or ""
        tool_type: str = self.type or ""

        input_data_dict = json.dumps(input_data, default=to_jsonable_python)

        if container.event_store:
            # Record the 'invoke' event
            container.event_store.record_event(
                ToolInvokeEvent(
                    tool_id=tool_id,
                    execution_context=execution_context,
                    tool_type=tool_type,
                    tool_name=tool_name,
                    input_data=input_data,
                )
            )

        # Execute the original function
        try:
            with tracer.start_as_current_span(f"{tool_name}.execute") as span:
                span.set_attribute(TOOL_ID, tool_id)
                span.set_attribute(TOOL_NAME, tool_name)
                span.set_attribute(TOOL_TYPE, tool_type)
                span.set_attributes(execution_context.model_dump())
                span.set_attribute("input", input_data_dict)
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    oi_span_type.value,
                )

                # Execute the original function
                result = func(self, execution_context, input_data)

                output_data_dict = json.dumps(result, default=to_jsonable_python)

                span.set_attribute("output", output_data_dict)
        except Exception as e:
            # Exception occurred during execution
            if container.event_store:
                container.event_store.record_event(
                    ToolFailedEvent(
                        tool_id=tool_id,
                        execution_context=execution_context,
                        tool_type=tool_type,
                        tool_name=tool_name,
                        input_data=input_data,
                        error=str(e),
                    )
                )
            raise
        else:
            # Successful execution
            if container.event_store:
                container.event_store.record_event(
                    ToolRespondEvent(
                        tool_id=tool_id,
                        execution_context=execution_context,
                        tool_type=tool_type,
                        tool_name=tool_name,
                        input_data=input_data,
                        output_data=result,
                    )
                )
        return result

    return wrapper
