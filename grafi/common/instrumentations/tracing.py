import os
import socket

from arize.otel import Endpoint
from arize.otel import register
from loguru import logger
from openinference.instrumentation.openai import OpenAIInstrumentor
from openinference.semconv.resource import ResourceAttributes
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer


phoenix_collector_host = os.getenv("PHOENIX_ENDPOINT", "127.0.0.1")


def is_local_endpoint_available(host: str, port: int) -> bool:
    """Check if the OTLP endpoint is available."""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except Exception as e:
        logger.debug(f"Endpoint check failed: {e}")
        return False


env = os.getenv("ENV", "local")
arize_api_key = os.getenv("ARIZE_API_KEY", "")
arize_space_id = os.getenv("ARIZE_SPACE_ID", "")
arize_project_name = os.getenv("ARIZE_PROJECT_NAME", "")


def setup_tracing() -> "Tracer":
    # only use arize if the environment is production
    if arize_api_key != "":
        collector_api_key = arize_api_key
        os.environ["PHOENIX_CLIENT_HEADERS"] = f"api_key={collector_api_key}"

        collector_endpoint = Endpoint.ARIZE

        register(
            endpoint=collector_endpoint,
            space_id=arize_space_id,  # in app space settings page
            api_key=collector_api_key,  # in app space settings page
            model_id=arize_project_name,  # name this to whatever you would like
        )

        logger.info(
            f"Arize endpoint {collector_endpoint} is available. Using OTLPSpanExporter."
        )

        OpenAIInstrumentor().instrument()
    elif is_local_endpoint_available(
        "phoenix", 4317
    ):  # check if the local collector is available
        resource = Resource.create({ResourceAttributes.PROJECT_NAME: "grafi-trace"})
        tracer_provider = TracerProvider(resource=resource)

        # Use OTLPSpanExporter if the endpoint is available
        span_exporter = OTLPSpanExporter(endpoint="phoenix:4317", insecure=True)
        logger.info("OTLP endpoint phoenix:4317 is available. Using OTLPSpanExporter.")

        # Use SimpleSpanProcessor or BatchSpanProcessor as needed
        span_processor = SimpleSpanProcessor(span_exporter)
        tracer_provider.add_span_processor(span_processor)

        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        trace.set_tracer_provider(tracer_provider)
    elif is_local_endpoint_available(
        "localhost", 4317
    ):  # check if the local collector is available
        resource = Resource.create({ResourceAttributes.PROJECT_NAME: "grafi-trace"})
        tracer_provider = TracerProvider(resource=resource)

        # Use OTLPSpanExporter if the endpoint is available
        span_exporter = OTLPSpanExporter(endpoint="localhost:4317", insecure=True)
        logger.info(
            "OTLP endpoint localhost:4317 is available. Using OTLPSpanExporter."
        )

        # Use SimpleSpanProcessor or BatchSpanProcessor as needed
        span_processor = SimpleSpanProcessor(span_exporter)
        tracer_provider.add_span_processor(span_processor)

        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        trace.set_tracer_provider(tracer_provider)
    else:
        # Fallback to InMemorySpanExporter if the endpoint is not available
        span_exporter_im = InMemorySpanExporter()
        span_exporter_im.shutdown()
        logger.debug("OTLP endpoint is not available. Using InMemorySpanExporter.")

    return trace.get_tracer(__name__)


tracer = setup_tracing()
