"""
Unit tests for grafi.common.instrumentations.tracing module.

Tests cover all tracing backends, configuration parsing, endpoint availability,
error handling, and integration with OpenTelemetry components.
"""

import os
import socket
from unittest.mock import Mock
from unittest.mock import call
from unittest.mock import patch

import pytest

from grafi.common.instrumentations.tracing import TracingOptions
from grafi.common.instrumentations.tracing import _get_arize_config
from grafi.common.instrumentations.tracing import _get_phoenix_config
from grafi.common.instrumentations.tracing import _setup_arize_tracing
from grafi.common.instrumentations.tracing import _setup_auto_tracing
from grafi.common.instrumentations.tracing import _setup_in_memory_tracing
from grafi.common.instrumentations.tracing import _setup_phoenix_tracing
from grafi.common.instrumentations.tracing import is_local_endpoint_available
from grafi.common.instrumentations.tracing import setup_tracing


class TestTracingOptions:
    """Test TracingOptions enum values."""

    def test_enum_values(self):
        """Test that TracingOptions has all expected values."""
        assert TracingOptions.ARIZE.value == "arize"
        assert TracingOptions.PHOENIX.value == "phoenix"
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

    def test_get_arize_config_with_env_vars(self):
        """Test Arize config retrieval with environment variables."""
        env_vars = {
            "ARIZE_API_KEY": "test-api-key",
            "ARIZE_SPACE_ID": "test-space-id",
            "ARIZE_PROJECT_NAME": "test-project",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            api_key, space_id, project_name = _get_arize_config()

            assert api_key == "test-api-key"
            assert space_id == "test-space-id"
            assert project_name == "test-project"

    def test_get_arize_config_without_env_vars(self):
        """Test Arize config retrieval without environment variables."""
        env_vars_to_unset = ["ARIZE_API_KEY", "ARIZE_SPACE_ID", "ARIZE_PROJECT_NAME"]

        with patch.dict(os.environ, {}, clear=False):
            # Ensure the env vars are not set
            for var in env_vars_to_unset:
                os.environ.pop(var, None)

            api_key, space_id, project_name = _get_arize_config()

            assert api_key == ""
            assert space_id == ""
            assert project_name == ""

    def test_get_phoenix_config_with_env_vars(self):
        """Test Phoenix config retrieval with environment variables."""
        env_vars = {"PHOENIX_ENDPOINT": "phoenix.example.com", "PHOENIX_PORT": "9090"}

        with patch.dict(os.environ, env_vars, clear=False):
            endpoint, port = _get_phoenix_config("localhost", 4317)

            assert endpoint == "phoenix.example.com"
            assert port == 9090

    def test_get_phoenix_config_with_defaults(self):
        """Test Phoenix config retrieval with default values."""
        env_vars_to_unset = ["PHOENIX_ENDPOINT", "PHOENIX_PORT"]

        with patch.dict(os.environ, {}, clear=False):
            # Ensure the env vars are not set
            for var in env_vars_to_unset:
                os.environ.pop(var, None)

            endpoint, port = _get_phoenix_config("localhost", 4317)

            assert endpoint == "localhost"
            assert port == 4317


class TestArizeTracing:
    """Test Arize tracing setup."""

    @patch("grafi.common.instrumentations.tracing.OpenAIInstrumentor")
    @patch("grafi.common.instrumentations.tracing.arize.otel.register")
    def test_setup_arize_tracing(self, mock_arize_register, mock_openai_instrumentor):
        """Test Arize tracing setup."""
        mock_instrumentor_instance = Mock()
        mock_openai_instrumentor.return_value = mock_instrumentor_instance

        env_vars = {
            "ARIZE_API_KEY": "test-api-key",
            "ARIZE_SPACE_ID": "test-space-id",
            "ARIZE_PROJECT_NAME": "test-project",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            _setup_arize_tracing("https://arize.example.com")

            # Check Arize registration
            mock_arize_register.assert_called_once_with(
                endpoint="https://arize.example.com",
                space_id="test-space-id",
                api_key="test-api-key",
                model_id="test-project",
                set_global_tracer_provider=False,
            )

            # Check OpenAI instrumentation
            mock_instrumentor_instance.instrument.assert_called_once()

            # Check Phoenix headers are set
            assert os.environ["PHOENIX_CLIENT_HEADERS"] == "api_key=test-api-key"


class TestPhoenixTracing:
    """Test Phoenix tracing setup."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_tracer_provider = Mock()
        self.mock_span_exporter = Mock()
        self.mock_span_processor = Mock()

    @patch("grafi.common.instrumentations.tracing.set_tracer_provider")
    @patch("grafi.common.instrumentations.tracing.OpenAIInstrumentor")
    @patch("grafi.common.instrumentations.tracing.BatchSpanProcessor")
    @patch("grafi.common.instrumentations.tracing.OTLPSpanExporter")
    @patch("grafi.common.instrumentations.tracing.phoenix.otel.register")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_phoenix_tracing_success(
        self,
        mock_endpoint_check,
        mock_phoenix_register,
        mock_otlp_exporter,
        mock_span_processor,
        mock_openai_instrumentor,
        mock_set_tracer_provider,
    ):
        """Test successful Phoenix tracing setup."""
        # Setup mocks
        mock_endpoint_check.return_value = True
        mock_tracer_provider = Mock()
        mock_phoenix_register.return_value = mock_tracer_provider
        mock_exporter = Mock()
        mock_otlp_exporter.return_value = mock_exporter
        mock_processor = Mock()
        mock_span_processor.return_value = mock_processor
        mock_instrumentor = Mock()
        mock_openai_instrumentor.return_value = mock_instrumentor

        result = _setup_phoenix_tracing("localhost", 4317, "test-project")

        # Verify endpoint check
        mock_endpoint_check.assert_called_once_with("localhost", 4317)

        # Verify Phoenix registration
        mock_phoenix_register.assert_called_once_with(
            endpoint="localhost:4317",
            project_name="test-project",
            set_global_tracer_provider=False,
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
    def test_setup_phoenix_tracing_endpoint_unavailable_required(
        self, mock_endpoint_check
    ):
        """Test Phoenix setup fails when endpoint unavailable and required."""
        mock_endpoint_check.return_value = False

        with pytest.raises(
            ValueError, match="Phoenix endpoint localhost:4317 is not available"
        ):
            _setup_phoenix_tracing(
                "localhost", 4317, "test-project", require_available=True
            )

    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_phoenix_tracing_endpoint_unavailable_not_required(
        self, mock_endpoint_check
    ):
        """Test Phoenix setup continues when endpoint unavailable but not required."""
        mock_endpoint_check.return_value = False

        with patch(
            "grafi.common.instrumentations.tracing.phoenix.otel.register"
        ) as mock_phoenix_register:
            mock_tracer_provider = Mock()
            mock_phoenix_register.return_value = mock_tracer_provider

            with (
                patch("grafi.common.instrumentations.tracing.OTLPSpanExporter"),
                patch("grafi.common.instrumentations.tracing.BatchSpanProcessor"),
                patch("grafi.common.instrumentations.tracing.OpenAIInstrumentor"),
                patch("grafi.common.instrumentations.tracing.set_tracer_provider"),
            ):
                result = _setup_phoenix_tracing(
                    "localhost", 4317, "test-project", require_available=False
                )

                # Should still proceed with setup even if endpoint check fails
                assert result == mock_tracer_provider


class TestAutoTracing:
    """Test auto tracing detection and setup."""

    @patch("grafi.common.instrumentations.tracing._setup_phoenix_tracing")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_auto_tracing_default_endpoint_available(
        self, mock_endpoint_check, mock_setup_phoenix
    ):
        """Test auto tracing uses default endpoint when available."""
        mock_endpoint_check.return_value = True
        mock_tracer_provider = Mock()
        mock_setup_phoenix.return_value = mock_tracer_provider

        result = _setup_auto_tracing("localhost", 4317, "test-project")

        mock_endpoint_check.assert_called_once_with("localhost", 4317)
        mock_setup_phoenix.assert_called_once_with(
            "localhost", 4317, "test-project", require_available=False
        )
        assert result == mock_tracer_provider

    @patch("grafi.common.instrumentations.tracing._setup_phoenix_tracing")
    @patch("grafi.common.instrumentations.tracing._setup_in_memory_tracing")
    @patch("grafi.common.instrumentations.tracing._get_phoenix_config")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_auto_tracing_phoenix_env_available(
        self,
        mock_endpoint_check,
        mock_get_phoenix_config,
        mock_setup_in_memory,
        mock_setup_phoenix,
    ):
        """Test auto tracing uses Phoenix from environment when available."""
        # Default endpoint not available, Phoenix env available
        mock_endpoint_check.side_effect = [
            False,
            True,
        ]  # First call fails, second succeeds
        mock_get_phoenix_config.return_value = ("phoenix.example.com", 9090)
        mock_tracer_provider = Mock()
        mock_setup_phoenix.return_value = mock_tracer_provider

        result = _setup_auto_tracing("localhost", 4317, "test-project")

        # Check calls in order
        assert mock_endpoint_check.call_args_list == [
            call("localhost", 4317),
            call("phoenix.example.com", 9090),
        ]
        mock_setup_phoenix.assert_called_once_with(
            "phoenix.example.com", 9090, "test-project", require_available=False
        )
        mock_setup_in_memory.assert_not_called()
        assert result == mock_tracer_provider

    @patch("grafi.common.instrumentations.tracing._setup_phoenix_tracing")
    @patch("grafi.common.instrumentations.tracing._setup_in_memory_tracing")
    @patch("grafi.common.instrumentations.tracing._get_phoenix_config")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_auto_tracing_fallback_to_in_memory(
        self,
        mock_endpoint_check,
        mock_get_phoenix_config,
        mock_setup_in_memory,
        mock_setup_phoenix,
    ):
        """Test auto tracing falls back to in-memory when no endpoints available."""
        mock_endpoint_check.return_value = False  # All endpoints unavailable
        mock_get_phoenix_config.return_value = ("phoenix.example.com", 9090)

        result = _setup_auto_tracing("localhost", 4317, "test-project")

        # Should check both endpoints
        assert mock_endpoint_check.call_args_list == [
            call("localhost", 4317),
            call("phoenix.example.com", 9090),
        ]
        mock_setup_phoenix.assert_not_called()
        mock_setup_in_memory.assert_called_once()
        assert result is None

    @patch("grafi.common.instrumentations.tracing._setup_phoenix_tracing")
    @patch("grafi.common.instrumentations.tracing._setup_in_memory_tracing")
    @patch("grafi.common.instrumentations.tracing._get_phoenix_config")
    @patch("grafi.common.instrumentations.tracing.is_local_endpoint_available")
    def test_setup_auto_tracing_same_endpoint_no_duplicate_check(
        self,
        mock_endpoint_check,
        mock_get_phoenix_config,
        mock_setup_in_memory,
        mock_setup_phoenix,
    ):
        """Test auto tracing doesn't duplicate check when Phoenix config same as default."""
        mock_endpoint_check.return_value = False
        mock_get_phoenix_config.return_value = ("localhost", 4317)  # Same as default

        result = _setup_auto_tracing("localhost", 4317, "test-project")

        # Should only check default endpoint once
        mock_endpoint_check.assert_called_once_with("localhost", 4317)
        mock_setup_phoenix.assert_not_called()
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
    @patch("grafi.common.instrumentations.tracing._setup_arize_tracing")
    def test_setup_tracing_arize(self, mock_setup_arize, mock_get_tracer):
        """Test setup_tracing with ARIZE option."""
        mock_tracer = Mock()
        mock_get_tracer.return_value = mock_tracer

        result = setup_tracing(
            TracingOptions.ARIZE, "arize.example.com", 4317, "test-project"
        )

        mock_setup_arize.assert_called_once_with("arize.example.com")
        mock_get_tracer.assert_called_once()
        assert result == mock_tracer

    @patch("grafi.common.instrumentations.tracing.get_tracer")
    @patch("grafi.common.instrumentations.tracing._setup_phoenix_tracing")
    @patch("grafi.common.instrumentations.tracing._get_phoenix_config")
    def test_setup_tracing_phoenix(
        self, mock_get_phoenix_config, mock_setup_phoenix, mock_get_tracer
    ):
        """Test setup_tracing with PHOENIX option."""
        mock_get_phoenix_config.return_value = ("localhost", 4317)
        mock_tracer_provider = Mock()
        mock_setup_phoenix.return_value = mock_tracer_provider
        mock_tracer = Mock()
        mock_get_tracer.return_value = mock_tracer

        result = setup_tracing(
            TracingOptions.PHOENIX, "localhost", 4317, "test-project"
        )

        mock_setup_phoenix.assert_called_once_with(
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
    @patch("grafi.common.instrumentations.tracing._setup_phoenix_tracing")
    def test_integration_auto_detection_with_available_endpoint(
        self, mock_setup_phoenix, mock_get_tracer, mock_socket_connect
    ):
        """Test full integration with auto-detection finding available endpoint."""
        # Mock successful connection
        mock_socket_connect.return_value.__enter__ = Mock()
        mock_socket_connect.return_value.__exit__ = Mock(return_value=None)

        mock_tracer_provider = Mock()
        mock_setup_phoenix.return_value = mock_tracer_provider
        mock_tracer = Mock()
        mock_get_tracer.return_value = mock_tracer

        result = setup_tracing(TracingOptions.AUTO)

        # Should detect endpoint and setup Phoenix
        mock_socket_connect.assert_called_once_with(("localhost", 4317), timeout=0.1)
        mock_setup_phoenix.assert_called_once_with(
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

        env_vars_to_unset = ["PHOENIX_ENDPOINT", "PHOENIX_PORT"]
        with patch.dict(os.environ, {}, clear=False):
            # Ensure Phoenix env vars are not set
            for var in env_vars_to_unset:
                os.environ.pop(var, None)

            result = setup_tracing(TracingOptions.AUTO)

        # Should fall back to in-memory
        mock_socket_connect.assert_called_once_with(("localhost", 4317), timeout=0.1)
        mock_in_memory_exporter.assert_called_once()
        mock_exporter.shutdown.assert_called_once()
        assert result == mock_tracer
