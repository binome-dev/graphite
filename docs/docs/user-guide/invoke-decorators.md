# Invoke Decorators

Graphite provides a comprehensive set of decorators for recording execution events, adding distributed tracing, and exposing functions to LLMs. These decorators automatically handle event logging, error tracking, and observability without requiring manual instrumentation.

## Overview

The decorators are categorized into two main types:

1. **Recording Decorators** - Automatically record events, add tracing spans, and handle errors
2. **Function Decorators** - Expose functions to LLMs with automatic schema generation

## LLM Function Decorator

### @llm_function

The `@llm_function` decorator exposes methods to Language Learning Models by automatically generating function specifications.

**Location**: `grafi.common.decorators.llm_function`

**Purpose**:

- Extracts function metadata (name, docstring, parameters, type hints)
- Constructs a `FunctionSpec` object with JSON Schema-compatible parameter descriptions
- Stores the specification as a `_function_spec` attribute on the decorated function

**Usage**:

```python
from grafi.common.decorators.llm_function import llm_function

@llm_function
def calculate_sum(x: int, y: int, precision: float = 0.1) -> float:
    """
    Calculate the sum of two numbers with optional precision.

    Args:
        x (int): The first number to add.
        y (int): The second number to add.
        precision (float, optional): Precision level. Defaults to 0.1.

    Returns:
        float: The sum of x and y.
    """
    return float(x + y)
```

**Features**:

- Automatically maps Python types to JSON Schema types
- Extracts parameter descriptions from docstrings
- Marks parameters without defaults as required
- Supports type hints for comprehensive schema generation

**Type Mapping**:

| Python Type | JSON Schema Type |
|-------------|------------------|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list` | `"array"` |
| `dict` | `"object"` |
| Other | `"string"` (default) |

## Recording Decorators

Recording decorators provide automatic event logging, distributed tracing, and error handling for different component types. They come in synchronous and asynchronous variants.

### Assistant Decorators

#### @record_assistant_invoke

**Location**: `grafi.common.decorators.record_assistant_invoke`

Records synchronous assistant invocations with event logging and tracing.

**Features**:

- Records `AssistantInvokeEvent` before execution
- Creates distributed tracing spans with OpenInference attributes
- Records `AssistantRespondEvent` on success or `AssistantFailedEvent` on error
- Captures input/output data as JSON

**Usage**:

```python
from grafi.common.decorators.record_assistant_invoke import record_assistant_invoke
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from typing import AsyncGenerator

@record_assistant_invoke
async def invoke(self, input_data: PublishToTopicEvent) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
    # Assistant implementation
    async for output in self.workflow.invoke(input_data):
        yield output
```

### Node Decorators

#### @record_node_invoke

**Location**: `grafi.common.decorators.record_node_invoke`

Records synchronous node invocations in event-driven workflows.

**Features**:

- Records `NodeInvokeEvent` with subscription and publication topic information
- Tracks subscribed topics and publish destinations
- Captures `ConsumeFromTopicEvent` input data
- Records success/failure events with comprehensive context

**Usage**:

```python
from grafi.common.decorators.record_node_invoke import record_node_invoke
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from typing import List, AsyncGenerator

@record_node_invoke
async def invoke(self, invoke_context: InvokeContext,
           node_input: List[ConsumeFromTopicEvent]) -> AsyncGenerator[PublishToTopicEvent, None]:
    # Node processing logic - execute command and yield PublishToTopicEvents
    async for response in self.command.invoke(invoke_context, node_input):
        yield PublishToTopicEvent(
            publisher_name=self.name,
            publisher_type=self.type,
            invoke_context=invoke_context,
            consumed_event_ids=[event.event_id for event in node_input],
            data=response
        )
```

### Tool Decorators

#### @record_tool_invoke

**Location**: `grafi.common.decorators.record_decorators`

Records synchronous tool invocations with event logging and tracing.

**Features**:

- Records `ToolInvokeEvent` before execution
- Creates tool-specific tracing spans
- Records `ToolRespondEvent` on success or `ToolFailedEvent` on error
- Captures tool execution context and results

**Usage**:

```python
from grafi.common.decorators.record_decorators import record_tool_invoke

@record_tool_invoke
def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
    # Tool execution logic
    return tool_results
```

### Workflow Decorators

#### @record_workflow_invoke

**Location**: `grafi.common.decorators.record_workflow_invoke`

Records synchronous workflow invocations with comprehensive event logging.

**Features**:

- Records `WorkflowInvokeEvent` before execution
- Creates workflow-level tracing spans
- Records `WorkflowRespondEvent` on success or `WorkflowFailedEvent` on error
- Tracks workflow execution context and results

**Usage**:

```python
from grafi.common.decorators.record_workflow_invoke import record_workflow_invoke
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from typing import List

@record_workflow_invoke
def invoke(self, input_data: PublishToTopicEvent) -> List[ConsumeFromTopicEvent]:
    # Workflow orchestration logic
    # Initialize workflow, execute nodes, return consumed events
    return output_events
```


## Common Features

### Event Recording

All recording decorators automatically:

- Record invocation events before execution begins
- Record success events with output data upon completion
- Record failure events with error details when exceptions occur
- Capture timing and execution context information

### Distributed Tracing

The decorators integrate with OpenInference tracing standards:

- Create spans with appropriate names (`{component_name}.invoke` or `{component_name}.run`)
- Set OpenInference span attributes for component identification
- Capture input/output data as span attributes
- Record error information in span attributes on failure

### Streaming Support

Async decorators handle streaming responses:

- Preserve async generator behavior for streaming outputs
- Aggregate streaming content for final result tracking
- Distinguish between streaming and non-streaming messages
- Maintain observability without affecting streaming performance

### Error Handling

All decorators provide comprehensive error handling:

- Capture and record exception details in events
- Add error information to tracing spans
- Re-raise exceptions to preserve original error behavior
- Maintain error context for debugging and monitoring

## Span Attributes

The decorators set standardized span attributes:

| Attribute Type | Examples |
|----------------|----------|
| **Component ID** | `assistant_id`, `node_id`, `tool_id`, `workflow_id` |
| **Component Metadata** | `name`, `type`, `model` (for assistants) |
| **Execution Context** | All fields from `InvokeContext` |
| **Data** | `input`, `output` (serialized as JSON) |
| **Topics** (Nodes) | `subscribed_topics`, `publish_to_topics` |
| **OpenInference** | `openinference.span.kind` |
| **Errors** | `error` (error message when exceptions occur) |

## Best Practices

1. **Choose the Right Decorator**: Use synchronous decorators for blocking operations and asynchronous decorators for streaming or async operations.

2. **Consistent Application**: Apply decorators consistently across similar component types for uniform observability.

3. **Function Specification**: Use `@llm_function` on methods that should be available to LLMs, ensuring comprehensive docstrings and type hints.

4. **Performance Considerations**: Recording decorators add minimal overhead but consider the impact of JSON serialization for large data structures.

5. **Error Context**: Leverage the automatic error recording for debugging and monitoring failed invocations.

6. **Streaming Behavior**: For async decorators, ensure your async generators yield complete message batches for proper aggregation.
