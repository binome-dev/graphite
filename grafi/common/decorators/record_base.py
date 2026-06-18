"""Base decorator utilities for recording component invoke events and tracing."""

import functools
import json
import os
from dataclasses import dataclass
from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import Dict
from typing import List
from typing import Type
from typing import TypeVar
from typing import Union

from loguru import logger
from opentelemetry.trace import Status
from opentelemetry.trace import StatusCode
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic_core import to_jsonable_python

from grafi.assistants.assistant_base import AssistantBase
from grafi.common.containers.container import container
from grafi.common.env import env_bool
from grafi.common.events.component_base import ComponentEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions.serialization import error_message
from grafi.common.exceptions.serialization import error_to_dict
from grafi.common.exceptions.serialization import iter_cause_chain
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node_base import NodeBase
from grafi.tools.tool import Tool
from grafi.workflows.workflow import Workflow

T = TypeVar("T")

# Attribute used to mark an exception whose full traceback has already been
# logged, so the same root failure is not dumped at every decorator layer.
_TRACEBACK_LOGGED_ATTR = "_grafi_traceback_logged"


class EventContext(BaseModel):
    id: str = default_id
    name: str = ""
    type: str = ""
    oi_span_type: str = ""

    model_config = ConfigDict(
        extra="allow"
    )  # Allow additional fields to be added dynamically


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


_DEFAULT_SPAN_MAX_PAYLOAD_CHARS = 10_000


def _span_payloads_disabled() -> bool:
    """Whether input/output payloads should be omitted from spans entirely.

    Set ``GRAFI_SPAN_DISABLE_PAYLOADS`` to a truthy value in environments where
    prompts / tool args / message content must never reach the tracing backend.
    """
    return env_bool("GRAFI_SPAN_DISABLE_PAYLOADS", default=False)


def _span_max_payload_chars() -> int:
    """Max characters of a serialized payload to attach to a span (0 = unbounded).

    Defaults to 10k characters so a single large prompt/response cannot bloat a
    span unbounded. Override with ``GRAFI_SPAN_MAX_PAYLOAD_CHARS``.
    """
    raw = os.getenv("GRAFI_SPAN_MAX_PAYLOAD_CHARS")
    if raw is None:
        return _DEFAULT_SPAN_MAX_PAYLOAD_CHARS
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_SPAN_MAX_PAYLOAD_CHARS


def _span_payload(value: Any) -> Union[str, None]:
    """Serialize a value for a span attribute, size-bounded and opt-out-able.

    Returns ``None`` when payloads are disabled, so the caller can skip setting
    the attribute altogether.
    """
    if _span_payloads_disabled():
        return None
    try:
        text = json.dumps(value, default=to_jsonable_python)
    except (TypeError, ValueError):
        text = repr(value)
    max_chars = _span_max_payload_chars()
    if max_chars and len(text) > max_chars:
        return f"{text[:max_chars]}...[truncated {len(text) - max_chars} chars]"
    return text


def _include_traceback() -> bool:
    """Whether to capture tracebacks into structured error details.

    Enabled by default. Set ``GRAFI_ERROR_INCLUDE_TRACEBACK`` to a falsy value
    (``0``/``false``/``no``/``off``) to omit tracebacks from persisted events,
    e.g. in production where they may carry sensitive paths or large payloads.
    """
    return env_bool("GRAFI_ERROR_INCLUDE_TRACEBACK", default=True)


def _build_error_details(exc: Exception, metadata: EventContext) -> Dict[str, Any]:
    """Build the structured ``error_details`` payload for a failed component."""
    details = error_to_dict(exc, include_traceback=_include_traceback())
    # Identify which component failed (the "where"), alongside the exception's
    # own type/module/cause chain (the "why").
    details["component_id"] = metadata.id
    details["component_name"] = metadata.name
    details["component_type"] = metadata.type
    return details


def _record_span_error(
    span: Any, exc: Exception, error_details: Dict[str, Any]
) -> None:
    """Attach structured error information to the active span."""
    span.set_attribute("error", str(exc))
    span.set_attribute("error.type", error_details["error_type"])
    span.set_attribute("error.message", error_details["message"])
    traceback_str = error_details.get("traceback")
    if traceback_str:
        span.set_attribute("error.stack", traceback_str)
    try:
        span.set_attribute(
            "error.details", json.dumps(error_details, default=to_jsonable_python)
        )
    except (TypeError, ValueError):
        pass
    try:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, error_details["message"]))
    except Exception:  # pragma: no cover - defensive; span impls vary
        pass


