"""The decorator behind ``record_*_invoke``: it records a component's invoke,
respond and failed events and traces each invocation in a span."""

import asyncio
import functools
import os
import uuid
from contextlib import AbstractContextManager
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from typing import AsyncGenerator
from typing import AsyncIterator
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import cast

from openinference.semconv.trace import OpenInferenceMimeTypeValues
from openinference.semconv.trace import SpanAttributes
from opentelemetry.trace import Span
from opentelemetry.trace import Status
from opentelemetry.trace import StatusCode
from opentelemetry.trace import use_span
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic_core import to_json

from grafi.common.async_lifecycle import cancelling
from grafi.common.async_lifecycle import cleanup_on_exit
from grafi.common.async_lifecycle import close_iterator
from grafi.common.async_lifecycle import isolated
from grafi.common.async_lifecycle import unexpected_cancellation
from grafi.common.env import env_bool
from grafi.common.events.component_base import ComponentEvent
from grafi.common.events.component_base import FailedEvent
from grafi.common.events.component_base import InvokeEvent
from grafi.common.events.component_base import RespondEvent
from grafi.common.exceptions import EventPersistenceError
from grafi.common.exceptions.serialization import error_message
from grafi.common.exceptions.serialization import error_to_dict
from grafi.common.exceptions.serialization import iter_cause_chain
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.runtime.execution_services import current_services

# The id every layer of one failure (tool, node, workflow, assistant) records,
# set on the exception by the layer closest to it, which alone logs it.
_ERROR_ID_ATTR = "_grafi_error_id"
# Deep enough to reach the innermost failure however often it was re-wrapped.
_MAX_CAUSE_DEPTH = 1000
_DEFAULT_SPAN_MAX_PAYLOAD_CHARS = 10_000
_JSON = OpenInferenceMimeTypeValues.JSON.value
_TEXT = OpenInferenceMimeTypeValues.TEXT.value
_HIDE_SETTINGS = ("OPENINFERENCE_HIDE_INPUTS", "OPENINFERENCE_HIDE_OUTPUTS")

F = TypeVar("F", bound=Callable[..., AsyncIterator[Any]])


class EventContext(BaseModel):
    """What a component's events and span record about it."""

    id: str = default_id
    name: str = ""
    type: str = ""
    # A span names it as OpenInference does, so tracing backends show the kind.
    oi_span_type: str = Field(
        "", serialization_alias=SpanAttributes.OPENINFERENCE_SPAN_KIND
    )

    model_config = ConfigDict(extra="allow")


@dataclass(frozen=True)
class ComponentConfig:
    """How one kind of component is recorded."""

    invoke_event: Type[InvokeEvent]
    respond_event: Type[RespondEvent]
    failed_event: Type[FailedEvent]
    # Typed Any, so this layer need not import the component classes.
    extract_metadata: Callable[[Any], EventContext]
    # The output its respond event records, from all its stream yielded.
    process_async_result: Callable[[List[Any]], Any]
    span_name_suffix: str = "invoke"
    # An assistant or a workflow runs in its caller's task, so its event writes
    # run in a task of their own: the caller's cancellation stays the caller's.
    isolate_event_writes: bool = False


