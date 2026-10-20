# FunctionTool

The **FunctionTool** class is a `Tool` that runs a plain Python function on the messages its node consumed. The function is written like any other: sync or async, it returns the tool's output, or, as a generator, it streams it.

## Fields

| Field          | Type                          | Description                                                                           |
|----------------|-------------------------------|---------------------------------------------------------------------------------------|
| `name`         | `str`                         | Human-readable name identifying the function tool (defaults to `"FunctionTool"`).    |
| `type`         | `str`                         | Specifies the type of the tool (set to `"FunctionTool"`).                           |
| `role`         | `str`                         | The role of the message a result becomes (defaults to `"assistant"`).               |
| `function`     | `CallableRef`                 | The function: it takes the messages and returns, or streams, the tool's output. Saved by import path, so it is a module-level function (or a `CallableComponent`). |
| `oi_span_type` | `OpenInferenceSpanKindValues` | Semantic attribute from OpenInference used for tracing (set to `TOOL`).             |

## Methods

| Method              | Signature                                                           | Description                                                                                         |
|---------------------|---------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `builder()`         | `classmethod -> FunctionToolBuilder`                               | Returns a builder instance for constructing FunctionTool objects.                                  |
| `invoke`          | `async (invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen` | Runs the function and yields its output, one batch of messages per result. A failure raises `FunctionToolException`, with the original error as its cause. |
| `model_dump(mode="json")` | `() -> dict[str, Any]`                                        | Saves the tool as data, its function as `{"ref": "module:qualname"}`; a lambda or a nested function cannot be saved. See [Manifests](../manifests.md). |

## Usage and Customization

### The function

The function takes the consumed messages:

```python
def your_function(messages: Messages) -> Any
```

It may be sync or async, or a sync or async generator. Sync code runs in a worker thread, so a blocking function never stalls the event loop; code that uses the loop, such as `asyncio.Event.set()`, must be async. Sync code cannot be stopped midway: a stop or cancellation drops a call not yet started, and waits for one running to return.

### Output

What the function returns becomes the tool's output (see `grafi.tools.results`):

- **Messages**: a `Message`, or a list of them, passes as it is.
- **`None`**: no output; the node publishes nothing.
- **Anything else**: one message from `role` holding it as text: a string as it is, anything else (a Pydantic model, a dict, a list, a number) as JSON.

### Streaming

A generator streams its output. Each string it yields reaches a caller streaming the run as a delta (see [Runtime](../runtime.md#streaming)), and its output is the text it yielded, joined, as one message. If it also yields other values, those are its outputs, each one a result as above, and its text only streams, as progress:

```python
async def summarize(messages: Messages):
    async for token in my_model.stream(messages[-1].content):
        yield token  # Streamed; the joined text is the tool's output.
```

## Builder Pattern

The `FunctionTool` uses a builder pattern for construction through the `FunctionToolBuilder` class:

```python
function_tool = (
    FunctionTool.builder()
    .function(your_custom_function)
    .build()
)
```

### Example Usage

```python
from grafi.tools.functions.function_tool import FunctionTool
from grafi.common.models.message import Messages
from pydantic import BaseModel

class ProcessResult(BaseModel):
    status: str
    data: dict

def my_custom_function(messages: Messages) -> ProcessResult:
    # Process the input messages
    content = messages[0].content if messages else ""

    return ProcessResult(
        status="processed",
        data={"input_length": len(content)}
    )

# Build the tool
function_tool = (
    FunctionTool.builder()
    .function(my_custom_function)
    .build()
)
```

## Command

`FunctionTool` names no command, so a node runs it through the base `Command`, which passes it the consumed messages as they are (see [Command](../command.md)).

By providing a consistent interface for function execution, the `FunctionTool` enables developers to integrate custom computational logic into event-driven workflows while maintaining clean separation between workflow orchestration and business logic implementation.
