"""Tracing: export spans to an OpenTelemetry (OTLP) collector.

Grafi's components trace themselves through OpenTelemetry's global tracer, with
attributes named as OpenInference names them; so do the LLM clients of every
installed OpenInference instrumentor (``openinference-instrumentation-openai``,
``-anthropic``, ...). ``setup_tracing`` sends all their spans to one collector.
"""

import os
from importlib.metadata import entry_points
from typing import Dict
from typing import List
from typing import Optional

from loguru import logger
from openinference.semconv.resource import ResourceAttributes
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import ProxyTracerProvider
from opentelemetry.trace import get_tracer_provider
from opentelemetry.trace import set_tracer_provider


def setup_tracing(
    project_name: Optional[str] = None,
    endpoint: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    auto_instrument: bool = True,
) -> TracerProvider:
    """Export spans in batches to an OTLP collector over gRPC, through a tracer
    provider set as the global one, and return that provider.

    Each argument not given follows OpenTelemetry's standard environment:
    ``project_name``, the spans' ``service.name`` and OpenInference project,
    comes from ``OTEL_SERVICE_NAME``, else is "grafi"; ``endpoint`` from
    ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` or ``OTEL_EXPORTER_OTLP_ENDPOINT``,
    else is ``http://localhost:4317`` (``https://`` uses TLS); ``headers``,
    such as an API key, from ``OTEL_EXPORTER_OTLP_HEADERS``.

    With ``auto_instrument``, every installed OpenInference instrumentor traces
    its client too. Spans still unexported are flushed when the process exits.
    A tracer provider already set, by an earlier call or the application, is
    kept, as OpenTelemetry allows one: it is returned, or, if it is not the
    SDK's, an idle provider is.

    Example:
        >>> setup_tracing(project_name="my-agent")
    """
    current = get_tracer_provider()
    if not isinstance(current, ProxyTracerProvider):
        logger.warning("Tracing: a tracer provider is already set, so it is kept")
        return current if isinstance(current, TracerProvider) else TracerProvider()
    name = project_name or os.environ.get("OTEL_SERVICE_NAME") or "grafi"
    resource = Resource.create(
        {SERVICE_NAME: name, ResourceAttributes.PROJECT_NAME: name}
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    set_tracer_provider(provider)
    instrumented = _instrument(provider) if auto_instrument else []
    logger.info(
        f"Tracing: exporting the spans of '{name}' over OTLP; "
        f"instrumented: {', '.join(instrumented) or 'none'}"
    )
    return provider


def _instrument(provider: TracerProvider) -> List[str]:
    """Instrument every installed OpenInference instrumentor, and name those
    that took. One that fails is skipped: tracing must never stop the
    application."""
    instrumented = []
    for entry_point in entry_points(group="openinference_instrumentor"):
        try:
            instrumentor = entry_point.load()()
            instrumentor.instrument(tracer_provider=provider)
        except Exception as error:
            logger.warning(f"Tracing: cannot instrument {entry_point.name}: {error}")
            continue
        # False when its client library is not installed.
        if getattr(instrumentor, "is_instrumented_by_opentelemetry", False):
            instrumented.append(entry_point.name)
    return instrumented
