"""The decorator behind ``record_*_invoke``: it records a component's invoke,
respond and failed events and traces each invocation in a span."""

import asyncio
import functools
import inspect
import os
import uuid
from contextlib import AbstractContextManager
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from typing import AsyncGenerator
from typing import Awaitable
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
from opentelemetry.trace import INVALID_SPAN
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
from grafi.runtime.deltas import Delta
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

F = TypeVar("F", bound=Callable[..., Any])
T = TypeVar("T")


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
    # The output its respond event records: what its invoke returns, or, from
    # a stream, made of all it yielded but deltas, which are never recorded.
    output_of: Callable[[Any], Any] = lambda result: result
    span_name_suffix: str = "invoke"
    # An assistant or a workflow runs in its caller's task, so its event writes
    # run in a task of their own: the caller's cancellation stays the caller's.
    isolate_event_writes: bool = False


# Set on a recorded method, to the method: a decorator stacked on it with
# functools.wraps() copies it, so the decorated method is known as this one.
_RECORDED = "__grafi_recorded__"


def is_recorded(method: Any) -> bool:
    """Whether ``method`` is recorded by a record decorator, also under
    another decorator."""
    return getattr(method, _RECORDED, None) is not None


def _records(layer: Callable[..., Any], component: Any) -> bool:
    """Whether ``layer``, a recorded method, records this call of it: it does
    unless the component's class overrides it with a method recorded alike,
    which records the call, calling it with ``super()``. A call is recorded
    once, by the most derived recorded method, with what that returns. A
    decorator stacked on it without functools.wraps() hides its mark: it
    then records, though the call may be recorded twice."""
    marks = [
        mark
        for klass in type(component).__mro__
        if (mark := getattr(vars(klass).get(layer.__name__), _RECORDED, None))
    ]
    return not any(mark is layer for mark in marks) or marks[0] is layer


def create_async_decorator(config: ComponentConfig) -> Callable[[F], F]:
    """A decorator for a component's ``invoke``: a coroutine function, or one
    returning an async generator, such as an async generator function.

    It records the invoke event, runs the invocation in the component's span,
    then records the respond event, or, on failure, the failed event with
    structured details (logged once, by the layer closest to the failure)
    before raising the failure again. The services are resolved at the call:
    every layer of an invocation runs with those where it was invoked,
    wherever, and in whichever task, a stream of it is read.
    """

    def decorator(func: F) -> F:
        if not inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            def stream(self: Any, *args: Any, **kwargs: Any) -> AsyncGenerator:
                if not _records(stream, self):
                    return func(self, *args, **kwargs)
                recording = _Recording(config, current_services(), self, args)
                start = functools.partial(func, self, *args, **kwargs)
                return _recorded_stream(recording, start)

            setattr(stream, _RECORDED, stream)
            return cast(F, stream)

        @functools.wraps(func)
        async def call(self: Any, *args: Any, **kwargs: Any) -> Any:
            if not _records(call, self):
                return await func(self, *args, **kwargs)
            recording = _Recording(config, current_services(), self, args)
            await recording.begin()
            try:
                recording.trace_input()
                result = await recording.step(func(self, *args, **kwargs))
                responded = recording.responded(result)
            except Exception as error:
                await recording.fail(error)
                raise
            finally:
                recording.end()
            await recording.respond(responded)
            return result

        setattr(call, _RECORDED, call)
        return cast(F, call)

    return decorator


async def _recorded_stream(
    recording: "_Recording", start: Callable[[], AsyncGenerator]
) -> AsyncGenerator:
    """The stream ``start()`` makes, an invocation's, recorded as one."""
    await recording.begin()
    try:
        recording.trace_input()
        stream = recording.run(start)

        async def close_stream() -> None:
            await recording.step(close_iterator(stream))

        results: List[Any] = []
        async with cleanup_on_exit(close_stream):
            while True:
                try:
                    result = await recording.step(anext(stream))
                except StopAsyncIteration:
                    break
                yield result
                if not isinstance(result, Delta):
                    results.append(result)
        responded = recording.responded(results)
    except Exception as error:
        await recording.fail(error)
        raise
    finally:
        recording.end()
    await recording.respond(responded)


