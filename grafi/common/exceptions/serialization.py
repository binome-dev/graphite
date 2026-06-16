"""Structured serialization of exceptions.

Turns an exception (and its cause chain) into a JSON-serializable dict so that
failed events, trace spans, and logs can expose the exception type, the module
it came from, the full cause chain, domain-specific component fields, and the
formatted traceback -- instead of only ``str(e)``.
"""

import traceback as traceback_module
from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional

from pydantic_core import to_jsonable_python

from grafi.common.exceptions.base import GrafiError


# Domain-specific attributes set by Grafi exception subclasses that help pinpoint
# which component failed. Captured only when present on the exception instance.
_DOMAIN_FIELDS = (
    "node_name",
    "tool_name",
    "model",
    "function_name",
    "operation",
    "topic_name",
)

# Bound the cause chain so a pathological or self-referential chain cannot loop
# forever or bloat a persisted event.
DEFAULT_MAX_CAUSE_DEPTH = 10


def error_message(exc: BaseException) -> str:
    """Return the human-readable message for an exception.

    For :class:`GrafiError` this is the raw ``message`` (without the severity and
    cause decoration that ``__str__`` adds); for any other exception it is
    ``str(exc)``.
    """
    if isinstance(exc, GrafiError):
        return exc.message
    return str(exc)


def _next_cause(exc: BaseException) -> Optional[BaseException]:
    """Return the next exception in the chain.

    Prefers :class:`GrafiError`'s explicit ``cause`` attribute, then the standard
    ``__cause__`` (set by ``raise ... from``), then the implicit ``__context__``
    unless it was suppressed.
    """
    grafi_cause = getattr(exc, "cause", None)
    if isinstance(grafi_cause, BaseException):
        return grafi_cause
    if exc.__cause__ is not None:
        return exc.__cause__
    if not exc.__suppress_context__ and exc.__context__ is not None:
        return exc.__context__
    return None


def iter_cause_chain(
    exc: BaseException, *, max_depth: int = DEFAULT_MAX_CAUSE_DEPTH
) -> Iterator[BaseException]:
    """Yield ``exc`` and each exception in its cause chain, outermost first.

    Bounded by ``max_depth`` and guarded against cycles.
    """
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and len(seen) < max_depth:
        if id(current) in seen:
            break
        seen.add(id(current))
        yield current
        current = _next_cause(current)


def _summarize(exc: BaseException) -> Dict[str, Any]:
    """Summarize a single exception (no traceback, no nested cause)."""
    details: Dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error_module": type(exc).__module__,
        "message": error_message(exc),
    }

    if isinstance(exc, GrafiError):
        details["severity"] = exc.severity
        details["timestamp"] = exc.timestamp
        if exc.invoke_context is not None:
            # invoke_context.kwargs is a free-form Dict[str, Any] whose values
            # are NOT coerced by model_dump(); force them to JSON-safe primitives
            # so the persisted failed event can always be serialized (JSONB).
            details["invoke_context"] = to_jsonable_python(
                exc.invoke_context.model_dump(), serialize_unknown=True
            )

    for field in _DOMAIN_FIELDS:
        value = getattr(exc, field, None)
        if value is not None:
            details[field] = to_jsonable_python(value, serialize_unknown=True)

    return details


def flatten_error_chain(
    exc: BaseException, *, max_depth: int = DEFAULT_MAX_CAUSE_DEPTH
) -> List[Dict[str, Any]]:
    """Flatten the cause chain into a bounded list of summaries (outermost first)."""
    return [_summarize(link) for link in iter_cause_chain(exc, max_depth=max_depth)]


def _summarize_chain(
    exc: BaseException, *, max_depth: int = DEFAULT_MAX_CAUSE_DEPTH
) -> Dict[str, Any]:
    """Summarize ``exc`` with a bounded, cycle-safe nested ``cause`` per link.

    The result is ``_summarize(exc)`` plus a ``cause`` key holding the same nested
    structure for the next exception in the chain, and so on. The deepest entry
    (root cause) is the innermost ``cause``.
    """
    root: Optional[Dict[str, Any]] = None
    parent: Optional[Dict[str, Any]] = None
    for link in iter_cause_chain(exc, max_depth=max_depth):
        summary = _summarize(link)
        if parent is None:
            root = summary
        else:
            parent["cause"] = summary
        parent = summary
    # iter_cause_chain always yields at least ``exc`` itself, so root is set.
    return root if root is not None else _summarize(exc)


def error_to_dict(
    exc: BaseException,
    *,
    include_traceback: bool = True,
    max_traceback_frames: Optional[int] = None,
    max_cause_depth: int = DEFAULT_MAX_CAUSE_DEPTH,
) -> Dict[str, Any]:
    """Serialize an exception and its cause chain into a structured dict.

    The outermost exception's fields are at the top level; the chain of underlying
    causes is exposed as a nested ``cause`` object (each link itself may carry a
    ``cause``), so the root cause is the innermost ``cause``.

    Args:
        exc: The exception to serialize.
        include_traceback: When True (and a traceback is attached), include the
            formatted, chained traceback under the ``traceback`` key.
        max_traceback_frames: Optional frame limit forwarded to the stdlib
            ``traceback`` module. Follows stdlib semantics: a positive N keeps the
            first (oldest) N frames, a negative N keeps the last (innermost) ``|N|``
            frames, ``0`` keeps none, and ``None`` (default) keeps every frame.
        max_cause_depth: Upper bound on how many links of the cause chain to walk.
    """
    details = _summarize_chain(exc, max_depth=max_cause_depth)

    if include_traceback and exc.__traceback__ is not None:
        formatted = traceback_module.format_exception(
            type(exc), exc, exc.__traceback__, limit=max_traceback_frames
        )
        details["traceback"] = "".join(formatted)

    return details
