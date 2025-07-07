# Containers

The Graphite container system provides a thread-safe singleton-based dependency injection container for managing shared resources throughout the application. It handles the registration and lifecycle of core components like event stores and tracers.

## Overview

The container system provides:

- **Singleton Pattern**: Thread-safe singleton implementation for global access
- **Dependency Injection**: Centralized registration and retrieval of dependencies
- **Event Store Management**: Registration and default setup of event storage
- **Tracing Integration**: Registration and configuration of OpenTelemetry tracing
- **Lazy Initialization**: On-demand creation of default implementations
- **Production Safety**: Warnings for development-only components

## Core Components

### SingletonMeta

A thread-safe meta-class that implements the singleton pattern.

#### Features

- **Thread Safety**: Uses threading locks to prevent race conditions
- **Instance Management**: Maintains a dictionary of singleton instances per class
- **Memory Efficiency**: Ensures only one instance exists per class type

```python
class SingletonMeta(type):
    _instances: dict[type, object] = {}
    _lock: threading.Lock = threading.Lock()

    def __call__(cls: "SingletonMeta", *args: Any, **kwargs: Any) -> Any:
        # Ensure thread-safe singleton creation
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
```

### Container

The main dependency injection container using singleton pattern.

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `event_store` | `EventStore` | Returns registered event store or creates default |
| `tracer` | `Tracer` | Returns registered tracer or creates default |

#### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `register_event_store` | `(event_store: EventStore) -> None` | Register custom event store implementation |
| `register_tracer` | `(tracer: Tracer) -> None` | Register custom tracer implementation |

#### Global Instance

```python
container: Container = Container()
```

A pre-instantiated global container instance available throughout the application.

## Usage Examples

### Basic Container Usage

```python
from grafi.common.containers.container import container

# Access the global container instance
event_store = container.event_store
tracer = container.tracer

print(f"Event store type: {type(event_store)}")
print(f"Tracer type: {type(tracer)}")
```

### Custom Event Store Registration

```python
from grafi.common.containers.container import container
from grafi.common.event_stores.event_store_postgres import EventStorePostgres

# Create custom event store
postgres_store = EventStorePostgres(
    connection_string="postgresql://user:pass@localhost:5432/events"
)

# Register with container
container.register_event_store(postgres_store)

# Now all access will use the custom store
event_store = container.event_store
assert isinstance(event_store, EventStorePostgres)
```

### Custom Tracer Registration

```python
from grafi.common.containers.container import container
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Create custom tracer with Jaeger export
tracer_provider = TracerProvider()
jaeger_exporter = JaegerExporter(
    agent_host_name="localhost",
    agent_port=6831,
)
span_processor = BatchSpanProcessor(jaeger_exporter)
tracer_provider.add_span_processor(span_processor)

# Set as global tracer provider
trace.set_tracer_provider(tracer_provider)
custom_tracer = trace.get_tracer(__name__)

# Register with container
container.register_tracer(custom_tracer)

# Now all access will use the custom tracer
tracer = container.tracer
```

## Event Store Integration

### Default Behavior

```python
# First access creates default in-memory store
event_store = container.event_store
# Logs warning: "Using EventStoreInMemory. This is ONLY suitable for local testing..."
```

### Production Setup

```python
def setup_production_container():
    """Setup container for production environment."""
    from grafi.common.event_stores.event_store_postgres import EventStorePostgres
    import os

    # Get database connection from environment
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable required")

    # Create and register production event store
    prod_store = EventStorePostgres(connection_string=db_url)
    container.register_event_store(prod_store)

    print("Production event store registered")

# Call during application startup
setup_production_container()
```

### Event Store Validation

```python
def validate_event_store():
    """Validate that production event store is configured."""
    from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory

    event_store = container.event_store

    if isinstance(event_store, EventStoreInMemory):
        raise RuntimeError(
            "Production environment detected with in-memory event store. "
            "Please configure a persistent event store."
        )

    print(f"Using production event store: {type(event_store).__name__}")
```

## Tracing Integration

### Default Tracing Setup

```python
# First access creates default tracer with auto-configuration
tracer = container.tracer
# Uses setup_tracing with default parameters:
# - tracing_options=TracingOptions.AUTO
# - collector_endpoint="localhost"
# - collector_port=4317
# - project_name="grafi-trace"
```

### Custom Tracing Configuration

