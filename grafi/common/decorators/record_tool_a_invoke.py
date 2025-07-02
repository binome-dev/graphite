"""Decorator for recording tool invoke events and tracing."""

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
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.tool import T_T


def record_tool_a_invoke(
    func: Callable[[T_T, InvokeContext, Messages], MsgsAGen],
) -> Callable[[T_T, InvokeContext, Messages], MsgsAGen]:
    """Decorator to record tool invoke events and tracing."""

    @functools.wraps(func)
    async def wrapper(
        self: T_T,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        tool_id, tool_name, tool_type = self.tool_id, self.name or "", self.type or ""
        input_data_dict = json.dumps(input_data, default=to_jsonable_python)

        container.event_store.record_event(
            ToolInvokeEvent(
                tool_id=tool_id,
                invoke_context=invoke_context,
                tool_type=tool_type,
                tool_name=tool_name,
                input_data=input_data,
            )
        )

        result: Messages = []

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
                    self.oi_span_type.value,
                )

                # --------------------------------------------------
                # iterate over the ORIGINAL async‑generator
                # --------------------------------------------------
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
                # --------------------------------------------------

                span.set_attribute(
                    "output", json.dumps(result, default=to_jsonable_python)
                )
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

    return wrapper
