"""Grafi execution runtime: explicit, request-scoped dependency injection.

Application startup constructs an :class:`ExecutionServices` and a
:class:`GrafiRuntime`, then invokes assistants through ``runtime.invoke(...)``.
The runtime binds the services to a request-scoped ``ContextVar``; components
resolve them via :func:`current_services` without any change to ``invoke``
signatures.
"""

from grafi.runtime.execution_services import ErrorReporter
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.runtime.execution_services import current_services
from grafi.runtime.runtime import GrafiRuntime

__all__ = [
    "ExecutionServices",
    "ErrorReporter",
    "GrafiRuntime",
    "current_services",
    "bind_services",
]
