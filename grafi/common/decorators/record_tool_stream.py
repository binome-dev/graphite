"""Decorator for recording tool execution events and tracing."""

import functools
import json
from typing import Callable
from typing import Generator

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
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.tool import T_T


def record_tool_stream(
    func: Callable[[T_T, ExecutionContext, Messages], Generator],
) -> Callable[[T_T, ExecutionContext, Messages], Generator]:
    """Decorator to record tool execution events and tracing."""

    @functools.wraps(func)
    def wrapper(
        self: T_T,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Generator:
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
            with container.tracer.start_as_current_span(f"{tool_name}.execute") as span:
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
                stream_result: Generator[Messages, None, None] = func(
                    self, execution_context, input_data
                )

                result_content = ""
                for data in stream_result:
                    for message in data:
                        if message.content is not None and isinstance(
                            message.content, str
                        ):
                            result_content += message.content
                    yield data

                result = Message(role="assistant", content=result_content)
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
                        output_data=[result],
                    )
                )
        return result

    return wrapper
