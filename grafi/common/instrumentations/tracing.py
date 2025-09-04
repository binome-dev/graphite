"""
OpenTelemetry tracing configuration for Grafi framework.

This module provides flexible tracing setup with support for multiple backends:
- Arize: Production monitoring and observability
- Phoenix: Local/development tracing
- Auto: Automatic detection of available endpoints
- In-Memory: Testing without external dependencies
"""

import os
import socket
from enum import Enum
from typing import Optional
from typing import Tuple

import arize.otel
import phoenix.otel
from loguru import logger
from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer
from opentelemetry.trace import get_tracer
from opentelemetry.trace import set_tracer_provider


class TracingOptions(Enum):
    """Available tracing backend options."""

    ARIZE = "arize"  # Production monitoring with Arize
    PHOENIX = "phoenix"  # Phoenix tracing (local or remote)
    AUTO = "auto"  # Auto-detect available endpoints
    IN_MEMORY = "in_memory"  # In-memory tracing for testing


def is_local_endpoint_available(host: str, port: int) -> bool:
    """
    Check if a local OTLP endpoint is reachable.

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


def _get_arize_config() -> Tuple[str, str, str]:
    """
    Retrieve Arize configuration from environment variables.

    Returns:
        Tuple of (api_key, space_id, project_name)
    """
    return (
        os.getenv("ARIZE_API_KEY", ""),
        os.getenv("ARIZE_SPACE_ID", ""),
        os.getenv("ARIZE_PROJECT_NAME", ""),
    )


def _get_phoenix_config(default_endpoint: str, default_port: int) -> Tuple[str, int]:
    """
    Retrieve Phoenix configuration from environment or use defaults.

    Args:
        default_endpoint: Default endpoint if not in environment
        default_port: Default port if not in environment

    Returns:
        Tuple of (endpoint, port)
    """
    return (
        os.getenv("PHOENIX_ENDPOINT", default_endpoint),
        int(os.getenv("PHOENIX_PORT", str(default_port))),
    )


def _setup_arize_tracing(collector_endpoint: str) -> None:
    """
    Configure Arize tracing backend.

    Args:
        collector_endpoint: The Arize collector endpoint
    """
    api_key, space_id, project_name = _get_arize_config()

    # Set Phoenix client headers for authentication
    os.environ["PHOENIX_CLIENT_HEADERS"] = f"api_key={api_key}"

    # Register with Arize
    arize.otel.register(
        endpoint=collector_endpoint,
        space_id=space_id,
        api_key=api_key,
        model_id=project_name,
        set_global_tracer_provider=False,
    )

    logger.info(f"Arize tracing configured with endpoint: {collector_endpoint}")

    # Instrument OpenAI calls
    OpenAIInstrumentor().instrument()


def _setup_phoenix_tracing(
    endpoint: str,
    port: int,
    project_name: str,
    require_available: bool = True,
) -> Optional[TracerProvider]:
    """
    Configure Phoenix tracing backend.

    Args:
        endpoint: The Phoenix collector endpoint hostname
        port: The Phoenix collector port
        project_name: The project name for tracing
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
            f"Phoenix endpoint {endpoint_url} is not available. "
            "Please ensure the collector is running or check the endpoint configuration."
        )

    # Register Phoenix tracer
    tracer_provider = phoenix.otel.register(
        endpoint=endpoint_url,
        project_name=project_name,
        set_global_tracer_provider=False,
    )

    # Configure OTLP exporter
    span_exporter = OTLPSpanExporter(endpoint=endpoint_url, insecure=True)
    span_processor = BatchSpanProcessor(span_exporter)
    tracer_provider.add_span_processor(span_processor)

    logger.info(f"Phoenix tracing configured with endpoint: {endpoint_url}")

    # Instrument OpenAI and set global tracer
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    set_tracer_provider(tracer_provider)

    return tracer_provider


def _setup_auto_tracing(
    collector_endpoint: str,
    collector_port: int,
    project_name: str,
) -> Optional[TracerProvider]:
    """
    Automatically detect and configure the best available tracing backend.

    Priority order:
    1. Default collector endpoint (if available)
    2. Phoenix endpoint from environment (if available)
    3. In-memory tracing (fallback)

    Args:
        collector_endpoint: Default collector endpoint
        collector_port: Default collector port
        project_name: Project name for tracing

    Returns:
        TracerProvider if configured, None for in-memory fallback
    """
    # Try default collector first
    logger.info(f"Trying default collector at {collector_endpoint}:{collector_port}")

    if is_local_endpoint_available(collector_endpoint, collector_port):
        return _setup_phoenix_tracing(
            collector_endpoint, collector_port, project_name, require_available=False
        )

    # Try Phoenix from environment
    phoenix_endpoint, phoenix_port = _get_phoenix_config(
        collector_endpoint, collector_port
    )

    if phoenix_endpoint and phoenix_port and phoenix_endpoint != collector_endpoint:
        if is_local_endpoint_available(phoenix_endpoint, phoenix_port):
            return _setup_phoenix_tracing(
                phoenix_endpoint, phoenix_port, project_name, require_available=False
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
    - ARIZE: Uses Arize for production monitoring
    - PHOENIX: Uses Phoenix collector (requires running instance)
    - AUTO: Auto-detects available endpoints
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

        >>> # Use Phoenix with custom endpoint
        >>> tracer = setup_tracing(
        ...     TracingOptions.PHOENIX,
        ...     collector_endpoint="tracing.example.com",
        ...     collector_port=4317
        ... )

        >>> # Use in-memory tracing for tests
        >>> tracer = setup_tracing(TracingOptions.IN_MEMORY)
    """
    if tracing_options == TracingOptions.ARIZE:
        logger.info(f"Trying Arize tracing at {collector_endpoint}:{collector_port}")
        _setup_arize_tracing(collector_endpoint)

    elif tracing_options == TracingOptions.PHOENIX:
        logger.info(f"Trying Phoenix tracing at {collector_endpoint}:{collector_port}")
        phoenix_endpoint, phoenix_port = _get_phoenix_config(
            collector_endpoint, collector_port
        )
        _setup_phoenix_tracing(
            phoenix_endpoint, phoenix_port, project_name, require_available=True
        )

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
            "Choose from: ARIZE, PHOENIX, AUTO, or IN_MEMORY."
        )

    return get_tracer(__name__)
