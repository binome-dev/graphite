import functools
import json
from typing import AsyncGenerator
from typing import Callable
from typing import List

from openinference.semconv.trace import SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.assistants.assistant_base import T_A
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
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.message import Message


def record_assistant_a_invoke(
    func: Callable[
        [T_A, PublishToTopicEvent], AsyncGenerator[ConsumeFromTopicEvent, None]
    ],
) -> Callable[[T_A, PublishToTopicEvent], AsyncGenerator[ConsumeFromTopicEvent, None]]:
    """
    Decorator to record assistant invoke events and add tracing.

    Args:
        func: The assistant function to be decorated.

    Returns:
        Wrapped function that records events and adds tracing.
    """

    @functools.wraps(func)
    async def wrapper(
        self: T_A,
        input_event: PublishToTopicEvent,
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        assistant_id = self.assistant_id
        assistant_name = self.name or ""
        assistant_type = self.type or ""
        model: str = getattr(self, "model", "")

        # Record the 'invoke' event
        container.event_store.record_event(
            AssistantInvokeEvent(
                assistant_id=assistant_id,
                assistant_name=assistant_name,
                assistant_type=assistant_type,
                invoke_context=input_event.invoke_context,
                input_event=input_event,
            )
        )

        # Invoke the original function
        result: List[ConsumeFromTopicEvent] = []
        try:
            with container.tracer.start_as_current_span(
                f"{assistant_name}.run"
            ) as span:
                # Set span attributes of the assistant
                span.set_attribute(ASSISTANT_ID, assistant_id)
                span.set_attribute(ASSISTANT_NAME, assistant_name)
                span.set_attribute(ASSISTANT_TYPE, assistant_type)
                span.set_attributes(input_event.model_dump())
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    self.oi_span_type.value,
                )
                span.set_attribute("model", model)

                # Invoke the original function
                result_content = ""
                is_streaming = False
                async for event in func(self, input_event):
                    for message in event.data:
                        if message.is_streaming:
                            if message.content is not None and isinstance(
                                message.content, str
                            ):
                                result_content += message.content
                            is_streaming = True
                    yield event
                    result.append(event)

                if is_streaming:
                    streaming_consumed_event = result[-1].model_copy(
                        update={
                            "data": [Message(role="assistant", content=result_content)]
                        },
                        deep=True,
                    )
                    result = [streaming_consumed_event]

                # Record the output data
                output_data_dict = json.dumps(result, default=to_jsonable_python)
                span.set_attribute("output", output_data_dict)
        except Exception as e:
            # Exception occurred during invoke
            span.set_attribute("error", str(e))
            container.event_store.record_event(
                AssistantFailedEvent(
                    assistant_id=assistant_id,
                    assistant_name=assistant_name,
                    assistant_type=assistant_type,
                    invoke_context=input_event.invoke_context,
                    input_event=input_event,
                    error=str(e),
                )
            )
            raise
        else:
            # Successful invoke
            container.event_store.record_event(
                AssistantRespondEvent(
                    assistant_id=assistant_id,
                    assistant_name=assistant_name,
                    assistant_type=assistant_type,
                    invoke_context=input_event.invoke_context,
                    input_event=input_event,
                    output_data=result,
                )
            )

    return wrapper