```python
def setup_custom_tracing():
    """Setup custom tracing configuration."""
    from grafi.common.instrumentations.tracing import setup_tracing, TracingOptions
    import os

    # Get tracing configuration from environment
    collector_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost")
    collector_port = int(os.getenv("OTEL_EXPORTER_OTLP_PORT", "4317"))
    service_name = os.getenv("SERVICE_NAME", "grafi-service")

    # Setup custom tracer
    custom_tracer = setup_tracing(
        tracing_options=TracingOptions.ENABLED,
        collector_endpoint=collector_endpoint,
        collector_port=collector_port,
        project_name=service_name
    )

    # Register with container
    container.register_tracer(custom_tracer)

    print(f"Custom tracing configured for {service_name}")

setup_custom_tracing()
```

### Distributed Tracing

```python
def create_span_example():
    """Example of using container tracer for distributed tracing."""
    tracer = container.tracer

    with tracer.start_as_current_span("process_user_request") as span:
        span.set_attribute("user.id", "12345")
        span.set_attribute("request.type", "get_profile")

        # Simulate processing
        process_request()

        span.set_attribute("response.status", "success")

def process_request():
    """Nested span example."""
    tracer = container.tracer

    with tracer.start_as_current_span("database_query") as span:
        span.set_attribute("db.operation", "SELECT")
        span.set_attribute("db.table", "users")

        # Database operation simulation
        result = query_database()

        span.set_attribute("db.rows_affected", len(result))
```

## Application Lifecycle Integration

### Startup Configuration

```python
class Application:
    def __init__(self):
        self.container = container

    def configure_dependencies(self):
        """Configure all application dependencies."""
        self._setup_event_store()
        self._setup_tracing()
        self._validate_configuration()

    def _setup_event_store(self):
        """Setup event store based on environment."""
        import os

        if os.getenv("ENVIRONMENT") == "production":
            from grafi.common.event_stores.event_store_postgres import EventStorePostgres

            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                raise ValueError("DATABASE_URL required in production")

            event_store = EventStorePostgres(connection_string=db_url)
            self.container.register_event_store(event_store)
        else:
            # Development - use default in-memory store
            pass

    def _setup_tracing(self):
        """Setup tracing based on environment."""
        import os
        from grafi.common.instrumentations.tracing import setup_tracing, TracingOptions

        if os.getenv("TRACING_ENABLED", "false").lower() == "true":
            tracer = setup_tracing(
                tracing_options=TracingOptions.ENABLED,
                collector_endpoint=os.getenv("OTEL_ENDPOINT", "localhost"),
                collector_port=int(os.getenv("OTEL_PORT", "4317")),
                project_name=os.getenv("SERVICE_NAME", "grafi-app")
            )
            self.container.register_tracer(tracer)

    def _validate_configuration(self):
        """Validate container configuration."""
        # Access properties to trigger initialization
        event_store = self.container.event_store
        tracer = self.container.tracer

        print(f"Event store: {type(event_store).__name__}")
        print(f"Tracer: {type(tracer).__name__}")

    def start(self):
        """Start the application."""
        self.configure_dependencies()
        print("Application started with configured dependencies")

# Usage
app = Application()
app.start()
```

### Graceful Shutdown

```python
class ApplicationManager:
    def __init__(self):
        self.container = container

    async def shutdown(self):
        """Gracefully shutdown application resources."""
        print("Shutting down application...")

        # Close event store connections
        event_store = self.container.event_store
        if hasattr(event_store, 'close'):
            await event_store.close()

        # Flush tracer spans
        tracer = self.container.tracer
        if hasattr(tracer, 'force_flush'):
            tracer.force_flush()

        print("Application shutdown complete")
```

## Testing with Containers

### Test Container Setup

```python
import pytest
from grafi.common.containers.container import Container
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory

@pytest.fixture
def test_container():
    """Create a test container with in-memory components."""
    test_container = Container()

    # Use in-memory event store for tests
    test_store = EventStoreInMemory()
    test_container.register_event_store(test_store)

    # Use no-op tracer for tests
    from opentelemetry.trace import NoOpTracer
    test_tracer = NoOpTracer()
    test_container.register_tracer(test_tracer)

    yield test_container

    # Cleanup if needed
    if hasattr(test_store, 'clear'):
        test_store.clear()

def test_event_store_integration(test_container):
    """Test event store integration."""
    event_store = test_container.event_store

    # Verify it's the test store
    assert isinstance(event_store, EventStoreInMemory)

    # Test basic operations
    from grafi.common.events.event import Event
    test_event = Event(event_id="test-123")

    event_store.record_event(test_event)
    retrieved = event_store.get_event("test-123")

    assert retrieved.event_id == "test-123"
```

### Mock Container

