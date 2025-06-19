"""Provides decorators for recording workflow execution events and adding tracing."""

import functools
import json
from typing import Callable

from openinference.semconv.trace import OpenInferenceSpanKindValues
from openinference.semconv.trace import SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.common.containers.container import container
from grafi.common.events.workflow_events.workflow_event import WORKFLOW_ID
from grafi.common.events.workflow_events.workflow_event import WORKFLOW_NAME
from grafi.common.events.workflow_events.workflow_event import WORKFLOW_TYPE
from grafi.common.events.workflow_events.workflow_failed_event import (
    WorkflowFailedEvent,
)
from grafi.common.events.workflow_events.workflow_invoke_event import (
    WorkflowInvokeEvent,
)
from grafi.common.events.workflow_events.workflow_respond_event import (
    WorkflowRespondEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.workflows.workflow import T_W


def record_workflow_execution(
    func: Callable[[T_W, ExecutionContext, Messages], Messages],
) -> Callable[[T_W, ExecutionContext, Messages], Messages]:
    """
    Decorator to record workflow execution events and add tracing.

    Args:
        func: The workflow function to be decorated.

    Returns:
        Wrapped function that records events and adds tracing.
    """

    @functools.wraps(func)
    def wrapper(
        self: T_W,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Messages:
        workflow_id: str = self.workflow_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        workflow_name: str = self.name or ""
        workflow_type: str = self.type or ""

        input_data_dict = json.dumps(input_data, default=to_jsonable_python)

        # Record the 'invoke' event
        container.event_store.record_event(
            WorkflowInvokeEvent(
                workflow_id=workflow_id,
                execution_context=execution_context,
                workflow_type=workflow_type,
                workflow_name=workflow_name,
                input_data=input_data,
            )
        )

        # Execute the original function
        try:
            with container.tracer.start_as_current_span(
                f"{workflow_name}.execute"
            ) as span:
                span.set_attribute(WORKFLOW_ID, workflow_id)
                span.set_attribute(WORKFLOW_NAME, workflow_name)
                span.set_attribute(WORKFLOW_TYPE, workflow_type)
                span.set_attributes(execution_context.model_dump())
                span.set_attribute("input", input_data_dict)
                span.set_attribute(
                    SpanAttributes.OPENINFERENCE_SPAN_KIND,
                    oi_span_type.value,
                )

                # Execute the original function
                result: Messages = func(self, execution_context, input_data)

                output_data_dict = json.dumps(result, default=to_jsonable_python)
                span.set_attribute("output", output_data_dict)

        except Exception as e:
            # Exception occurred during execution
            span.set_attribute("error", str(e))
            container.event_store.record_event(
                WorkflowFailedEvent(
                    workflow_id=workflow_id,
                    execution_context=execution_context,
                    workflow_type=workflow_type,
                    workflow_name=workflow_name,
                    input_data=input_data,
                    error=str(e),
                )
            )
            raise
        else:
            # Successful execution
            container.event_store.record_event(
                WorkflowRespondEvent(
                    workflow_id=workflow_id,
                    execution_context=execution_context,
                    workflow_type=workflow_type,
                    workflow_name=workflow_name,
                    input_data=input_data,
                    output_data=result,
                )
            )
        return result

    return wrapper
