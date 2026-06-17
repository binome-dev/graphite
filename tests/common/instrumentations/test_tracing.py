"""
Unit tests for grafi.common.instrumentations.tracing module.

Tests cover all tracing backends, configuration parsing, endpoint availability,
error handling, and integration with OpenTelemetry components.
"""

import os
import socket
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from grafi.common.instrumentations.tracing import TracingOptions
from grafi.common.instrumentations.tracing import _get_otlp_config
from grafi.common.instrumentations.tracing import _setup_auto_tracing
from grafi.common.instrumentations.tracing import _setup_in_memory_tracing
from grafi.common.instrumentations.tracing import _setup_otlp_tracing
from grafi.common.instrumentations.tracing import is_local_endpoint_available
from grafi.common.instrumentations.tracing import setup_tracing


class TestTracingOptions:
    """Test TracingOptions enum values."""

    def test_enum_values(self):
        """Test that TracingOptions has all expected values."""
        assert TracingOptions.OTLP.value == "otlp"
        assert TracingOptions.AUTO.value == "auto"
        assert TracingOptions.IN_MEMORY.value == "in_memory"


class TestEndpointAvailability:
    """Test endpoint availability checking."""

    def test_is_local_endpoint_available_success(self):
        """Test successful endpoint connection."""
        with patch("socket.create_connection") as mock_connect:
            mock_connect.return_value.__enter__ = Mock()
            mock_connect.return_value.__exit__ = Mock(return_value=None)

            result = is_local_endpoint_available("localhost", 4317)

            assert result is True
            mock_connect.assert_called_once_with(("localhost", 4317), timeout=0.1)

    def test_is_local_endpoint_available_failure(self):
        """Test failed endpoint connection."""
        with patch("socket.create_connection") as mock_connect:
            mock_connect.side_effect = ConnectionRefusedError("Connection refused")

            result = is_local_endpoint_available("localhost", 4317)

            assert result is False

    def test_is_local_endpoint_available_timeout(self):
        """Test endpoint connection timeout."""
        with patch("socket.create_connection") as mock_connect:
            mock_connect.side_effect = socket.timeout("Timeout")

            result = is_local_endpoint_available("localhost", 4317)

            assert result is False