```python
from unittest.mock import Mock, patch

def test_with_mocked_container():
    """Test using mocked container dependencies."""
    # Create mock event store
    mock_event_store = Mock()
    mock_event_store.record_event.return_value = None
    mock_event_store.get_events.return_value = []

    # Create mock tracer
    mock_tracer = Mock()
    mock_span = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

    # Patch container properties
    with patch('grafi.common.containers.container.container.event_store', mock_event_store), \
         patch('grafi.common.containers.container.container.tracer', mock_tracer):

        # Test code using container
        from grafi.common.containers.container import container

        event_store = container.event_store
        tracer = container.tracer

        # Verify mocks are used
        assert event_store is mock_event_store
        assert tracer is mock_tracer
```

## Thread Safety

### Concurrent Access

```python
import threading
import time
from grafi.common.containers.container import container

def worker_function(worker_id: int, results: dict):
    """Worker function to test thread safety."""
    # Access container from multiple threads
    event_store = container.event_store
    tracer = container.tracer

    # Store results for verification
    results[worker_id] = {
        'event_store_id': id(event_store),
        'tracer_id': id(tracer)
    }

def test_thread_safety():
    """Test that container is thread-safe."""
    results = {}
    threads = []

    # Create multiple threads
    for i in range(10):
        thread = threading.Thread(
            target=worker_function,
            args=(i, results)
        )
        threads.append(thread)
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Verify all threads got the same instances
    event_store_ids = {r['event_store_id'] for r in results.values()}
    tracer_ids = {r['tracer_id'] for r in results.values()}

    assert len(event_store_ids) == 1, "Event store should be singleton"
    assert len(tracer_ids) == 1, "Tracer should be singleton"

    print("Thread safety test passed")

# Run the test
test_thread_safety()
```

## Best Practices

### Container Configuration

1. **Early Registration**: Register dependencies during application startup
2. **Environment-Based Setup**: Use environment variables for configuration
3. **Validation**: Validate container configuration before starting main logic
4. **Production Safety**: Never use in-memory stores in production

### Dependency Management

1. **Single Responsibility**: Keep container focused on dependency injection
2. **Lazy Loading**: Let container handle lazy initialization of defaults
3. **Type Safety**: Use proper type hints for registered dependencies
4. **Error Handling**: Handle missing dependencies gracefully

### Testing Strategies

1. **Test Containers**: Use separate container instances for tests
2. **Mock Dependencies**: Mock container dependencies for unit tests
3. **Integration Tests**: Test with real dependencies in integration tests
4. **Cleanup**: Always clean up test resources

### Performance Considerations

1. **Singleton Benefits**: Leverage singleton pattern for shared resources
2. **Thread Safety**: Container is thread-safe by design
3. **Memory Efficiency**: Single instances reduce memory overhead
4. **Initialization Cost**: Lazy initialization spreads startup cost

## Error Handling

### Common Issues

```python
def handle_container_errors():
    """Examples of handling container-related errors."""
    try:
        # This might fail if dependencies are not available
        event_store = container.event_store

    except Exception as e:
        print(f"Failed to get event store: {e}")
        # Fallback to in-memory store
        from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
        fallback_store = EventStoreInMemory()
        container.register_event_store(fallback_store)

def validate_production_setup():
    """Validate that production dependencies are properly configured."""
    import os
    from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory

    if os.getenv("ENVIRONMENT") == "production":
        event_store = container.event_store

        if isinstance(event_store, EventStoreInMemory):
            raise RuntimeError(
                "Production environment using in-memory event store. "
                "Configure persistent storage."
            )

        # Additional validation
        if not hasattr(event_store, 'connection_pool'):
            raise RuntimeError("Event store missing connection pool")
```

## Migration Guide

### From Direct Dependencies to Container

```python
# Before: Direct dependency instantiation
# event_store = EventStorePostgres(connection_string)
# tracer = setup_tracing(...)

# After: Using container
from grafi.common.containers.container import container

# Setup once during application startup
container.register_event_store(event_store)
container.register_tracer(tracer)

# Use throughout application
event_store = container.event_store
tracer = container.tracer
```

### Existing Code Integration

```python
class ExistingService:
    def __init__(self):
        # Old way - direct instantiation
        # self.event_store = EventStoreInMemory()

        # New way - use container
        from grafi.common.containers.container import container
        self.event_store = container.event_store
        self.tracer = container.tracer

    def process_data(self, data):
        # Use tracer from container
        with self.tracer.start_as_current_span("process_data") as span:
            span.set_attribute("data.size", len(data))

            # Process data
            result = self._transform_data(data)

            # Record event using container's event store
            from grafi.common.events.event import Event
            event = Event(event_id=f"processed-{result.id}")
            self.event_store.record_event(event)

            return result
```

The container system provides a robust foundation for dependency injection in Graphite applications, ensuring thread-safe access to shared resources while maintaining flexibility for different deployment environments and testing scenarios.
