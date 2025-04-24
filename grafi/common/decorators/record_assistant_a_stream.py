"""Decorator for recording node execution events and tracing."""

import functools
import json
from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import Coroutine

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
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen


def record_assistant_a_stream(
    func: Callable[[A, ExecutionContext, Messages], Coroutine[Any, Any, MsgsAGen]],
) -> Callable[[A, ExecutionContext, Messages], MsgsAGen]:
    """Decorator to record node execution events and tracing."""

    @functools.wraps(func)
    async def wrapper(
        self: A,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> AsyncGenerator:
        assistant_id = self.assistant_id
        assistant_name = self.name or ""
        assistant_type = self.type or ""
        model: str = getattr(self, "model", "")
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
                span.set_attribute("input", input_data_dict)

                # Execute the node function
                stream_result: MsgsAGen = await func(
                    self, execution_context, input_data
                )
                result_content = ""
                async for data in stream_result:
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
                        output_data=[result],
                    )
                )

    return wrapper
