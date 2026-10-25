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
from grafi.common.decorators.record_decorators import record_assistant_invoke
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from grafi.runtime import Delta
from typing import AsyncGenerator, Union

class MyAssistant(AssistantBase):
    def _construct_workflow(self) -> "MyAssistant":
        # Implementation required: build self.workflow
        return self

    @record_assistant_invoke  # An LLM reads its history from these events.
    async def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        # Implementation required: yield the outputs, and the deltas when
        # `stream` (pass it on to the workflow).
        raise NotImplementedError
        yield
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
| `invoke` | `(PublishToTopicEvent, is_sequential=False, *, stream=False) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]` | Yields the outputs, and, with `stream=True`, the deltas its tools emit |

### Lifecycle

The `AssistantBase` automatically calls `_construct_workflow()` during initialization via `model_post_init()`, ensuring the workflow is properly configured before the assistant is used. An assistant given a workflow, as one loaded from a manifest is, keeps it instead.

So the fields an assistant only builds its workflow from are declared with a default and `exclude=True`, as `ReActAgent` declares its `model` and `api_key`: the manifest holds the workflow built from them, and a saved copy of them would be ignored on load.

```python
class MyAssistant(Assistant):
    # What it builds its workflow from. Not saved: a manifest holds the
    # workflow, which loading keeps (see AssistantBase).
    api_key: Optional[str] = env_secret("OPENAI_API_KEY", exclude=True)
    model: str = Field(default="gpt-4o-mini", exclude=True)
    function_tool: Optional[FunctionCallTool] = Field(default=None, exclude=True)
```

It gives its tools the key as `.api_key(self.secret_reference("api_key"))`, as
`ReActAgent` does: `{"env": "VAR"}` while the key is unset or that variable's
value, so each tool reads and saves the variable the key was read from, a
tenant's one given in code as `{"env": "VAR"}` included, where the key's value
itself could not be saved, and never falls back to another account's.

## Assistant Class

The concrete `Assistant` class extends `AssistantBase` and provides a complete implementation for workflow-based message processing. It includes automatic event recording and tracing through decorators.

### Implementation Features

- **Automatic Event Recording**: Uses `@record_assistant_invoke` decorator
- **Workflow Delegation**: Delegates all processing to the configured workflow
- **Manifests**: Saves the assistant, with its workflow and its own saved fields, as a manifest, and loads it back with that workflow (see [Manifests](manifests.md))

### Assistant Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `invoke` | `(PublishToTopicEvent, is_sequential=False, *, stream=False) -> AsyncGenerator[...]` | Yields the workflow's outputs as their steps are stored, and, with `stream=True`, each `Delta` its tools emit |
| `to_manifest` | `() -> dict[str, Any]` | The assistant's manifest: `{"apiVersion": "grafi/v2", "kind": "Assistant", "spec": ...}` |
| `generate_manifest` | `(output_dir: str \| PathLike = ".") -> Path` | Writes the manifest to `<name>_manifest.json` in `output_dir`, made if need be, and returns its `pathlib.Path` |
| `from_manifest` | `classmethod (manifest: dict \| str \| bytes \| PathLike, *, allow_env=(), legacy_classes=None, context=None) -> Assistant` | Loads an assistant from a manifest: a dict (an envelope, or the assistant's JSON), JSON as a `str` or `bytes` (a `str` is never a path), or the file a `pathlib.Path` names; `allow_env` names the variables its secrets may read besides their own |

### Method Details

#### invoke()

Runs the workflow on the input and yields its outputs as their steps are stored.

```python
@record_assistant_invoke
async def invoke(self, input_data, is_sequential=False, *, stream=False):
    async with owned_iterator(
        self.workflow.invoke(input_data, is_sequential, stream=stream)
    ) as outputs:
        async for output in outputs:
            yield output
```

**Parameters**:

- `input_data`: A `PublishToTopicEvent` containing the data to be processed and context information
- `is_sequential`: Run one step at a time
- `stream`: Also yield each `Delta` the tools emit, such as an LLM's tokens, as they emit it

**Returns**: Async generator yielding `ConsumeFromTopicEvent` objects, and, with `stream=True`, `Delta` objects between them. The return type follows `stream`: without it, only output events.

```python
from grafi.runtime import Delta

async for item in assistant.invoke(input_event, stream=True):
    if isinstance(item, Delta):
        print(item.content, end="", flush=True)
    else:
        answer = item.data[-1].content
```

See [Runtime](runtime.md#streaming) for what deltas are, and are not.

An `invoke` of your own, on an `Assistant` or an `EventDrivenWorkflow`
subclass, takes `stream` and passes it on. Declare the two overloads above it,
as `Assistant` does, so a type checker still knows a call without `stream`
yields only output events:

```python
from typing import AsyncGenerator, Literal, Union, overload

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.runtime import Delta


class LoggedAssistant(Assistant):
    @overload
    def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: Literal[False] = False,
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]: ...

    @overload
    def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]: ...

    async def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        print(f"Invoked with {len(input_data.data)} messages")
        async for output in super().invoke(input_data, is_sequential, stream=stream):
            yield output
```

#### generate_manifest() and from_manifest()

`generate_manifest()` writes the assistant's manifest, `to_manifest()`, as JSON
to `<name>_manifest.json` in `output_dir` (default: the current directory),
making the directory if need be, and returns the file's path, a
`pathlib.Path`. It writes the file whole: beside it, then moved over it.
`Assistant.from_manifest()` loads it back, as the assistant class it names,
with the workflow it holds; given a `str`, it reads it as JSON, never as a
path:

```python
from grafi.assistants.assistant import Assistant
from grafi.common.import_ref import trust_modules

path = assistant.generate_manifest("manifests")  # A pathlib.Path.

trust_modules("my_app")  # The modules defining your assistant, tools and functions.
assistant = Assistant.from_manifest(path)
```

A manifest holds no secret: an API key is saved as the name of the environment
variable it is read from. See [Manifests](manifests.md).

## AssistantBaseBuilder Class

The `AssistantBaseBuilder` provides a fluent interface for constructing assistant instances with proper configuration.

### Builder Methods

| Method | Parameters | Description |
|--------|------------|-------------|
| `oi_span_type` | `OpenInferenceSpanKindValues` | Sets the OpenInference span type for tracing |
| `name` | `str` | Sets the assistant's name |
| `type` | `str` | Sets the assistant's type category |

### Usage Example

```python
from grafi.assistants.assistant_base import AssistantBaseBuilder
from openinference.semconv.trace import OpenInferenceSpanKindValues

builder = AssistantBaseBuilder(MyAssistant)
assistant = (builder
    .name("Customer Support Assistant")
    .type("support")
    .oi_span_type(OpenInferenceSpanKindValues.AGENT)
    .build())

# The event store and tracer are set at startup, not on the assistant:
#   set_default_services(ExecutionServices(event_store=...))
#   async for event in assistant.invoke(input_data): ...
```