class TestConfigurationHelpers:
    """Test configuration helper functions."""

    def test_get_otlp_config_with_env_vars(self):
        """Test OTLP config retrieval with environment variables."""
        env_vars = {
            "OTEL_COLLECTOR_ENDPOINT": "collector.example.com",
            "OTEL_COLLECTOR_PORT": "9090",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            endpoint, port = _get_otlp_config("localhost", 4317)

            assert endpoint == "collector.example.com"
            assert port == 9090

    def test_get_otlp_config_with_defaults(self):
        """Test OTLP config retrieval with default values."""
        env_vars_to_unset = ["OTEL_COLLECTOR_ENDPOINT", "OTEL_COLLECTOR_PORT"]

        with patch.dict(os.environ, {}, clear=False):
            # Ensure the env vars are not set
            for var in env_vars_to_unset:
                os.environ.pop(var, None)

            endpoint, port = _get_otlp_config("localhost", 4317)

            assert endpoint == "localhost"
            assert port == 4317


class TestOTLPTracing:
    """Test OTLP tracing setup."""

    @patch("grafi.common.instrumentations.tracing.set_tracer_provider")
    @patch("grafi.common.instrumentations.tracing.OpenAIInstrumentor")
    @patch("grafi.common.instrumentations.tracing.BatchSpanProcessor")
    @patch("grafi.common.instrumentations.tracing.OTLPSpanExporter")
    @patch("grafi.common.instrumentations.tracing.TracerProvider")
    @patch("grafi.common.instrumentations.tracing.Resource")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_otlp_tracing_success(
        self,
        mock_endpoint_check,
        mock_resource,
        mock_tracer_provider_cls,
        mock_otlp_exporter,
        mock_span_processor,
        mock_openai_instrumentor,
        mock_set_tracer_provider,
    ):
        """Test successful OTLP tracing setup."""
        # Setup mocks
        mock_endpoint_check.return_value = True
        mock_resource_instance = Mock()
        mock_resource.create.return_value = mock_resource_instance
        mock_tracer_provider = Mock()
        mock_tracer_provider_cls.return_value = mock_tracer_provider
        mock_exporter = Mock()
        mock_otlp_exporter.return_value = mock_exporter
        mock_processor = Mock()
        mock_span_processor.return_value = mock_processor
        mock_instrumentor = Mock()
        mock_openai_instrumentor.return_value = mock_instrumentor

        result = _setup_otlp_tracing("localhost", 4317, "test-project")

        # Verify endpoint check
        mock_endpoint_check.assert_called_once_with("localhost", 4317)

        # Verify resource + tracer provider creation
        mock_resource.create.assert_called_once_with({"service.name": "test-project"})
        mock_tracer_provider_cls.assert_called_once_with(
            resource=mock_resource_instance
        )

        # Verify OTLP exporter setup
        mock_otlp_exporter.assert_called_once_with(
            endpoint="localhost:4317", insecure=True
        )

        # Verify span processor setup
        mock_span_processor.assert_called_once_with(mock_exporter)
        mock_tracer_provider.add_span_processor.assert_called_once_with(mock_processor)

        # Verify instrumentation
        mock_instrumentor.instrument.assert_called_once_with(
            tracer_provider=mock_tracer_provider
        )
        mock_set_tracer_provider.assert_called_once_with(mock_tracer_provider)

        assert result == mock_tracer_provider

    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_otlp_tracing_endpoint_unavailable_required(
        self, mock_endpoint_check
    ):
        """Test OTLP setup fails when endpoint unavailable and required."""
        mock_endpoint_check.return_value = False

        with pytest.raises(
            ValueError, match="OTLP endpoint localhost:4317 is not available"
        ):
            _setup_otlp_tracing(
                "localhost", 4317, "test-project", require_available=True
            )

    @patch("grafi.common.instrumentations.tracing.set_tracer_provider")
    @patch("grafi.common.instrumentations.tracing.OpenAIInstrumentor")
    @patch("grafi.common.instrumentations.tracing.BatchSpanProcessor")
    @patch("grafi.common.instrumentations.tracing.OTLPSpanExporter")
    @patch("grafi.common.instrumentations.tracing.TracerProvider")
    @patch("grafi.common.instrumentations.tracing.Resource")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_otlp_tracing_endpoint_unavailable_not_required(
        self,
        mock_endpoint_check,
        mock_resource,
        mock_tracer_provider_cls,
        mock_otlp_exporter,
        mock_span_processor,
        mock_openai_instrumentor,
        mock_set_tracer_provider,
    ):
        """Test OTLP setup continues when endpoint unavailable but not required."""
        mock_endpoint_check.return_value = False
        mock_tracer_provider = Mock()
        mock_tracer_provider_cls.return_value = mock_tracer_provider

        result = _setup_otlp_tracing(
            "localhost", 4317, "test-project", require_available=False
        )

        # Should not perform the availability check when not required
        mock_endpoint_check.assert_not_called()
        # Should still proceed with setup
        assert result == mock_tracer_provider


class TestAutoTracing:
    """Test auto tracing detection and setup."""

    @patch("grafi.common.instrumentations.tracing._setup_otlp_tracing")
    @patch("grafi.common.instrumentations.tracing._get_otlp_config")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_auto_tracing_endpoint_available(
        self, mock_endpoint_check, mock_get_otlp_config, mock_setup_otlp
    ):
        """Test auto tracing uses OTLP endpoint when available."""
        mock_get_otlp_config.return_value = ("localhost", 4317)
        mock_endpoint_check.return_value = True
        mock_tracer_provider = Mock()
        mock_setup_otlp.return_value = mock_tracer_provider

        result = _setup_auto_tracing("localhost", 4317, "test-project")

        mock_endpoint_check.assert_called_once_with("localhost", 4317)
        mock_setup_otlp.assert_called_once_with(
            "localhost", 4317, "test-project", require_available=False
        )
        assert result == mock_tracer_provider

    @patch("grafi.common.instrumentations.tracing._setup_otlp_tracing")
    @patch("grafi.common.instrumentations.tracing._setup_in_memory_tracing")
    @patch("grafi.common.instrumentations.tracing._get_otlp_config")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_auto_tracing_env_override_available(
        self,
        mock_endpoint_check,
        mock_get_otlp_config,
        mock_setup_in_memory,
        mock_setup_otlp,
    ):
        """Test auto tracing uses OTLP endpoint from environment when available."""
        mock_get_otlp_config.return_value = ("collector.example.com", 9090)
        mock_endpoint_check.return_value = True
        mock_tracer_provider = Mock()
        mock_setup_otlp.return_value = mock_tracer_provider

        result = _setup_auto_tracing("localhost", 4317, "test-project")

        mock_endpoint_check.assert_called_once_with("collector.example.com", 9090)
        mock_setup_otlp.assert_called_once_with(
            "collector.example.com", 9090, "test-project", require_available=False
        )
        mock_setup_in_memory.assert_not_called()
        assert result == mock_tracer_provider

    @patch("grafi.common.instrumentations.tracing._setup_otlp_tracing")
    @patch("grafi.common.instrumentations.tracing._setup_in_memory_tracing")
    @patch("grafi.common.instrumentations.tracing._get_otlp_config")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_auto_tracing_fallback_to_in_memory(
        self,
        mock_endpoint_check,
        mock_get_otlp_config,
        mock_setup_in_memory,
        mock_setup_otlp,
    ):
        """Test auto tracing falls back to in-memory when no endpoint available."""
        mock_get_otlp_config.return_value = ("localhost", 4317)
        mock_endpoint_check.return_value = False  # Endpoint unavailable

        result = _setup_auto_tracing("localhost", 4317, "test-project")

        mock_endpoint_check.assert_called_once_with("localhost", 4317)
        mock_setup_otlp.assert_not_called()
        mock_setup_in_memory.assert_called_once()
        assert result is None


class TestInMemoryTracing:
    """Test in-memory tracing setup."""

    @patch("grafi.common.instrumentations.tracing.InMemorySpanExporter")
    def test_setup_in_memory_tracing(self, mock_in_memory_exporter):
        """Test in-memory tracing setup."""
        mock_exporter = Mock()
        mock_in_memory_exporter.return_value = mock_exporter

        _setup_in_memory_tracing()

        mock_in_memory_exporter.assert_called_once()
        mock_exporter.shutdown.assert_called_once()


class TestMainSetupFunction:
    """Test the main setup_tracing function."""

    @patch("grafi.common.instrumentations.tracing.get_tracer")
    @patch("grafi.common.instrumentations.tracing._setup_otlp_tracing")
    @patch("grafi.common.instrumentations.tracing._get_otlp_config")
    def test_setup_tracing_otlp(
        self, mock_get_otlp_config, mock_setup_otlp, mock_get_tracer
    ):
        """Test setup_tracing with OTLP option."""
        mock_get_otlp_config.return_value = ("localhost", 4317)
        mock_tracer_provider = Mock()
        mock_setup_otlp.return_value = mock_tracer_provider
        mock_tracer = Mock()
        mock_get_tracer.return_value = mock_tracer

        result = setup_tracing(TracingOptions.OTLP, "localhost", 4317, "test-project")

        mock_setup_otlp.assert_called_once_with(
            "localhost", 4317, "test-project", require_available=True
        )
        mock_get_tracer.assert_called_once()
        assert result == mock_tracer

    @patch("grafi.common.instrumentations.tracing.get_tracer")
    @patch("grafi.common.instrumentations.tracing._setup_auto_tracing")
    def test_setup_tracing_auto(self, mock_setup_auto, mock_get_tracer):
        """Test setup_tracing with AUTO option."""
        mock_tracer_provider = Mock()
        mock_setup_auto.return_value = mock_tracer_provider
        mock_tracer = Mock()
        mock_get_tracer.return_value = mock_tracer

        result = setup_tracing(TracingOptions.AUTO, "localhost", 4317, "test-project")

        mock_setup_auto.assert_called_once_with("localhost", 4317, "test-project")
        mock_get_tracer.assert_called_once()
        assert result == mock_tracer

    @patch("grafi.common.instrumentations.tracing.get_tracer")
    @patch("grafi.common.instrumentations.tracing._setup_in_memory_tracing")
    def test_setup_tracing_in_memory(self, mock_setup_in_memory, mock_get_tracer):
        """Test setup_tracing with IN_MEMORY option."""
        mock_tracer = Mock()
        mock_get_tracer.return_value = mock_tracer

        result = setup_tracing(
            TracingOptions.IN_MEMORY, "localhost", 4317, "test-project"
        )

        mock_setup_in_memory.assert_called_once()
        mock_get_tracer.assert_called_once()
        assert result == mock_tracer

    @patch("grafi.common.instrumentations.tracing.get_tracer")
    def test_setup_tracing_invalid_option(self, mock_get_tracer):
        """Test setup_tracing with invalid option raises ValueError."""
        with pytest.raises(ValueError, match="Invalid tracing option"):
            setup_tracing("invalid_option")  # type: ignore

    @patch("grafi.common.instrumentations.tracing.get_tracer")
    @patch("grafi.common.instrumentations.tracing._setup_auto_tracing")
    def test_setup_tracing_default_parameters(self, mock_setup_auto, mock_get_tracer):
        """Test setup_tracing with default parameters."""
        mock_tracer = Mock()
        mock_get_tracer.return_value = mock_tracer

        result = setup_tracing()  # All defaults

        mock_setup_auto.assert_called_once_with("localhost", 4317, "grafi-trace")
        assert result == mock_tracer


class TestIntegration:
    """Integration tests covering multiple components."""

    @patch("grafi.common.instrumentations.tracing.socket.create_connection")
    @patch("grafi.common.instrumentations.tracing.get_tracer")
    @patch("grafi.common.instrumentations.tracing._setup_otlp_tracing")
    def test_integration_auto_detection_with_available_endpoint(
        self, mock_setup_otlp, mock_get_tracer, mock_socket_connect
    ):
        """Test full integration with auto-detection finding available endpoint."""
        # Mock successful connection
        mock_socket_connect.return_value.__enter__ = Mock()
        mock_socket_connect.return_value.__exit__ = Mock(return_value=None)

        mock_tracer_provider = Mock()
        mock_setup_otlp.return_value = mock_tracer_provider
        mock_tracer = Mock()
        mock_get_tracer.return_value = mock_tracer

        env_vars_to_unset = ["OTEL_COLLECTOR_ENDPOINT", "OTEL_COLLECTOR_PORT"]
        with patch.dict(os.environ, {}, clear=False):
            for var in env_vars_to_unset:
                os.environ.pop(var, None)

            result = setup_tracing(TracingOptions.AUTO)

        # Should detect endpoint and setup OTLP
        mock_socket_connect.assert_called_once_with(("localhost", 4317), timeout=0.1)
        mock_setup_otlp.assert_called_once_with(
            "localhost", 4317, "grafi-trace", require_available=False
        )
        assert result == mock_tracer

    @patch("grafi.common.instrumentations.tracing.socket.create_connection")
    @patch("grafi.common.instrumentations.tracing.get_tracer")
    @patch("grafi.common.instrumentations.tracing.InMemorySpanExporter")
    def test_integration_auto_detection_with_unavailable_endpoint(
        self, mock_in_memory_exporter, mock_get_tracer, mock_socket_connect
    ):
        """Test full integration with auto-detection falling back to in-memory."""
        # Mock failed connection
        mock_socket_connect.side_effect = ConnectionRefusedError("Connection refused")

        mock_exporter = Mock()
        mock_in_memory_exporter.return_value = mock_exporter
        mock_tracer = Mock()
        mock_get_tracer.return_value = mock_tracer

        env_vars_to_unset = ["OTEL_COLLECTOR_ENDPOINT", "OTEL_COLLECTOR_PORT"]
        with patch.dict(os.environ, {}, clear=False):
            # Ensure OTLP env vars are not set
            for var in env_vars_to_unset:
                os.environ.pop(var, None)

            result = setup_tracing(TracingOptions.AUTO)

        # Should fall back to in-memory
        mock_socket_connect.assert_called_once_with(("localhost", 4317), timeout=0.1)
        mock_in_memory_exporter.assert_called_once()
        mock_exporter.shutdown.assert_called_once()
        assert result == mock_tracer