def _traceback_already_logged(exc: Exception) -> bool:
    """True if any exception in the cause chain has had its traceback logged."""
    # Scan generously: each decorator layer marks the exception it sees (below),
    # so the flag is normally within a few links, but a large bound keeps the
    # invariant robust for deeply nested agent-calling chains. The cycle guard in
    # iter_cause_chain prevents runaway traversal.
    return any(
        getattr(link, _TRACEBACK_LOGGED_ATTR, False)
        for link in iter_cause_chain(exc, max_depth=1000)
    )


def _log_component_exception(
    exc: Exception,
    metadata: EventContext,
    invoke_context: InvokeContext,
    error_details: Dict[str, Any],
) -> None:
    """Log a failed component, with a full traceback only once.

    The same root failure propagates through the tool -> node -> workflow ->
    assistant decorators (and is re-wrapped along the way). Logging the full
    traceback at every layer would print the same stack four-plus times, so the
    full traceback is emitted once at the layer closest to the failure (the first
    decorator to catch it); outer layers log a one-line summary instead.

    The traceback is taken from ``error_details`` -- a plain, stdlib-formatted
    string that does NOT include local-variable values (unlike Loguru's
    ``opt(exception=...)`` with ``diagnose=True``). This keeps secrets/PII out of
    logs and honors GRAFI_ERROR_INCLUDE_TRACEBACK (the key is absent when the
    switch disables traceback capture), without forcing global Loguru config.
    """
    bound = logger.bind(
        component_id=metadata.id,
        component_name=metadata.name,
        component_type=metadata.type,
        conversation_id=getattr(invoke_context, "conversation_id", None),
        invoke_id=getattr(invoke_context, "invoke_id", None),
        assistant_request_id=getattr(invoke_context, "assistant_request_id", None),
    )
    component_label = metadata.type or "component"
    summary = (
        f"{component_label} '{metadata.name}' failed: "
        f"{type(exc).__name__}: {error_message(exc)}"
    )

    already_logged = _traceback_already_logged(exc)
    # Mark this exception (including re-wrapped outer ones) so the next decorator
    # layer finds the flag within one link of the chain regardless of nesting
    # depth, keeping the full traceback to a single emission.
    try:
        setattr(exc, _TRACEBACK_LOGGED_ATTR, True)
    except Exception:  # pragma: no cover - builtins generally allow attributes
        pass

    traceback_str = error_details.get("traceback")
    # Pass values as arguments so any braces in them are not re-interpreted as
    # Loguru format placeholders.
    if already_logged or not traceback_str:
        bound.error("{}", summary)
    else:
        bound.error("{}\n{}", summary, traceback_str)


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

            if isinstance(args[0], InvokeContext):
                invoke_context: InvokeContext = args[0]
                input_data = args[1]
            else:
                # Assistant and workflow
                input_data = args[0]
                invoke_context = input_data.invoke_context

            # Create invoke event
            invoke_event = config.event_types["invoke"](
                id=metadata.id,
                name=metadata.name,
                type=metadata.type,
                input_data=input_data,
                invoke_context=invoke_context,
            )
            await container.event_store.record_event(invoke_event)

            # Execute with tracing
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

                    # Set input (size-bounded; omitted if payloads are disabled)
                    input_payload = _span_payload(input_data)
                    if input_payload is not None:
                        span.set_attribute("input", input_payload)

                    # Handle streaming
                    result_list: List = []

                    async for result in func(self, *args, **kwargs):
                        yield result
                        result_list.append(result)

                    output_data = config.process_async_result(result_list)

                    output_payload = _span_payload(output_data)
                    if output_payload is not None:
                        span.set_attribute("output", output_payload)

            except Exception as e:
                # Build structured details once, while the traceback is still
                # attached to the exception.
                error_details = _build_error_details(e, metadata)

                # Enrich the active span with structured error information.
                if "span" in locals():
                    _record_span_error(span, e, error_details)

                # Log a full traceback once at the layer closest to the failure;
                # outer layers log a concise summary (see _log_component_exception).
                _log_component_exception(e, metadata, invoke_context, error_details)

                # Record failed event with both the human-readable string (kept
                # for backward compatibility) and the structured details.
                failed_event = config.event_types["failed"](
                    id=metadata.id,
                    name=metadata.name,
                    type=metadata.type,
                    input_data=input_data,
                    invoke_context=invoke_context,
                    error=str(e),
                    error_details=error_details,
                )
                await container.event_store.record_event(failed_event)
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
                await container.event_store.record_event(respond_event)

        return wrapper

    return decorator
