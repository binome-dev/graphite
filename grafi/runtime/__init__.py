"""The services invocations run with: the event store, the tracer and the error
reporter; and the deltas they stream.

Every invocation runs with the process default services, which
:func:`set_default_services` sets once at startup (in-process ones until then),
unless :func:`bind_services` or a :class:`GrafiRuntime` gives it others.
Components read them through :func:`current_services`. A caller streaming an
invocation receives each :class:`Delta` its tools emit, as they emit it.
"""

from grafi.runtime.deltas import Delta
from grafi.runtime.deltas import deltas_for
from grafi.runtime.deltas import deltas_to
from grafi.runtime.deltas import emit_delta
from grafi.runtime.deltas import streaming
from grafi.runtime.execution_services import ErrorReporter
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.runtime.execution_services import current_services
from grafi.runtime.execution_services import set_default_services
from grafi.runtime.runtime import GrafiRuntime

__all__ = [
    "Delta",
    "ExecutionServices",
    "ErrorReporter",
    "GrafiRuntime",
    "bind_services",
    "current_services",
    "deltas_for",
    "deltas_to",
    "emit_delta",
    "set_default_services",
    "streaming",
]
