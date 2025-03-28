"""Provides decorators for recording workflow execution events and adding tracing."""

import functools
import json
from typing import List, Union

from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from pydantic_core import to_jsonable_python

from grafi.common.containers.container import event_store
from grafi.common.events.workflow_events.workflow_event import (
    WORKFLOW_ID,
    WORKFLOW_NAME,
    WORKFLOW_TYPE,
)
from grafi.common.events.workflow_events.workflow_failed_event import (
    WorkflowFailedEvent,
)
from grafi.common.events.workflow_events.workflow_invoke_event import (
    WorkflowInvokeEvent,
)
from grafi.common.instrumentations.tracing import tracer
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.workflows.workflow import Workflow


def record_workflow_execution(func):
    """
    Decorator to record workflow execution events and add tracing.

    Args:
        func: The workflow function to be decorated.

    Returns:
        Wrapped function that records events and adds tracing.
    """

    @functools.wraps(func)
    def wrapper(self: Workflow, *args, **kwargs):
        workflow_id: str = self.workflow_id
        oi_span_type: OpenInferenceSpanKindValues = self.oi_span_type
        execution_context: ExecutionContext = (
            args[0] if args else kwargs.get("execution_context", None)
        )
        workflow_name: str = self.name
        workflow_type: str = self.type
        input_data: Union[Message, List[Message]] = (
            args[1] if (args and len(args) > 1) else kwargs.get("input", {})
        )

        input_data_dict = json.dumps(input_data, default=to_jsonable_python)

        workflow_event_base = {
            WORKFLOW_ID: workflow_id,
            "execution_context": execution_context,
            WORKFLOW_TYPE: workflow_type,
            WORKFLOW_NAME: workflow_name,
            "input_data": input_data,
        }

        if event_store:
            # Record the 'invoke' event
            invoke_event = WorkflowInvokeEvent(
                **workflow_event_base,
            )
            event_store.record_event(invoke_event)

        # Execute the original function
        try:
            with tracer.start_as_current_span(f"{workflow_name}.execute") as span:
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
                func(self, *args, **kwargs)

        except Exception as e:
            # Exception occurred during execution
            if event_store:
                failed_event = WorkflowFailedEvent(
                    **workflow_event_base,
                    error=str(e),
                )
                event_store.record_event(failed_event)
            raise

    return wrapper