class _Recording:
    """One invocation of a component, as its events and its span record it."""

    def __init__(
        self,
        config: ComponentConfig,
        services: ExecutionServices,
        component: Any,
        args: Tuple[Any, ...],
    ) -> None:
        self.config = config
        self.services = services
        self.metadata = config.extract_metadata(component)
        # A tool or a node takes (invoke_context, input); an assistant or a
        # workflow takes an input event, which carries the context.
        if isinstance(args[0], InvokeContext):
            self.invoke_context, self.input_data = args[0], args[1]
        else:
            self.input_data = args[0]
            self.invoke_context = self.input_data.invoke_context
        declared = config.invoke_event.model_fields
        self.fields: Dict[str, Any] = dict(
            id=self.metadata.id,
            name=self.metadata.name,
            type=self.metadata.type,
            input_data=self.input_data,
            invoke_context=self.invoke_context,
            # What else the events declare, such as a node's topics.
            **{
                key: value
                for key, value in (self.metadata.model_extra or {}).items()
                if key in declared
            },
        )
        self.span: Span = INVALID_SPAN
        self._ended = False

    async def begin(self) -> None:
        """Record the invoke event, then start the span."""
        await self._lifecycle(self.config.invoke_event(**self.fields), "invoke")
        self.span = self.services.tracer.start_span(
            f"{self.metadata.name}.{self.config.span_name_suffix}"
        )

    def trace_input(self) -> None:
        """Set what the span records of the component and its input."""
        span = self.span
        if not span.is_recording():
            return
        # Span attributes hold neither None nor kwargs' free-form dict.
        span.set_attributes(self.metadata.model_dump(by_alias=True, exclude_none=True))
        span.set_attributes(
            self.invoke_context.model_dump(exclude={"kwargs"}, exclude_none=True)
        )
        span.set_attribute(
            SpanAttributes.SESSION_ID, self.invoke_context.conversation_id
        )
        _set_payload(
            span,
            SpanAttributes.INPUT_VALUE,
            self.input_data,
            SpanAttributes.INPUT_MIME_TYPE,
        )

    def run(self, function: Callable[[], T]) -> T:
        """``function()``, run with the invocation's services bound and its
        span current."""
        with bind_services(self.services), _current(self.span):
            return function()

    async def step(self, awaitable: Awaitable[T]) -> T:
        """``awaitable``'s result, awaited with the invocation's services bound
        and its span current. A cancellation nobody requested is the
        component's own failure."""
        with bind_services(self.services), _current(self.span):
            try:
                return await awaitable
            except asyncio.CancelledError as cancelled:
                if cancelling():
                    raise
                raise unexpected_cancellation(
                    f"{self.metadata.name} was unexpectedly cancelled", cancelled
                )

    def responded(self, result: Any) -> RespondEvent:
        """The respond event for ``result``, its output set on the span."""
        output_data = self.config.output_of(result)
        event = self.config.respond_event(**self.fields, output_data=output_data)
        _set_payload(
            self.span,
            SpanAttributes.OUTPUT_VALUE,
            output_data,
            SpanAttributes.OUTPUT_MIME_TYPE,
        )
        return event

    def end(self) -> None:
        """End the span, once."""
        if not self._ended:
            self._ended = True
            self.span.end()

    async def respond(self, event: RespondEvent) -> None:
        """Record the respond event."""
        await self._lifecycle(event, "respond")

    async def fail(self, error: Exception) -> None:
        """Record ``error`` on the span, end it, and record the failed event.
        Failing to record a failure never replaces it."""
        try:
            try:
                first = _existing_error_id(error) is None
                details = _build_error_details(
                    error, self.metadata, self.invoke_context
                )
                _record_span_error(self.span, error, details)
            finally:
                self.end()
            if first:
                _report_failure(self.services, error, self.metadata, details)
            failed = self.config.failed_event(
                **self.fields, error=str(error), error_details=details
            )
            await self._record(failed)
        except Exception as unrecorded:
            _note_unrecorded_failure(
                self.services, error, self.invoke_context, unrecorded
            )

    async def _record(self, event: ComponentEvent) -> None:
        await _record_event(
            self.services, event, isolate=self.config.isolate_event_writes
        )

    async def _lifecycle(self, event: ComponentEvent, operation: str) -> None:
        """Record an invoke or respond event: failing to is itself the failure,
        raised as an EventPersistenceError naming the operation."""
        try:
            await self._record(event)
        except Exception as persist_error:
            error = EventPersistenceError(
                message=f"Failed to persist {operation} event",
                invoke_context=self.invoke_context,
                cause=persist_error,
            )
            # Captured by serialization's _DOMAIN_FIELDS for a precise diagnostic.
            error.operation = operation  # type: ignore[attr-defined]
            raise error from persist_error


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
