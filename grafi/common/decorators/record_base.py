"""Base decorator utilities for recording component invoke events and tracing."""

import functools
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Type
from typing import TypeVar
from typing import Union

from opentelemetry.trace import Status
from opentelemetry.trace import StatusCode
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic_core import to_jsonable_python

from grafi.common.env import env_bool
from grafi.common.events.component_base import ComponentEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import EventPersistenceError
from grafi.common.exceptions.serialization import error_message
from grafi.common.exceptions.serialization import error_to_dict
from grafi.common.exceptions.serialization import iter_cause_chain
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime.execution_services import current_services

T = TypeVar("T")

# Attribute used to mark an exception whose full traceback has already been
# logged, so the same root failure is not dumped at every decorator layer.
_TRACEBACK_LOGGED_ATTR = "_grafi_traceback_logged"

# Attribute carrying the correlation id shared by every layer of one failure, so
# the wrapped/re-raised exception keeps a stable ``error_id`` across the
# tool -> node -> workflow -> assistant decorators.
_ERROR_ID_ATTR = "_grafi_error_id"


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
    # Extracts component-specific metadata. Typed as ``Any`` so this common-layer
    # module does not import the higher-layer component classes (Assistant /
    # Workflow / Node / Tool) just for an annotation.
    extract_metadata: Callable[[Any], EventContext]
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


def _error_correlation(exc: Exception) -> tuple[str, BaseException]:
    """Walk the cause chain once and return ``(error_id, root_cause)``.

    The error id is the one already stashed on any link of the chain (so a
    re-wrapped outer exception inherits the id minted at the layer closest to the
    root failure); if the chain has none, mint one and stash it on ``exc`` for
    the next decorator layer. The root cause is the innermost link.
    """
    error_id: Optional[str] = None
    root: BaseException = exc
    for link in iter_cause_chain(exc, max_depth=1000):
        if error_id is None:
            existing = getattr(link, _ERROR_ID_ATTR, None)
            if existing:
                error_id = str(existing)
        root = link
    if error_id is None:
        error_id = uuid.uuid4().hex[:12]
        try:
            setattr(exc, _ERROR_ID_ATTR, error_id)
        except Exception:  # pragma: no cover - builtins generally allow attributes
            pass
    return error_id, root


def _error_id_for(exc: Exception) -> str:
    """Return the correlation id for ``exc`` (minting one if the chain has none)."""
    return _error_correlation(exc)[0]


def _build_error_details(
    exc: Exception, metadata: EventContext, invoke_context: InvokeContext
) -> Dict[str, Any]:
    """Build the structured ``error_details`` payload for a failed component.

    One correlated record: the failing component (the "where"), the exception's
    own type/module/cause chain (the "why"), the request identifiers, the root
    cause, and a stable ``error_id`` shared across the wrapper chain.
    """
    details = error_to_dict(exc, include_traceback=_include_traceback())
    # One pass over the cause chain yields both the correlation id and the root.
    error_id, root = _error_correlation(exc)
    details["error_id"] = error_id
    # Identify which component failed (the "where").
    details["component_id"] = metadata.id
    details["component_name"] = metadata.name
    details["component_type"] = metadata.type
    # Correlate to the request.
    details["conversation_id"] = getattr(invoke_context, "conversation_id", None)
    details["invoke_id"] = getattr(invoke_context, "invoke_id", None)
    details["assistant_request_id"] = getattr(
        invoke_context, "assistant_request_id", None
    )
    # The original failure at the bottom of the chain (the "why, ultimately").
    details["root_error_type"] = type(root).__name__
    details["root_error_message"] = error_message(root)
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


def _safe_report(message: str, *, level: str = "error") -> None:
    """Emit a log line best-effort.

    A misbehaving reporter (or an unbound runtime) must never replace the
    execution failure it is describing, so any exception from resolving the
    services or calling ``report`` is swallowed here.
    """
    try:
        current_services().error_reporter.report(message, level=level)
    except Exception:  # pragma: no cover - reporters must not raise
        pass


def _report_component_exception(
    exc: Exception,
    metadata: EventContext,
    error_details: Dict[str, Any],
) -> None:
    """Log one concise, id-bearing line for a failure -- once.

    The same failure propagates through the tool -> node -> workflow -> assistant
    decorators (re-wrapped along the way). Only the layer closest to the failure
    (the first decorator to catch it) logs; outer layers add nothing. The line
    carries the conversation/invoke/assistant_request/error ids so the full
    structured record (cause chain, traceback, component fields) can be pulled
    from the event store -- the log itself stays minimal and never dumps a
    traceback.
    """
    already_logged = _traceback_already_logged(exc)
    # Mark this exception (including re-wrapped outer ones) so the next decorator
    # layer finds the flag within one link of the chain regardless of nesting
    # depth, keeping emission to a single line.
    try:
        setattr(exc, _TRACEBACK_LOGGED_ATTR, True)
    except Exception:  # pragma: no cover - builtins generally allow attributes
        pass
    if already_logged:
        return

    component_label = metadata.type or "component"
    _safe_report(
        f"{component_label} '{metadata.name}' failed: "
        f"{type(exc).__name__}: {error_message(exc)} "
        f"[error_id={error_details.get('error_id')} "
        f"conversation_id={error_details.get('conversation_id')} "
        f"invoke_id={error_details.get('invoke_id')} "
        f"assistant_request_id={error_details.get('assistant_request_id')}]"
    )


