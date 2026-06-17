"""
OpenTelemetry tracing configuration for Grafi framework.

This module provides flexible tracing setup using a generic OpenTelemetry
(OTLP) endpoint:
- OTLP: Export spans to any OpenTelemetry-compatible collector
- Auto: Automatic detection of an available OTLP endpoint
- In-Memory: Testing without external dependencies

OpenInference is used to automatically instrument OpenAI calls, regardless of
which OTLP collector the spans are exported to.
"""

import os
import socket
from enum import Enum
from typing import Optional
from typing import Tuple

from loguru import logger
from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer
from opentelemetry.trace import get_tracer
from opentelemetry.trace import set_tracer_provider


class TracingOptions(Enum):
    """Available tracing backend options."""

    OTLP = "otlp"  # Export to a generic OpenTelemetry (OTLP) collector
    AUTO = "auto"  # Auto-detect an available OTLP endpoint
    IN_MEMORY = "in_memory"  # In-memory tracing for testing


def is_local_endpoint_available(host: str, port: int) -> bool:
    """
    Check if an OTLP endpoint is reachable.

    Args:
        host: The hostname or IP address
        port: The port number

    Returns:
        True if the endpoint is reachable, False otherwise
    """
    try:
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except Exception as e:
        logger.debug(f"Endpoint check failed for {host}:{port} - {e}")
        return False


def _get_otlp_config(default_endpoint: str, default_port: int) -> Tuple[str, int]:
    """
    Retrieve OTLP collector configuration from environment or use defaults.

    Args:
        default_endpoint: Default endpoint if not in environment
        default_port: Default port if not in environment

    Returns:
        Tuple of (endpoint, port)
    """
    return (
        os.getenv("OTEL_COLLECTOR_ENDPOINT", default_endpoint),
        int(os.getenv("OTEL_COLLECTOR_PORT", str(default_port))),
    )


def _setup_otlp_tracing(
    endpoint: str,
    port: int,
    project_name: str,
    require_available: bool = True,
) -> Optional[TracerProvider]:
    """
    Configure tracing against a generic OTLP collector.

    Args:
        endpoint: The OTLP collector endpoint hostname
        port: The OTLP collector port
        project_name: The project (service) name for tracing
        require_available: If True, raise error when endpoint is unavailable

    Returns:
        TracerProvider if successfully configured, None otherwise

    Raises:
        ValueError: If require_available=True and endpoint is not available
    """
    endpoint_url = f"{endpoint}:{port}"

    # Check endpoint availability if required
    if require_available and not is_local_endpoint_available(endpoint, port):
        raise ValueError(
            f"OTLP endpoint {endpoint_url} is not available. "
            "Please ensure the collector is running or check the endpoint configuration."
        )

    # Build a tracer provider tagged with the project/service name
    resource = Resource.create({"service.name": project_name})
    tracer_provider = TracerProvider(resource=resource)

    # Configure OTLP exporter
    span_exporter = OTLPSpanExporter(endpoint=endpoint_url, insecure=True)
    span_processor = BatchSpanProcessor(span_exporter)
    tracer_provider.add_span_processor(span_processor)

    logger.info(f"OTLP tracing configured with endpoint: {endpoint_url}")

    # Instrument OpenAI (via OpenInference) and set global tracer
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    set_tracer_provider(tracer_provider)

    return tracer_provider


def _setup_auto_tracing(
    collector_endpoint: str,
    collector_port: int,
    project_name: str,
) -> Optional[TracerProvider]:
    """
    Automatically detect and configure tracing against an OTLP collector.

    Priority order:
    1. OTLP endpoint (if available)
    2. In-memory tracing (fallback)

    Args:
        collector_endpoint: Default collector endpoint
        collector_port: Default collector port
        project_name: Project name for tracing

    Returns:
        TracerProvider if configured, None for in-memory fallback
    """
    endpoint, port = _get_otlp_config(collector_endpoint, collector_port)

    logger.info(f"Trying OTLP collector at {endpoint}:{port}")

    if is_local_endpoint_available(endpoint, port):
        return _setup_otlp_tracing(
            endpoint, port, project_name, require_available=False
        )

    # Fallback to in-memory
    _setup_in_memory_tracing()
    return None


def _setup_in_memory_tracing() -> None:
    """Configure in-memory tracing for testing or offline use."""
    span_exporter = InMemorySpanExporter()
    span_exporter.shutdown()
    logger.debug("Using in-memory tracing (no external endpoint available)")


def setup_tracing(
    tracing_options: TracingOptions = TracingOptions.AUTO,
    collector_endpoint: str = "localhost",
    collector_port: int = 4317,
    project_name: str = "grafi-trace",
) -> Tracer:
    """
    Set up distributed tracing with the specified backend.

    This function configures OpenTelemetry tracing based on the selected option:
    - OTLP: Exports to a generic OTLP collector (requires running instance)
    - AUTO: Auto-detects an available OTLP endpoint
    - IN_MEMORY: Uses in-memory storage (for testing)

    Args:
        tracing_options: The tracing backend to use
        collector_endpoint: Default collector endpoint hostname
        collector_port: Default collector port number
        project_name: Name for the tracing project

    Returns:
        Configured OpenTelemetry Tracer instance

    Raises:
        ValueError: If tracing option is invalid or required endpoint is unavailable

    Examples:
        >>> # Auto-detect available tracing backend
        >>> tracer = setup_tracing()

        >>> # Use a generic OTLP collector with a custom endpoint
        >>> tracer = setup_tracing(
        ...     TracingOptions.OTLP,
        ...     collector_endpoint="tracing.example.com",
        ...     collector_port=4317
        ... )

        >>> # Use in-memory tracing for tests
        >>> tracer = setup_tracing(TracingOptions.IN_MEMORY)
    """
    if tracing_options == TracingOptions.OTLP:
        logger.info(f"Trying OTLP tracing at {collector_endpoint}:{collector_port}")
        endpoint, port = _get_otlp_config(collector_endpoint, collector_port)
        _setup_otlp_tracing(endpoint, port, project_name, require_available=True)

    elif tracing_options == TracingOptions.AUTO:
        logger.info(
            f"Trying auto-detection for tracing at {collector_endpoint}:{collector_port}"
        )
        _setup_auto_tracing(collector_endpoint, collector_port, project_name)

    elif tracing_options == TracingOptions.IN_MEMORY:
        logger.info("Trying in-memory tracing")
        _setup_in_memory_tracing()

    else:
        raise ValueError(
            f"Invalid tracing option: {tracing_options}. "
            "Choose from: OTLP, AUTO, or IN_MEMORY."
        )

    return get_tracer(__name__)
