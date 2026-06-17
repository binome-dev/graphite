# OpenTelemetry Tracing Guide

This document provides guidance on integrating Graphite with any OpenTelemetry
(OTLP) compatible backend for distributed tracing and observability.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Tracing Options](#tracing-options)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

Graphite emits traces through OpenTelemetry and exports them to a generic OTLP
collector. This works with any OpenTelemetry-compatible backend (e.g. the
OpenTelemetry Collector, Jaeger, Tempo, or any vendor that accepts OTLP).

Graphite supports the following modes:

- **OTLP**: Export spans to an OTLP collector (gRPC)
- **Auto**: Automatic detection of an available OTLP endpoint
- **In-Memory**: Testing mode without external dependencies

[OpenInference](https://github.com/Arize-ai/openinference) is used to
automatically instrument LLM calls, regardless of which OTLP collector the
spans are exported to. The integration automatically captures:

- OpenAI API calls
- LLM interactions
- Tool executions
- Workflow orchestration
- Node operations

## Installation

### Core Dependencies

Grafi includes the following observability dependencies by default:

```toml
dependencies = [
    "openinference-instrumentation-openai>=0.1.41",
    "opentelemetry-sdk>=1.39.1",
    "opentelemetry-exporter-otlp-proto-grpc>=1.39.1",
]
```

These are automatically installed when you install Grafi:

```bash
# Using pip
pip install grafi

# Using uv
uv pip install grafi
```

## Configuration

### Docker Compose

You can run a local OpenTelemetry Collector (or any OTLP-compatible backend)
via docker compose. For example, using an OTLP collector that exposes the
default gRPC port `4317`:

```yaml
version: '3.8'

services:
  otel-collector:
    image: otel/opentelemetry-collector:latest
    command: ["--config=/etc/otel-collector-config.yaml"]
    volumes:
      - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml
    ports:
      - "4317:4317" # OTLP gRPC
```

### Environment Variables

Set these environment variables to override the default OTLP collector settings:

```bash
# Optional - defaults to localhost:4317
export OTEL_COLLECTOR_ENDPOINT="localhost" # collector hostname
export OTEL_COLLECTOR_PORT="4317"          # collector gRPC port
```

These are also read by the default `Container` tracer, so simply setting them is
enough for the auto-configured tracer to find your collector.

### Setup Function Parameters

The `setup_tracing()` function accepts the following parameters:

```python
def setup_tracing(
    tracing_options: TracingOptions = TracingOptions.AUTO,
    collector_endpoint: str = "localhost",
    collector_port: int = 4317,
    project_name: str = "grafi-trace",
) -> Tracer:
```

- **tracing_options**: Backend to use (OTLP, AUTO, IN_MEMORY)
- **collector_endpoint**: Hostname of the collector (default: "localhost")
- **collector_port**: Port number of the collector (default: 4317)
- **project_name**: Name for the tracing project; exported as the `service.name`
  resource attribute (default: "grafi-trace")

## Tracing Options

Grafi provides three tracing modes through the `TracingOptions` enum:

### 1. OTLP - Generic OpenTelemetry Collector

Export spans to any OTLP-compatible collector:

```python
from grafi.common.instrumentations.tracing import TracingOptions, setup_tracing

tracer = setup_tracing(
    tracing_options=TracingOptions.OTLP,
    collector_endpoint="localhost",
    collector_port=4317,
    project_name="my-project",
)
```

**When to use:**
- Production and development deployments
- Any backend that accepts OTLP (OpenTelemetry Collector, Jaeger, Tempo, etc.)
- A running collector instance is required

### 2. AUTO - Automatic Detection

Let Grafi automatically detect an available OTLP endpoint:

```python
from grafi.common.instrumentations.tracing import TracingOptions, setup_tracing

tracer = setup_tracing(
    tracing_options=TracingOptions.AUTO,
    collector_endpoint="localhost",
    collector_port=4317,
)
```

**Detection priority:**
1. OTLP endpoint (from arguments or `OTEL_COLLECTOR_*` env vars), if available
2. Falls back to in-memory tracing

**When to use:**
- Development environments with an optional collector
- CI/CD pipelines
- Flexible deployment scenarios

### 3. IN_MEMORY - Testing

Use in-memory tracing for tests and offline work:

```python
tracer = setup_tracing(tracing_options=TracingOptions.IN_MEMORY)
```

**When to use:**
- Unit and integration tests
- CI/CD without external dependencies
- Offline development
- Minimal overhead scenarios

## Usage Examples

### Example 1: Basic Setup with AUTO Detection

```python
from grafi.common.containers.container import container
from grafi.common.instrumentations.tracing import TracingOptions, setup_tracing

# Register the tracer with auto-detection
tracer = setup_tracing(tracing_options=TracingOptions.AUTO)
container.register_tracer(tracer)

# Your assistant code here
```

### Example 2: Export to an OTLP Collector

```python
from grafi.common.containers.container import container
from grafi.common.instrumentations.tracing import TracingOptions, setup_tracing

tracer = setup_tracing(
    tracing_options=TracingOptions.OTLP,
    collector_endpoint="localhost",
    collector_port=4317,
    project_name="my-assistant",
)
container.register_tracer(tracer)

# Your assistant code here
```

### Example 3: Testing with In-Memory Tracing

```python
from grafi.common.containers.container import container
from grafi.common.instrumentations.tracing import TracingOptions, setup_tracing

# Use in-memory tracing for tests
tracer = setup_tracing(tracing_options=TracingOptions.IN_MEMORY)
container.register_tracer(tracer)

# Your test code here
```

### Example 4: Complete Assistant with Tracing

```python
import os
import uuid
import asyncio
from grafi.common.containers.container import container
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.instrumentations.tracing import TracingOptions, setup_tracing
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.assistants.assistant_base import AssistantBase

# Setup tracing
tracer = setup_tracing(tracing_options=TracingOptions.AUTO)
container.register_tracer(tracer)

# Get event store
event_store = container.event_store

# Create your assistant
async def main():
    assistant = (
        # YourAssistant is an instance of type grafi.assistants.assistant
        # https://github.com/binome-dev/graphite/blob/main/grafi/assistants/assistant.py
        YourAssistant.builder()
        .name("MyAssistant")
        .api_key(os.getenv("OPENAI_API_KEY"))
        .build()
    )

    # Create invoke context
    invoke_context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )

    # Invoke assistant
    input_data = PublishToTopicEvent(
        invoke_context=invoke_context,
        data=[Message(content="Hello!", role="user")]
    )

    output = await async_func_wrapper(
        assistant.invoke(input_data, is_sequential=True)
    )
    print(output)

asyncio.run(main())
```

## Best Practices

### 1. Environment-Specific Configuration

Use different tracing modes for different environments:

```python
import os
from grafi.common.instrumentations.tracing import TracingOptions, setup_tracing

env = os.getenv("ENVIRONMENT", "development")

if env in ("production", "staging"):
    tracing_option = TracingOptions.OTLP
    endpoint = os.getenv("OTEL_COLLECTOR_ENDPOINT", "localhost")
elif env == "development":
    tracing_option = TracingOptions.AUTO
    endpoint = "localhost"
else:  # testing
    tracing_option = TracingOptions.IN_MEMORY
    endpoint = "localhost"

tracer = setup_tracing(
    tracing_options=tracing_option,
    collector_endpoint=endpoint,
    project_name=f"{env}-assistant",
)
```

### 2. Early Initialization

Set up tracing early in your application lifecycle, before creating assistants:

```python
# Good: Setup tracing first
tracer = setup_tracing(tracing_options=TracingOptions.AUTO)
container.register_tracer(tracer)

# Then create assistants
assistant = MyAssistant.builder().build()
```

### 3. Project Naming Conventions

Use descriptive project names to organize traces. The project name is exported
as the `service.name` resource attribute:

```python
tracer = setup_tracing(
    tracing_options=TracingOptions.OTLP,
    project_name=f"{app_name}-{environment}-{version}",
)
```

### 4. Graceful Degradation with AUTO Mode

Use AUTO mode to gracefully degrade when the collector is unavailable:

```python
# Will automatically fall back to in-memory if no endpoint available
tracer = setup_tracing(tracing_options=TracingOptions.AUTO)
```

### 5. Testing Isolation

Use IN_MEMORY mode in tests to avoid external dependencies:

```python
import pytest
from grafi.common.instrumentations.tracing import TracingOptions, setup_tracing

@pytest.fixture(autouse=True)
def setup_test_tracing():
    tracer = setup_tracing(tracing_options=TracingOptions.IN_MEMORY)
    container.register_tracer(tracer)
    yield
    # Cleanup if needed
```

## Troubleshooting

### Issue: "OTLP endpoint is not available"

**Symptom**: ValueError when using the OTLP tracing option

**Solution**:

1. Ensure your collector is running:
   ```bash
   ➜ docker compose up
    nc -zv localhost 4317

    Connection to localhost (::1) 4317 port [tcp/*] succeeded!
   ```

2. Check the endpoint and port are correct:
   ```python
   tracer = setup_tracing(
       tracing_options=TracingOptions.OTLP,
       collector_endpoint="localhost",
       collector_port=4317,
   )
   ```

3. Use AUTO mode for graceful fallback:
   ```python
   tracer = setup_tracing(tracing_options=TracingOptions.AUTO)
   ```

### Issue: Connection timeout with the collector

**Symptom**: Slow startup or timeout errors

**Solution**:
1. The endpoint check has a 0.1s timeout, which is normal
2. Use AUTO mode to automatically fall back:
   ```python
   tracer = setup_tracing(tracing_options=TracingOptions.AUTO)
   ```
3. For OTLP mode, ensure the endpoint is reachable:
   ```bash
   nc -zv localhost 4317
   ```

### Issue: OpenAI instrumentation not working

**Symptom**: OpenAI calls not showing in traces

**Solution**:
1. Ensure OpenAI is instrumented (done automatically by `setup_tracing`)
2. Verify the tracer is registered before creating assistants:
   ```python
   container.register_tracer(tracer)  # Must be before assistant creation
   ```

### Issue: Traces showing in wrong project

**Symptom**: Traces appear in an unexpected project / service name

**Solution**:
Specify the project name explicitly:
```python
tracer = setup_tracing(
    tracing_options=TracingOptions.OTLP,
    project_name="my-specific-project",
)
```

### Debug Logging

Enable debug logging to troubleshoot tracing issues:

```python
from loguru import logger
import sys

logger.remove()
logger.add(sys.stderr, level="DEBUG")

# Now setup tracing
tracer = setup_tracing(tracing_options=TracingOptions.AUTO)
```

## Additional Resources

### OpenTelemetry Resources
- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- [OpenTelemetry Python SDK](https://opentelemetry-python.readthedocs.io/)

### OpenInference Resources
- [OpenInference Specification](https://github.com/Arize-ai/openinference)

### Grafi Resources
- [Graphite Documentation](https://binome-dev.github.io/graphite)
- [Event-Driven Workflows](https://binome-dev.github.io/graphite/user-guide/event-driven-workflow/)
- [Graphite GitHub Repository](https://github.com/binome-dev/graphite)

## Support

For issues related to:

- **Graphite tracing integration**: Open an issue on the Grafi repository
- **OpenTelemetry**: Consult the OpenTelemetry documentation
