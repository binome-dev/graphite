# Assistant

The **Assistant** serves as the primary interface between users and the underlying workflow system. It processes user input, manages workflows, and coordinates interactions between users and workflow components. Assistants use language models to process input and generate responses through structured workflows.

## Architecture Overview

Assistants in Graphite follow a two-tier architecture:

1. **AssistantBase** - Abstract base class defining the core interface and properties
2. **Assistant** - Concrete implementation that handles workflow execution and message processing

## AssistantBase Class

The `AssistantBase` class provides an abstract foundation for all assistants, defining essential properties and methods that must be implemented by concrete assistant classes.

### Class Configuration

```python
from grafi.assistants.assistant_base import AssistantBase
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from typing import List, AsyncGenerator

class MyAssistant(AssistantBase):
    def _construct_workflow(self):
        # Implementation required
        pass

    def invoke(self, input_event: PublishToTopicEvent) -> List[ConsumeFromTopicEvent]:
        # Implementation required
        pass

    async def a_invoke(self, input_event: PublishToTopicEvent) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        # Implementation required
        pass
```

### AssistantBase Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `assistant_id` | `str` | `default_id` | Unique identifier for the assistant instance |
| `name` | `str` | `"Assistant"` | Human-readable name for the assistant |
| `type` | `str` | `"assistant"` | Category or type specification for the assistant |
| `oi_span_type` | `OpenInferenceSpanKindValues` | `AGENT` | OpenInference span type for distributed tracing |
| `workflow` | `Workflow` | `Workflow()` | Associated workflow instance managed by the assistant |

### Required Methods

Subclasses must implement these abstract methods:

| Method | Signature | Description |
|--------|-----------|-------------|
| `_construct_workflow` | `() -> AssistantBase` | Constructs and configures the assistant's workflow |
| `invoke` | `(PublishToTopicEvent) -> List[ConsumeFromTopicEvent]` | Synchronous event processing |
| `a_invoke` | `(PublishToTopicEvent) -> AsyncGenerator[ConsumeFromTopicEvent, None]` | Asynchronous event processing with streaming support |

### Lifecycle

The `AssistantBase` automatically calls `_construct_workflow()` during initialization via `model_post_init()`, ensuring the workflow is properly configured before the assistant is used.

## Assistant Class

The concrete `Assistant` class extends `AssistantBase` and provides a complete implementation for workflow-based message processing. It includes automatic event recording and tracing through decorators.

### Implementation Features

- **Automatic Event Recording**: Uses `@record_assistant_invoke` and `@record_assistant_a_invoke` decorators
- **Workflow Delegation**: Delegates all processing to the configured workflow
- **Manifest Generation**: Supports generating configuration manifests
- **Serialization**: Provides dictionary serialization capabilities

### Assistant Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `invoke` | `(PublishToTopicEvent) -> List[ConsumeFromTopicEvent]` | Processes input events synchronously through the workflow |
| `a_invoke` | `(PublishToTopicEvent) -> AsyncGenerator[ConsumeFromTopicEvent, None]` | Processes input events asynchronously with streaming support |
| `to_dict` | `() -> dict[str, Any]` | Serializes the assistant's workflow configuration |
| `generate_manifest` | `(output_dir: str = ".") -> str` | Generates a JSON manifest file for the assistant |

### Method Details

#### invoke()

Synchronously processes input events through the configured workflow.

```python
@record_assistant_invoke
def invoke(self, input_event: PublishToTopicEvent) -> List[ConsumeFromTopicEvent]:
    events = self.workflow.invoke(input_event)
    return events
```

**Parameters**:

- `input_event`: A `PublishToTopicEvent` containing the data to be processed and context information

**Returns**: List of `ConsumeFromTopicEvent` objects representing the workflow output

**Raises**: `ValueError` if required configuration (e.g., API keys) is missing

#### a_invoke()

Asynchronously processes input events with support for streaming responses.

```python
@record_assistant_a_invoke
async def a_invoke(self, input_event: PublishToTopicEvent) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
    async for output in self.workflow.a_invoke(input_event):
        yield output
```

**Parameters**:

- `input_event`: A `PublishToTopicEvent` containing the data to be processed and context information

**Returns**: Async generator yielding `ConsumeFromTopicEvent` objects

**Use Cases**: Streaming responses, real-time processing, concurrent operations

#### generate_manifest()

Creates a JSON manifest file containing the assistant's configuration.

```python
def generate_manifest(self, output_dir: str = ".") -> str:
    manifest_dict = self.to_dict()
    output_path = os.path.join(output_dir, f"{self.name}_manifest.json")
    # Writes JSON file
    return output_path
```

**Parameters**:

- `output_dir`: Directory for the manifest file (default: current directory)

**Returns**: Path to the generated manifest file

## AssistantBaseBuilder Class

The `AssistantBaseBuilder` provides a fluent interface for constructing assistant instances with proper configuration.

### Builder Methods

| Method | Parameters | Description |
|--------|------------|-------------|
| `oi_span_type` | `OpenInferenceSpanKindValues` | Sets the OpenInference span type for tracing |
| `name` | `str` | Sets the assistant's name |
| `type` | `str` | Sets the assistant's type category |
| `event_store` | `EventStore` | Registers an event store for event recording |

### Usage Example

```python
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.common.event_stores.in_memory_event_store import InMemoryEventStore
from openinference.semconv.trace import OpenInferenceSpanKindValues

builder = AssistantBaseBuilder(MyAssistant)
assistant = (builder
    .name("Customer Support Assistant")
    .type("support")
    .oi_span_type(OpenInferenceSpanKindValues.AGENT)
    .event_store(InMemoryEventStore())
    .build())
```
