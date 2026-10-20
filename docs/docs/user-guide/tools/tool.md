# Tool (Base Class)

The `Tool` class is the fundamental base class for all tools in the Graphite framework. It defines the core interface and common functionality that all tools must implement, providing a unified approach to tool development, execution, and integration within event-driven workflows. This abstract base class ensures consistency across different tool types while enabling powerful extensibility.

## Fields

| Field          | Type                          | Description                                                                                      |
|----------------|-------------------------------|--------------------------------------------------------------------------------------------------|
| `tool_id`      | `str`                         | Unique identifier for the tool instance (automatically generated using `default_id`).          |
| `name`         | `Optional[str]`               | Human-readable name for the tool (defaults to `None`).                                          |
| `type`         | `Optional[str]`               | Type identifier for the tool, typically the class name (defaults to `None`).                   |
| `oi_span_type` | `OpenInferenceSpanKindValues` | Semantic attribute for observability tracing (required field for OpenInference integration).   |

## Methods

| Method       | Signature                                                                  | Description                                                                                    |
|--------------|----------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| `invoke`   | `async (invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen` | Asynchronous method to process input data and yield its output in batches of messages; the node publishes each batch as one event. |
| `model_dump(mode="json")` | `() -> Dict[str, Any]`                                        | Saves the tool as data: its fields, and its class by import path, as `"class"`. See [Manifests](../manifests.md). |
| `model_validate` | `classmethod (data: Dict[str, Any]) -> Tool`                          | Loads a tool from that data, as the class it names, which must be this class or a subclass of it. |

## Builder Pattern

The `Tool` class uses the `ToolBuilder` base class that provides common builder methods:

| Builder Method   | Signature                                                    | Description                                                    |
|------------------|--------------------------------------------------------------|----------------------------------------------------------------|
| `name`          | `(name: str) -> Self`                                       | Sets the human-readable name for the tool.                    |
| `type`          | `(type_name: str) -> Self`                                  | Sets the type identifier for the tool.                        |
| `oi_span_type`  | `(oi_span_type: OpenInferenceSpanKindValues) -> Self`      | Sets the OpenInference span type for observability.           |

## Core Concepts

### Tool Identification

Every tool instance has a unique identifier and optional metadata:

```python
# Automatic ID generation
tool = SomeTool()
print(tool.tool_id)  # Automatically generated unique ID

# Manual configuration via builder
tool = (
    SomeTool.builder()
    .name("My Custom Tool")
    .type("CustomTool")
    .build()
)
```

### Execution Pattern

Tools use asynchronous execution patterns:

#### Asynchronous Execution

```python
# Asynchronous processing with generator
async for message_batch in tool.invoke(invoke_context, input_messages):
    process_messages(message_batch)
```

### Message Conversion

A tool yields `Message` objects. To turn a value into messages the way `FunctionTool` does (messages as they are, `None` as none, anything else as one message holding it as text, JSON unless a string), use `grafi.tools.results.as_messages`:

```python
from grafi.tools.results import as_messages

yield as_messages(result)
```

### Streaming

A tool that produces its output piece by piece, such as an LLM's tokens, can send the pieces to a caller streaming the run with `emit_delta`, then yield the whole output. The pieces are never published or stored; `streaming()` says whether anyone receives them (see [Runtime](../runtime.md#streaming)):

```python
from grafi.runtime import emit_delta

async def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen:
    text = []
    async for token in self.client.stream(input_data):
        emit_delta(token)
        text.append(token)
    yield [Message(role="assistant", content="".join(text))]
```

Plain functions need no subclass: `FunctionTool` and `FunctionCallTool` take a function, sync or async, that returns its result or, as a generator, streams it.

## Implementation Requirements

When creating a concrete tool implementation, you must:

### 1. Inherit from Tool

```python
from grafi.tools.tool import Tool

class MyCustomTool(Tool):
    # Tool-specific fields
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
```

### 2. Implement Core Methods

```python
async def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen:
    """Asynchronous processing implementation."""
    # Process input_data asynchronously
    result = await self.async_process_data(input_data)
    yield [Message(role="assistant", content=result)]
```

### 3. Create Builder Class

```python
from grafi.tools.tool import ToolBuilder

class MyCustomToolBuilder(ToolBuilder[MyCustomTool]):
    """Builder for MyCustomTool instances."""

    def custom_parameter(self, value: str) -> Self:
        self.kwargs["custom_parameter"] = value
        return self
```

### 4. Add Builder Factory Method

```python
@classmethod
def builder(cls) -> "MyCustomToolBuilder":
    """Return a builder for MyCustomTool."""
    return MyCustomToolBuilder(cls)
```

## Complete Implementation Example

Here's a complete example of a custom tool implementation:

```python
from typing import Self
from pydantic import Field
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.tools.tool import Tool, ToolBuilder
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message, Messages, MsgsAGen

class TextProcessorTool(Tool):
    """A tool for processing text data."""

    name: str = Field(default="TextProcessorTool")
    type: str = Field(default="TextProcessorTool")
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    # Tool-specific configuration
    operation: str = Field(default="uppercase")
    prefix: str = Field(default="")

    @classmethod
    def builder(cls) -> "TextProcessorToolBuilder":
        return TextProcessorToolBuilder(cls)

    async def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen:
        """Process text asynchronously."""
        if not input_data:
            yield []
            return

        content = input_data[0].content or ""
        processed = self._process_text(content)
        yield self.to_messages(processed)

    def _process_text(self, text: str) -> str:
        """Internal text processing logic."""
        if self.operation == "uppercase":
            result = text.upper()
        elif self.operation == "lowercase":
            result = text.lower()
        else:
            result = text

        return f"{self.prefix}{result}"

    def to_messages(self, response: str) -> Messages:
        """Convert processed text to Messages."""
        return [Message(role="assistant", content=response)]

class TextProcessorToolBuilder(ToolBuilder[TextProcessorTool]):
    """Builder for TextProcessorTool instances."""

    def operation(self, operation: str) -> Self:
        self.kwargs["operation"] = operation
        return self

    def prefix(self, prefix: str) -> Self:
        self.kwargs["prefix"] = prefix
        return self

# Usage example
text_tool = (
    TextProcessorTool.builder()
    .name("Text Processor")
    .operation("uppercase")
    .prefix("PROCESSED: ")
    .build()
)
```