async def _record_lifecycle_event(
    event: ComponentEvent, *, operation: str, invoke_context: InvokeContext
) -> None:
    """Persist a lifecycle event, translating a store failure into a contextual
    :class:`EventPersistenceError`.

    Used for invoke/respond events, where no execution error is active yet -- a
    failure to persist them is itself the primary failure and must surface with
    operation context rather than a raw backend exception.
    """
    try:
        await current_services().event_store.record_event(event)
    except Exception as persist_error:
        err = EventPersistenceError(
            message=f"Failed to persist {operation} event",
            invoke_context=invoke_context,
            cause=persist_error,
        )
        # Captured by serialization's _DOMAIN_FIELDS for a precise diagnostic.
        err.operation = operation  # type: ignore[attr-defined]
        raise err from persist_error


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
            self: Any,
            *args: Any,
            **kwargs: Any,
        ) -> AsyncGenerator[Union[PublishToTopicEvent, List[Message]], None]:
            # Extract metadata using component-specific logic
            metadata = config.extract_metadata(self)

            input_data: Optional[
                Union[List[ConsumeFromTopicEvent], List[Message], PublishToTopicEvent]
            ] = None

            if isinstance(args[0], InvokeContext):
                invoke_context: InvokeContext = args[0]
                input_data = args[1]
            else:
                # Assistant and workflow: args[0] is the input event (Any), which
                # carries invoke_context. Read it off args[0] directly so mypy
                # does not widen to the input_data union (which has no such attr).
                input_data = args[0]
                invoke_context = args[0].invoke_context

            # Create invoke event. The factory maps each string key to the
            # matching InvokeEvent/RespondEvent/FailedEvent subclass, so these
            # per-event kwargs (input_data/output_data/error/...) are correct at
            # runtime but unprovable to mypy through the Dict value's
            # ComponentEvent base type -- hence the targeted call-arg ignores.
            invoke_event = config.event_types["invoke"](  # type: ignore[call-arg]
                id=metadata.id,
                name=metadata.name,
                type=metadata.type,
                input_data=input_data,
                invoke_context=invoke_context,
            )
            await _record_lifecycle_event(
                invoke_event, operation="invoke", invoke_context=invoke_context
            )

            # Execute with tracing
            output_data = None
            error_details: Optional[Dict[str, Any]] = None

            try:
                with current_services().tracer.start_as_current_span(
                    f"{metadata.name}.{config.span_name_suffix}"
                ) as span:
                    try:
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
                        # Build structured details once, while the traceback is
                        # still attached to the exception, and enrich the span
                        # WHILE it is still recording. Attributes set after the
                        # span context manager exits are dropped by the backend.
                        error_details = _build_error_details(
                            e, metadata, invoke_context
                        )
                        _record_span_error(span, e, error_details)
                        raise

            except Exception as e:
                # error_details is normally built above, inside the live span.
                # Rebuild defensively only if the failure happened before the
                # inner try (e.g. span creation itself).
                if error_details is None:
                    error_details = _build_error_details(e, metadata, invoke_context)

                # Log one concise line for this failure -- once, at the layer
                # closest to it; outer layers add nothing. See
                # _report_component_exception.
                _report_component_exception(e, metadata, error_details)

                # Record failed event with both the human-readable string (kept
                # for backward compatibility) and the structured details.
                failed_event = config.event_types["failed"](  # type: ignore[call-arg]
                    id=metadata.id,
                    name=metadata.name,
                    type=metadata.type,
                    input_data=input_data,
                    invoke_context=invoke_context,
                    error=str(e),
                    error_details=error_details,
                )
                # A failure to persist the failed event must NOT replace the
                # primary execution error. Report it as a secondary diagnostic
                # (same error_id), annotate the primary, and re-raise the primary.
                try:
                    await current_services().event_store.record_event(failed_event)
                except Exception as persist_error:
                    error_id = error_details.get("error_id")
                    arid = error_details.get("assistant_request_id")
                    _safe_report(
                        "Secondary failure: failed-event NOT persisted "
                        f"(error_id={error_id} assistant_request_id={arid}); "
                        "the failure will not be queryable from the event store: "
                        f"{type(persist_error).__name__}: {persist_error}",
                        level="warning",
                    )
                    try:
                        e.add_note(  # Python 3.11+
                            f"[grafi] failed to persist failed-event "
                            f"(error_id={error_id}): {persist_error!r}"
                        )
                    except Exception:  # pragma: no cover - add_note always present
                        pass
                raise
            else:
                # Record respond event
                respond_event = config.event_types["respond"](  # type: ignore[call-arg]
                    id=metadata.id,
                    name=metadata.name,
                    type=metadata.type,
                    input_data=input_data,
                    invoke_context=invoke_context,
                    output_data=output_data,
                )
                await _record_lifecycle_event(
                    respond_event, operation="respond", invoke_context=invoke_context
                )

        return wrapper

    return decorator
