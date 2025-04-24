"""Decorator for recording tool execution events and tracing."""

import functools
import json
from typing import Callable

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
from grafi.common.models.message import MsgsAGen
from grafi.tools.tool import T


def record_tool_a_stream(
    func: Callable[[T, ExecutionContext, Messages], MsgsAGen],
) -> Callable[[T, ExecutionContext, Messages], MsgsAGen]:
    """Decorator to record tool execution events and tracing."""

    @functools.wraps(func)
    async def wrapper(
        self: T,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:
        tool_id, tool_name, tool_type = self.tool_id, self.name or "", self.type or ""
        input_data_dict = json.dumps(input_data, default=to_jsonable_python)

        if container.event_store:
            container.event_store.record_event(
                ToolInvokeEvent(
                    tool_id=tool_id,
                    execution_context=execution_context,
                    tool_type=tool_type,
                    tool_name=tool_name,
                    input_data=input_data,
                )
            )

        result: Messages = []

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
                    self.oi_span_type.value,
                )

                # --------------------------------------------------
                # iterate over the ORIGINAL async‑generator
                # --------------------------------------------------
                result_content = ""
                async for data in func(self, execution_context, input_data):
                    for message in data:
                        if message.content is not None and isinstance(
                            message.content, str
                        ):
                            result_content += message.content
                    yield data
                # --------------------------------------------------

                span.set_attribute(
                    "output", json.dumps(result, default=to_jsonable_python)
                )
        except Exception as e:
            # Exception occurred during execution
            if container.event_store:
                failed_event = ToolFailedEvent(
                    tool_id=tool_id,
                    execution_context=execution_context,
                    tool_type=tool_type,
                    tool_name=tool_name,
                    input_data=input_data,
                    error=str(e),
                )
                container.event_store.record_event(failed_event)
            raise
        else:
            # Successful execution
            if container.event_store:
                respond_event = ToolRespondEvent(
                    tool_id=tool_id,
                    execution_context=execution_context,
                    tool_type=tool_type,
                    tool_name=tool_name,
                    input_data=input_data,
                    output_data=result,
                )
                container.event_store.record_event(respond_event)

    return wrapper