def create_async_decorator(config: ComponentConfig) -> Callable[[F], F]:
    """A decorator for a component's async generator ``invoke``.

    It records the invoke event, runs the stream in the component's span, then
    records the respond event, or, on failure, the failed event with
    structured details (logged once, by the layer closest to the failure)
    before raising the failure again.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> AsyncGenerator:
            # Resolved at the call, and bound around every step: every layer of
            # an invocation runs with the services where it was invoked,
            # wherever, and in whichever task, its stream is read.
            return recorded(current_services(), self, *args, **kwargs)

        async def recorded(
            services: ExecutionServices, self: Any, *args: Any, **kwargs: Any
        ) -> AsyncGenerator:
            record = functools.partial(
                _record_event, services, isolate=config.isolate_event_writes
            )
            metadata = config.extract_metadata(self)
            # A tool or a node takes (invoke_context, input); an assistant or a
            # workflow takes an input event, which carries the context.
            if isinstance(args[0], InvokeContext):
                invoke_context, input_data = args[0], args[1]
            else:
                input_data = args[0]
                invoke_context = input_data.invoke_context
            fields: Dict[str, Any] = dict(
                id=metadata.id,
                name=metadata.name,
                type=metadata.type,
                input_data=input_data,
                invoke_context=invoke_context,
            )
            await _record_lifecycle_event(
                record, config.invoke_event(**fields), "invoke", invoke_context
            )

            span = services.tracer.start_span(
                f"{metadata.name}.{config.span_name_suffix}"
            )
            try:
                if span.is_recording():
                    # Span attributes hold neither None nor kwargs' free-form dict.
                    span.set_attributes(
                        metadata.model_dump(by_alias=True, exclude_none=True)
                    )
                    span.set_attributes(
                        invoke_context.model_dump(exclude={"kwargs"}, exclude_none=True)
                    )
                    span.set_attribute(
                        SpanAttributes.SESSION_ID, invoke_context.conversation_id
                    )
                    _set_payload(
                        span,
                        SpanAttributes.INPUT_VALUE,
                        input_data,
                        SpanAttributes.INPUT_MIME_TYPE,
                    )

                with bind_services(services), _current(span):
                    stream = func(self, *args, **kwargs)

                async def close_stream() -> None:
                    with bind_services(services), _current(span):
                        await close_iterator(stream)

                results: List[Any] = []
                async with cleanup_on_exit(close_stream):
                    while True:
                        with bind_services(services), _current(span):
                            try:
                                result = await anext(stream)
                            except StopAsyncIteration:
                                break
                            except asyncio.CancelledError as cancelled:
                                if cancelling():
                                    raise
                                # The component's own, not its task's: a failure.
                                raise unexpected_cancellation(
                                    f"{metadata.name} was unexpectedly cancelled",
                                    cancelled,
                                )
                        yield result
                        results.append(result)
                output_data = config.process_async_result(results)
                _set_payload(
                    span,
                    SpanAttributes.OUTPUT_VALUE,
                    output_data,
                    SpanAttributes.OUTPUT_MIME_TYPE,
                )
            except Exception as error:
                # Failing to record a failure never replaces it.
                try:
                    first = _existing_error_id(error) is None
                    details = _build_error_details(error, metadata, invoke_context)
                    _record_span_error(span, error, details)
                    if first:
                        _report_failure(services, error, metadata, details)
                    failed = config.failed_event(
                        **fields, error=str(error), error_details=details
                    )
                    await record(failed)
                except Exception as unrecorded:
                    _note_unrecorded_failure(
                        services, error, invoke_context, unrecorded
                    )
                raise
            finally:
                span.end()

            await _record_lifecycle_event(
                record,
                config.respond_event(**fields, output_data=output_data),
                "respond",
                invoke_context,
            )

        return cast(F, wrapper)

    return decorator


async def _record_event(
    services: ExecutionServices, event: ComponentEvent, isolate: bool
) -> None:
    """Write ``event`` to the store; see ``ComponentConfig.isolate_event_writes``."""
    if isolate:
        await isolated(
            functools.partial(services.event_store.record_event, event),
            "Recording an event",
        )
    else:
        await services.event_store.record_event(event)


async def _record_lifecycle_event(
    record: Callable[[ComponentEvent], Any],
    event: ComponentEvent,
    operation: str,
    invoke_context: InvokeContext,
) -> None:
    """Record an invoke or respond event: failing to is itself the failure,
    raised as an EventPersistenceError naming the operation."""
    try:
        await record(event)
    except Exception as persist_error:
        error = EventPersistenceError(
            message=f"Failed to persist {operation} event",
            invoke_context=invoke_context,
            cause=persist_error,
        )
        # Captured by serialization's _DOMAIN_FIELDS for a precise diagnostic.
        error.operation = operation  # type: ignore[attr-defined]
        raise error from persist_error


def _current(span: Span) -> AbstractContextManager[Span]:
    """Make ``span`` current for one step of a component's stream, as its
    services are bound for it.

    A generator's body runs in the context of whoever iterates it, so neither
    may be set across a ``yield``: it would stay set in the reader's context
    between reads, and for good if the stream were abandoned and closed from
    another task. Exceptions are recorded on the span by the wrapper.
    """
    return use_span(
        span, end_on_exit=False, record_exception=False, set_status_on_exception=False
    )


def _set_payload(
    span: Span, key: str, value: Any, mime_type_key: Optional[str] = None
) -> None:
    """Set ``value`` on a recording span, and its mime type at
    ``mime_type_key``. OpenInference's ``OPENINFERENCE_HIDE_INPUTS`` and
    ``OPENINFERENCE_HIDE_OUTPUTS`` redact it as they do on LLM spans; the older
    ``GRAFI_SPAN_DISABLE_PAYLOADS`` leaves every payload off."""
    if not span.is_recording() or env_bool("GRAFI_SPAN_DISABLE_PAYLOADS"):
        return
    redacted = _redactions(*map(os.environ.get, _HIDE_SETTINGS)).get(key)
    if redacted is not None:
        span.set_attribute(key, redacted)
        return
    text, mime_type = _payload_text(value)
    span.set_attribute(key, text)
    if mime_type_key:
        span.set_attribute(mime_type_key, mime_type)


@functools.lru_cache(maxsize=8)
def _redactions(*settings: Optional[str]) -> Dict[str, str]:
    """The payloads OpenInference's settings hide, each with its redaction
    marker, worked out once for each value of those ``settings``."""
    # Imported only once a span records.
    from openinference.instrumentation import REDACTED_VALUE
    from openinference.instrumentation import TraceConfig

    config = TraceConfig()
    hidden = {
        SpanAttributes.INPUT_VALUE: config.hide_inputs,
        SpanAttributes.OUTPUT_VALUE: config.hide_outputs,
    }
    return {key: REDACTED_VALUE for key, hide in hidden.items() if hide}


def _payload_text(value: Any) -> Tuple[str, str]:
    """``value`` as JSON, or as text (its repr) if JSON cannot hold it, cut to
    ``GRAFI_SPAN_MAX_PAYLOAD_CHARS`` (default 10,000; 0: no limit); and its
    mime type."""
    try:
        text, mime_type = to_json(value, fallback=repr).decode(), _JSON
    except ValueError:  # Circular data, a lone surrogate, bytes not UTF-8...
        text, mime_type = repr(value), _TEXT
    try:
        limit = max(0, int(os.environ["GRAFI_SPAN_MAX_PAYLOAD_CHARS"]))
    except (KeyError, ValueError):
        limit = _DEFAULT_SPAN_MAX_PAYLOAD_CHARS
    if limit and len(text) > limit:
        text = f"{text[:limit]}...[truncated {len(text) - limit} chars]"
        mime_type = _TEXT
    return text, mime_type


def _record_span_error(span: Span, error: Exception, details: Dict[str, Any]) -> None:
    """Record ``error`` on the span, before it ends: as OpenTelemetry does, its
    exception event (with the traceback) and status; then its type, the id its
    log line and failed events share, and its details."""
    span.set_attributes(
        {"error.type": details["error_type"], "error_id": details["error_id"]}
    )
    without_traceback = {k: v for k, v in details.items() if k != "traceback"}
    _set_payload(span, "error.details", without_traceback)
    span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR, details["message"]))


def _existing_error_id(error: BaseException) -> Optional[str]:
    """The id an inner layer gave this failure, found along its cause chain."""
    for link in iter_cause_chain(error, max_depth=_MAX_CAUSE_DEPTH):
        error_id = getattr(link, _ERROR_ID_ATTR, None)
        if error_id:
            return str(error_id)
    return None


def _error_id_for(error: Exception) -> str:
    """The id every layer records for this failure: an inner layer's, or a new
    one set on ``error`` for the layers outside it."""
    error_id = _existing_error_id(error)
    if error_id is None:
        error_id = uuid.uuid4().hex[:12]
        # An exception may refuse new attributes (attrs' frozen ones do); its
        # outer layers then cannot find the id, and each records its own.
        with suppress(Exception):
            setattr(error, _ERROR_ID_ATTR, error_id)
    return error_id


def _build_error_details(
    error: Exception, metadata: EventContext, invoke_context: InvokeContext
) -> Dict[str, Any]:
    """A failed event's structured details: the error and its cause chain, the
    failing component, the request's ids, the root cause and the error id.

    Tracebacks are included unless ``GRAFI_ERROR_INCLUDE_TRACEBACK`` is falsy.
    """
    *_, root = iter_cause_chain(error, max_depth=_MAX_CAUSE_DEPTH)
    return {
        **error_to_dict(
            error,
            include_traceback=env_bool("GRAFI_ERROR_INCLUDE_TRACEBACK", default=True),
        ),
        "error_id": _error_id_for(error),
        "component_id": metadata.id,
        "component_name": metadata.name,
        "component_type": metadata.type,
        "conversation_id": invoke_context.conversation_id,
        "invoke_id": invoke_context.invoke_id,
        "assistant_request_id": invoke_context.assistant_request_id,
        "root_error_type": type(root).__name__,
        "root_error_message": error_message(root),
    }


def _report(services: ExecutionServices, message: str, level: str) -> None:
    """Report ``message``; a failing reporter never replaces the failure it
    describes."""
    try:
        services.error_reporter.report(message, level=level)
    except Exception:  # pragma: no cover - reporters must not raise
        pass


def _report_failure(
    services: ExecutionServices,
    error: Exception,
    metadata: EventContext,
    details: Dict[str, Any],
) -> None:
    """One concise line for a failure, with the ids to find its failed events
    (which hold the cause chain and traceback) in the event store."""
    _report(
        services,
        f"{metadata.type or 'component'} '{metadata.name}' failed: "
        f"{type(error).__name__}: {error_message(error)} "
        f"[error_id={details['error_id']} "
        f"conversation_id={details['conversation_id']} "
        f"invoke_id={details['invoke_id']} "
        f"assistant_request_id={details['assistant_request_id']}]",
        "error",
    )


def _note_unrecorded_failure(
    services: ExecutionServices,
    error: Exception,
    invoke_context: InvokeContext,
    unrecorded: Exception,
) -> None:
    """A failure whose failed event could not be recorded: reported, and noted
    on the failure, which is still the one raised."""
    error_id = _existing_error_id(error)
    _report(
        services,
        "Secondary failure: failed-event NOT persisted "
        f"(error_id={error_id} "
        f"assistant_request_id={invoke_context.assistant_request_id}); "
        "the failure will not be queryable from the event store: "
        f"{type(unrecorded).__name__}: {unrecorded}",
        "warning",
    )
    with suppress(Exception):  # A note never replaces the failure it is on.
        error.add_note(
            f"[grafi] failed to persist failed-event (error_id={error_id}): "
            f"{unrecorded!r}"
        )
