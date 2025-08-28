"""Base decorator utilities for recording component invoke events and tracing."""

import functools
import json
from dataclasses import dataclass
from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import Dict
from typing import List
from typing import Type
from typing import TypeVar
from typing import Union

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from grafi.assistants.assistant_base import AssistantBase
from grafi.common.containers.container import container
from grafi.common.events.component_base_events import ComponentEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node_base import NodeBase
from grafi.tools.tool import Tool
from grafi.workflows.workflow import Workflow


T = TypeVar("T")


class EventContext(BaseModel):
    id: str = default_id
    name: str = ""
    type: str = ""
    oi_span_type: str = ""

    class Config:
        extra = "allow"  # Allow additional fields to be added dynamically


@dataclass
class ComponentConfig:
    """Configuration for component-specific behavior."""

    event_types: Dict[
        str, Type[ComponentEvent]
    ]  # Maps 'invoke', 'respond', 'failed' to event classes
    extract_metadata: Callable[
        [Union[AssistantBase, Workflow, NodeBase, Tool]], EventContext
    ]  # Extracts component-specific metadata
    process_async_result: Callable[[List], Any]
    span_name_suffix: str = "invoke"  # Suffix for span name


def create_sync_decorator(config: ComponentConfig) -> Callable:
    """
    Factory to create synchronous decorators for different component types.

    Args:
        config: Component-specific configuration

    Returns:
        A decorator function for the component type
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(
            self: Union[AssistantBase, Workflow, NodeBase, Tool],
            *args,
            **kwargs,
        ) -> Union[PublishToTopicEvent, List[Message]]:
            # Extract metadata using component-specific logic
            metadata = config.extract_metadata(self)

            input_data: Union[
                List[ConsumeFromTopicEvent], List[Message], PublishToTopicEvent
            ] = None

            invoke_context: InvokeContext = None

            if len(args) == 1:
                # Assistant and workflow
                input_data = args[0]
                invoke_context = input_data.invoke_context
            elif len(args) == 2:
                # Node and Tool
                invoke_context: InvokeContext = args[0]
                input_data = args[1]

            # Create invoke event
            invoke_event = config.event_types["invoke"](
                id=metadata.id,
                name=metadata.name,
                type=metadata.type,
                input_data=input_data,
                invoke_context=invoke_context,
            )
            container.event_store.record_event(invoke_event)

            # Execute with tracing
            try:
                with container.tracer.start_as_current_span(
                    f"{metadata.name}.{config.span_name_suffix}"
                ) as span:
                    # Set span attributes
                    for key, value in metadata.model_dump().items():
                        if value is not None:
                            span.set_attribute(key, value)

                    # Set context attributes
                    span.set_attributes(invoke_context.model_dump())

                    # Set input
                    span.set_attribute(
                        "input", json.dumps(input_data, default=to_jsonable_python)
                    )

                    # Execute function
                    result = func(self, *args, **kwargs)

                    # Set output
                    span.set_attribute(
                        "output", json.dumps(result, default=to_jsonable_python)
                    )

            except Exception as e:
                # Record failed event
                if "error" in locals():
                    span.set_attribute("error", str(e))

                failed_event = config.event_types["failed"](
                    id=metadata.id,
                    name=metadata.name,
                    type=metadata.type,
                    invoke_context=invoke_context,
                    input_data=input_data,
                    error=str(e),
                )
                container.event_store.record_event(failed_event)
                raise
            else:
                # Record respond event
                respond_event = config.event_types["respond"](
                    id=metadata.id,
                    name=metadata.name,
                    type=metadata.type,
                    input_data=input_data,
                    invoke_context=invoke_context,
                    output_data=result,
                )
                container.event_store.record_event(respond_event)

            return result

        return wrapper

    return decorator


def create_async_decorator(config: ComponentConfig) -> Callable:
    """
    Factory to create asynchronous decorators for different component types.

    Args:
        config: Component-specific configuration

    Returns:
        An async decorator function for the component type
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(
            self: Union[AssistantBase, Workflow, NodeBase, Tool],
            *args,
            **kwargs,
        ) -> AsyncGenerator[Union[PublishToTopicEvent, List[Message]], None]:
            # Extract metadata using component-specific logic
            metadata = config.extract_metadata(self)

            input_data: Union[
                List[ConsumeFromTopicEvent], List[Message], PublishToTopicEvent
            ] = None

            if len(args) == 1:
                # Assistant and workflow
                input_data: PublishToTopicEvent = args[0]
                invoke_context = input_data.invoke_context
            elif len(args) == 2:
                # Node and Tool
                invoke_context: InvokeContext = args[0]
                input_data = args[1]

            # Create invoke event
            invoke_event = config.event_types["invoke"](
                id=metadata.id,
                name=metadata.name,
                type=metadata.type,
                input_data=input_data,
                invoke_context=invoke_context,
            )
            container.event_store.record_event(invoke_event)

            # Execute with tracing
            result_list = []
            output_data = None

            try:
                with container.tracer.start_as_current_span(
                    f"{metadata.name}.{config.span_name_suffix}"
                ) as span:
                    # Set span attributes
                    for key, value in metadata.model_dump().items():
                        if value is not None:
                            span.set_attribute(key, value)

                    span.set_attributes(invoke_context.model_dump())

                    # Set input
                    span.set_attribute(
                        "input", json.dumps(input_data, default=to_jsonable_python)
                    )

                    # Handle streaming
                    result_list: List = []

                    async for result in func(self, *args, **kwargs):
                        yield result
                        result_list.append(result)

                    output_data = config.process_async_result(result_list)

                    span.set_attribute(
                        "output", json.dumps(output_data, default=to_jsonable_python)
                    )

            except Exception as e:
                # Record failed event
                if "span" in locals():
                    span.set_attribute("error", str(e))

                failed_event = config.event_types["failed"](
                    id=metadata.id,
                    name=metadata.name,
                    type=metadata.type,
                    input_data=input_data,
                    invoke_context=invoke_context,
                    error=str(e),
                )
                container.event_store.record_event(failed_event)
                raise
            else:
                # Record respond event
                respond_event = config.event_types["respond"](
                    id=metadata.id,
                    name=metadata.name,
                    type=metadata.type,
                    input_data=input_data,
                    invoke_context=invoke_context,
                    output_data=output_data,
                )
                container.event_store.record_event(respond_event)

        return wrapper

    return decorator
