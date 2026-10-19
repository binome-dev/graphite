"""Tests for setup_tracing: the tracer provider it sets globally, its exporter's
settings, and the OpenInference instrumentors it instruments."""

from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NoOpTracerProvider
from opentelemetry.trace import ProxyTracerProvider

from grafi.common.instrumentations import tracing


class _Exporter(InMemorySpanExporter):
    """Stands in for the OTLP exporter, remembering its settings."""

    settings: list = []

    def __init__(self, **settings) -> None:
        super().__init__()
        self.settings.append(settings)


class _Instrumentor:
    instrumented: list = []
    is_instrumented_by_opentelemetry = True

    def instrument(self, tracer_provider) -> None:
        self.instrumented.append(tracer_provider)


class _UnusableInstrumentor(_Instrumentor):
    """Like an instrumentor whose client library is not installed."""

    is_instrumented_by_opentelemetry = False


class _BrokenInstrumentor:
    def instrument(self, tracer_provider) -> None:
        raise ImportError("its client library is not installed")


def _entry_point(name: str, instrumentor: type) -> SimpleNamespace:
    return SimpleNamespace(name=name, load=lambda: instrumentor)


@pytest.fixture
def global_provider(monkeypatch) -> list:
    """The providers setup_tracing sets globally, without touching the process'
    real global, which can be set only once."""
    providers: list = []
    monkeypatch.setattr(tracing, "get_tracer_provider", ProxyTracerProvider)
    monkeypatch.setattr(tracing, "set_tracer_provider", providers.append)
    monkeypatch.setattr(tracing, "OTLPSpanExporter", _Exporter)
    monkeypatch.setattr(tracing, "entry_points", lambda group: [])
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    _Exporter.settings.clear()
    _Instrumentor.instrumented.clear()
    yield providers
    for provider in providers:
        provider.shutdown()


def test_the_provider_returned_is_set_globally(global_provider):
    provider = tracing.setup_tracing()
    assert global_provider == [provider]


def test_the_project_name_names_the_service_and_the_project(
    global_provider, monkeypatch
):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    attributes = tracing.setup_tracing(project_name="my-agent").resource.attributes
    assert attributes["service.name"] == "my-agent"
    assert attributes["openinference.project.name"] == "my-agent"


def test_a_tracer_provider_already_set_is_kept(global_provider, monkeypatch):
    existing = TracerProvider()
    monkeypatch.setattr(tracing, "get_tracer_provider", lambda: existing)
    assert tracing.setup_tracing() is existing
    assert global_provider == [] and _Exporter.settings == []


def test_a_provider_of_another_kind_already_set_is_kept(global_provider, monkeypatch):
    monkeypatch.setattr(tracing, "get_tracer_provider", NoOpTracerProvider)
    assert isinstance(tracing.setup_tracing(), TracerProvider)
    assert global_provider == [] and _Exporter.settings == []


def test_without_a_project_name_the_environment_names_the_service(
    global_provider, monkeypatch
):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    assert tracing.setup_tracing().resource.attributes["service.name"] == "from-env"


def test_the_service_is_named_grafi_by_default(global_provider):
    assert tracing.setup_tracing().resource.attributes["service.name"] == "grafi"


def test_the_endpoint_and_headers_given_reach_the_exporter(global_provider):
    tracing.setup_tracing(
        endpoint="https://otel.example.com", headers={"api_key": "secret"}
    )
    assert _Exporter.settings == [
        {"endpoint": "https://otel.example.com", "headers": {"api_key": "secret"}}
    ]


def test_without_them_the_exporter_reads_the_environment(global_provider):
    tracing.setup_tracing()
    assert _Exporter.settings == [{"endpoint": None, "headers": None}]


def test_every_installed_instrumentor_traces_through_the_provider(
    global_provider, monkeypatch
):
    monkeypatch.setattr(
        tracing,
        "entry_points",
        lambda group: [
            _entry_point("openai", _Instrumentor),
            _entry_point("anthropic", _Instrumentor),
        ],
    )
    provider = tracing.setup_tracing()
    assert _Instrumentor.instrumented == [provider, provider]


def test_an_instrumentor_that_fails_is_skipped(global_provider, monkeypatch):
    monkeypatch.setattr(
        tracing,
        "entry_points",
        lambda group: [
            _entry_point("broken", _BrokenInstrumentor),
            _entry_point("openai", _Instrumentor),
        ],
    )
    provider = tracing.setup_tracing()
    assert _Instrumentor.instrumented == [provider]


def test_auto_instrument_can_be_turned_off(global_provider, monkeypatch):
    monkeypatch.setattr(
        tracing, "entry_points", lambda group: [_entry_point("openai", _Instrumentor)]
    )
    tracing.setup_tracing(auto_instrument=False)
    assert _Instrumentor.instrumented == []


def test_only_instrumentors_that_took_are_named(global_provider, monkeypatch):
    monkeypatch.setattr(
        tracing,
        "entry_points",
        lambda group: [
            _entry_point("openai", _Instrumentor),
            _entry_point("anthropic", _UnusableInstrumentor),
        ],
    )
    assert tracing._instrument(TracerProvider()) == ["openai"]