### Saving and Loading

A tool is saved as data, with its fields and its class, and needs no code of
its own for it:

```python
from grafi.common.import_ref import trust_modules

data = text_tool.model_dump(mode="json")
# {"class": "my_app.tools:TextProcessorTool", "tool_id": "...",
#  "name": "Text Processor", "operation": "uppercase", "prefix": "PROCESSED: ", ...}

trust_modules("my_app")  # Loading imports classes from trusted modules only.
restored = Tool.model_validate(data)  # A TextProcessorTool.
```

A field holding something that is not data, such as a client or an index, is
left out with `Field(exclude=True)`, and a secret is declared with
`env_secret("VAR")`. See [Manifests](../manifests.md).

## OpenInference Integration

All tools integrate with OpenInference for observability and tracing:

### Span Types

Common span types used by different tool categories:

```python
from openinference.semconv.trace import OpenInferenceSpanKindValues

# General tools
oi_span_type = OpenInferenceSpanKindValues.TOOL

# Language model tools
oi_span_type = OpenInferenceSpanKindValues.LLM

# Retrieval tools
oi_span_type = OpenInferenceSpanKindValues.RETRIEVER

# Embedding tools
oi_span_type = OpenInferenceSpanKindValues.EMBEDDING
```

### Tracing Configuration

```python
class MyTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
```

## Tool Categories

Graphite provides several categories of tools that extend the base Tool class:

### LLM Tools

- **OpenAITool**: Integration with OpenAI's language models
- **OllamaTool**: Integration with local Ollama deployments
- **Base LLM class**: Abstract base for language model tools

### Function Tools

- **FunctionTool**: Wrapper for custom Python functions
- **FunctionCallTool**: Enables LLM function calling capabilities

### Specialized Tools

- **Assistant Tools**: High-level AI assistant implementations
- **Retrieval Tools**: Document and information retrieval
- **Workflow Tools**: Orchestration and flow control

## Configuration and Pydantic Integration

Tools are built on Pydantic BaseModel, providing:

### Type Safety

```python
class MyTool(Tool):
    # Pydantic field validation
    max_tokens: int = Field(gt=0, le=4000, default=1000)
    temperature: float = Field(ge=0.0, le=2.0, default=0.7)
```

### Configuration

```python
class MyTool(Tool):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,  # Allow complex types
        validate_assignment=True,      # Validate on assignment
        extra="forbid"                 # Strict field validation
    )
```

## Error Handling Best Practices

### Async Error Handling

Raise a `ToolInvocationError` subclass caused by the error: the tool's and the
node's failed events record it, and the run fails with it. An error an LLM
should see and recover from is a function call's, answered by
[FunctionCallTool](function-call.md) (see its `on_error`).

```python
from grafi.common.exceptions import FunctionToolException
from grafi.tools.results import as_messages

async def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen:
    try:
        result = await self.async_process(input_data)
    except Exception as e:
        raise FunctionToolException(
            tool_name=self.name,
            message=f"Processing failed: {e}",
            invoke_context=invoke_context,
            cause=e,
        ) from e
    yield as_messages(result)
```

## Testing Tools

### Unit Testing

```python
import pytest
from grafi.common.models.message import Message
from grafi.common.models.invoke_context import InvokeContext

@pytest.mark.asyncio
async def test_tool_invoke():
    tool = MyCustomTool()
    context = InvokeContext()
    input_messages = [Message(role="user", content="test input")]

    results = []
    async for batch in tool.invoke(context, input_messages):
        results.extend(batch)

    assert len(results) > 0
```

## Integration with Graphite

### Command Pattern

Tools integrate with Graphite's command system:

```python
from grafi.tools.command import Command, use_command

class MyCommand(Command):
    ...  # How the node prepares the tool's input; see Command.

@use_command(MyCommand)
class MyTool(Tool):
    # Tool implementation
    pass
```

### Event-Driven Workflows

Tools participate in event-driven workflows through:

- **InvokeContext**: Carries workflow context and metadata
- **Message passing**: Standardized communication via Messages
- **Async generators**: A tool yields its output in batches, each one event, and can stream pieces of it to a caller with `emit_delta`

## Best Practices

### Design Principles

1. **Single Responsibility**: Each tool should have a clear, focused purpose
2. **Immutability**: Prefer immutable configurations where possible
3. **Error Resilience**: Handle errors gracefully and provide meaningful feedback
4. **Observable**: Use proper OpenInference span types for tracing

### Performance Considerations

1. **Async Support**: Implement both sync and async methods for flexibility
2. **Resource Management**: Clean up resources in finally blocks or context managers
3. **Batching**: Process multiple messages efficiently when possible
4. **Caching**: Cache expensive operations when appropriate

### Documentation

1. **Clear Docstrings**: Document purpose, parameters, and return values
2. **Type Hints**: Use comprehensive type annotations
3. **Examples**: Provide usage examples in docstrings
4. **Error Cases**: Document expected exceptions and error conditions

By following the Tool base class pattern, you can create powerful, consistent, and observable tools that integrate seamlessly with Graphite's event-driven architecture while maintaining clean separation of concerns and excellent developer experience.
