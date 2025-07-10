import os
import socket
from enum import Enum

import arize.otel
import phoenix.otel
from loguru import logger
from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer
from opentelemetry.trace import get_tracer
from opentelemetry.trace import set_tracer_provider


class TracingOptions(Enum):
    ARIZE = "arize"
    PHOENIX = "phoenix"
    AUTO = "auto"  # Default to auto-detecting
    IN_MEMORY = "in_memory"  # use in-memory span


def is_local_endpoint_available(host: str, port: int) -> bool:
    """Check if the OTLP endpoint is available."""
    try:
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except Exception as e:
        logger.debug(f"Endpoint check failed: {e}")
        return False


def setup_tracing(
    tracing_options: TracingOptions = TracingOptions.AUTO,
    collector_endpoint: str = "localhost",
    collector_port: int = 4317,
    project_name: str = "grafi-trace",
) -> "Tracer":
    # only use arize if the environment is production
    if tracing_options == TracingOptions.ARIZE:
        arize_api_key = os.getenv("ARIZE_API_KEY", "")
        arize_space_id = os.getenv("ARIZE_SPACE_ID", "")
        arize_project_name = os.getenv("ARIZE_PROJECT_NAME", "")
        collector_api_key = arize_api_key
        os.environ["PHOENIX_CLIENT_HEADERS"] = f"api_key={collector_api_key}"

        collector_endpoint = collector_endpoint  # Endpoint.ARIZE

        arize.otel.register(
            endpoint=collector_endpoint,
            space_id=arize_space_id,  # in app space settings page
            api_key=collector_api_key,  # in app space settings page
            model_id=arize_project_name,  # name this to whatever you would like
            set_global_tracer_provider=False,
        )

        logger.info(
            f"Arize endpoint {collector_endpoint} is available. Using OTLPSpanExporter."
        )

        OpenAIInstrumentor().instrument()
    elif tracing_options == TracingOptions.PHOENIX:
        # check if the local collector is available
        collector_endpoint_url = f"{collector_endpoint}:{collector_port}"
        if not is_local_endpoint_available(collector_endpoint, collector_port):
            raise ValueError(
                f"OTLP endpoint {collector_endpoint} is not available. "
                "Please ensure the collector is running or check the endpoint configuration."
            )

        tracer_provider = phoenix.otel.register(
            endpoint=collector_endpoint_url,
            project_name=project_name,
            set_global_tracer_provider=False,
        )

        # Use OTLPSpanExporter if the endpoint is available
        span_exporter = OTLPSpanExporter(endpoint=collector_endpoint_url, insecure=True)
        logger.info(
            f"OTLP endpoint {collector_endpoint_url} is available. Using OTLPSpanExporter."
        )

        # Use SimpleSpanProcessor or BatchSpanProcessor as needed
        span_processor = SimpleSpanProcessor(span_exporter)
        tracer_provider.add_span_processor(span_processor)

        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        set_tracer_provider(tracer_provider)
    elif tracing_options == TracingOptions.AUTO:
        collector_endpoint_url = f"{collector_endpoint}:{collector_port}"
        if is_local_endpoint_available(collector_endpoint, collector_port):
            tracer_provider = phoenix.otel.register(
                endpoint=collector_endpoint_url,
                project_name=project_name,
                set_global_tracer_provider=False,
            )

            # Use OTLPSpanExporter if the endpoint is available
            span_exporter = OTLPSpanExporter(
                endpoint=collector_endpoint_url, insecure=True
            )
            logger.info(
                f"OTLP endpoint {collector_endpoint_url} is available. Using OTLPSpanExporter."
            )

            # Use SimpleSpanProcessor or BatchSpanProcessor as needed
            span_processor = SimpleSpanProcessor(span_exporter)
            tracer_provider.add_span_processor(span_processor)

            OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
            set_tracer_provider(tracer_provider)
        else:
            # Fallback to InMemorySpanExporter if the endpoint is not available
            span_exporter_im = InMemorySpanExporter()
            span_exporter_im.shutdown()
            logger.debug("OTLP endpoint is not available. Using InMemorySpanExporter.")
    elif tracing_options == TracingOptions.IN_MEMORY:
        # Fallback to InMemorySpanExporter if the endpoint is not available
        span_exporter_im = InMemorySpanExporter()
        span_exporter_im.shutdown()
        logger.debug("Using InMemorySpanExporter.")

    else:
        raise ValueError(
            f"Invalid tracing option: {tracing_options}. "
            "Choose from ARIZE, PHOENIX, AUTO, or IN_MEMORY."
        )

    return get_tracer(__name__)
