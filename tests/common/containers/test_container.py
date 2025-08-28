"""Tests for the Container (EventStore and Tracer container)."""

import pytest
from unittest.mock import Mock, patch
import threading

from grafi.common.containers.container import Container, SingletonMeta
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.event_stores.event_store import EventStore


@pytest.fixture(autouse=True)
def reset_container():
    """Reset the container singleton before each test."""
    # Clear the singleton instances
    SingletonMeta._instances.clear()
    yield
    # Clean up after test
    SingletonMeta._instances.clear()


class TestContainerSingleton:
    """Test Container singleton behavior."""
    
    def test_singleton_behavior(self):
        """Test that Container is a singleton."""
        container1 = Container()
        container2 = Container()
        assert container1 is container2
    
    def test_thread_safe_singleton(self):
        """Test that singleton creation is thread-safe."""
        instances = []
        
        def create_container():
            instances.append(Container())
        
        # Create multiple containers in parallel threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=create_container)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All instances should be the same
        first_instance = instances[0]
        assert all(instance is first_instance for instance in instances)


class TestEventStoreManagement:
    """Test event store registration and access."""
    
    def test_default_event_store(self):
        """Test that container provides default event store."""
        container = Container()
        
        # Should return default EventStoreInMemory
        event_store = container.event_store
        assert isinstance(event_store, EventStoreInMemory)
    
    def test_register_custom_event_store(self):
        """Test registering a custom event store.""" 
        container = Container()
        mock_store = Mock(spec=EventStore)
        
        container.register_event_store(mock_store)
        
        assert container.event_store is mock_store
    
    def test_event_store_caching(self):
        """Test that event store is cached after first access."""
        container = Container()
        
        # Access event store twice
        store1 = container.event_store
        store2 = container.event_store
        
        # Should be the same instance
        assert store1 is store2
    
    @patch('grafi.common.containers.container.logger')
    def test_in_memory_store_warning(self, mock_logger):
        """Test warning when using in-memory event store."""
        container = Container()
        
        # Access default event store
        container.event_store
        
        # Should log warning about in-memory store
        mock_logger.warning.assert_called_with(
            "Using EventStoreInMemory. This is ONLY suitable for local testing but not for production."
        )
    
    @patch('grafi.common.containers.container.logger')
    def test_register_in_memory_store_warning(self, mock_logger):
        """Test warning when registering in-memory event store."""
        container = Container()
        in_memory_store = EventStoreInMemory()
        
        container.register_event_store(in_memory_store)
        
        # Should log warning about in-memory store
        mock_logger.warning.assert_called_with(
            "Using EventStoreInMemory. This is ONLY suitable for local testing but not for production."
        )


class TestTracerManagement:
    """Test tracer registration and access."""
    
    @patch('grafi.common.containers.container.setup_tracing')
    def test_default_tracer(self, mock_setup_tracing):
        """Test that container provides default tracer."""
        from grafi.common.instrumentations.tracing import TracingOptions
        
        mock_tracer = Mock()
        mock_setup_tracing.return_value = mock_tracer
        
        container = Container()
        tracer = container.tracer
        
        # Should call setup_tracing with default options
        mock_setup_tracing.assert_called_once_with(
            tracing_options=TracingOptions.AUTO,
            collector_endpoint="localhost", 
            collector_port=4317,
            project_name="grafi-trace"
        )
        assert tracer is mock_tracer
    
    def test_register_custom_tracer(self):
        """Test registering a custom tracer."""
        container = Container()
        mock_tracer = Mock()
        
        container.register_tracer(mock_tracer)
        
        assert container.tracer is mock_tracer
    
    def test_tracer_caching(self):
        """Test that tracer is cached after first access."""
        container = Container()
        mock_tracer = Mock()
        container.register_tracer(mock_tracer)
        
        # Access tracer twice
        tracer1 = container.tracer
        tracer2 = container.tracer
        
        # Should be the same instance
        assert tracer1 is tracer2


class TestContainerIntegration:
    """Integration tests for container functionality."""
    
    def test_container_initialization(self):
        """Test container proper initialization."""
        container = Container()
        
        # Should have proper initial state
        assert container._event_store is None
        assert container._tracer is None
    
    def test_multiple_containers_share_state(self):
        """Test that multiple container instances share state."""
        container1 = Container()
        container2 = Container()
        
        # Register event store in one container
        mock_store = Mock(spec=EventStore)
        container1.register_event_store(mock_store)
        
        # Should be accessible from other container (singleton)
        assert container2.event_store is mock_store
    
    def test_container_properties_independent_lifecycle(self):
        """Test that event store and tracer can be set independently."""
        container = Container()
        
        # Set only event store
        mock_store = Mock(spec=EventStore)
        container.register_event_store(mock_store)
        
        # Event store should be set, tracer should use default
        assert container.event_store is mock_store
        # Tracer access will create default tracer
        with patch('grafi.common.containers.container.setup_tracing') as mock_setup:
            mock_tracer = Mock()
            mock_setup.return_value = mock_tracer
            assert container.tracer is mock_tracer
    
    def test_global_container_instance(self):
        """Test the global container instance."""
        from grafi.common.containers.container import container as global_container
        
        # Should be a Container instance
        assert isinstance(global_container, Container)
        
        # Note: The global container is created at module import time,
        # so it might not be the same instance as a new Container()
        # due to our test fixture that clears singleton instances.
        # But they should both be Container instances
        new_container = Container()
        assert isinstance(new_container, Container)