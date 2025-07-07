# FunctionTool

The **FunctionTool** class is a specialized `Tool` designed to invoke custom function-based operations within event-driven workflows. It provides a flexible framework for integrating arbitrary function logic, allowing developers to wrap any callable function and seamlessly integrate it into the workflow system. The tool handles both synchronous and asynchronous function execution while maintaining compatibility with the broader tool interface.

## Fields

| Field          | Type                          | Description                                                                           |
|----------------|-------------------------------|---------------------------------------------------------------------------------------|
| `name`         | `str`                         | Human-readable name identifying the function tool (defaults to `"FunctionTool"`).    |
| `type`         | `str`                         | Specifies the type of the tool (set to `"FunctionTool"`).                           |
| `function`     | `Callable[[Messages], OutputType]` | The callable function that processes input messages and returns output data.   |
| `oi_span_type` | `OpenInferenceSpanKindValues` | Semantic attribute from OpenInference used for tracing (set to `TOOL`).             |

## Methods

| Method              | Signature                                                           | Description                                                                                         |
|---------------------|---------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `builder()`         | `classmethod -> FunctionToolBuilder`                               | Returns a builder instance for constructing FunctionTool objects.                                  |
| `invoke`            | `(invoke_context: InvokeContext, input_data: Messages) -> Messages` | Synchronously invokes the wrapped function with input messages and returns the result as messages. |
| `a_invoke`          | `async (invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen` | Asynchronously invokes the function, supporting both regular and await-able functions.        |
| `to_messages`       | `(response: OutputType) -> Messages`                               | Converts the function's raw response into standardized `Message` objects with appropriate formatting. |
| `to_dict`           | `() -> dict[str, Any]`                                              | Serializes the tool's configuration into a dictionary format for persistence or debugging.         |

## Usage and Customization

### Function Requirements

The `FunctionTool` can wrap any callable that accepts a `Messages` list as input and returns various output types. The function signature must be:

```python
def your_function(messages: Messages) -> OutputType
```

Where `OutputType` is defined as `Union[BaseModel, List[BaseModel]]` but the tool also supports additional types through its output handling.

### Output Handling

The tool automatically handles different response types in its `to_messages` method:

- **`BaseModel` instances**: Serialized to JSON using `model_dump_json()`
- **Lists of `BaseModel` objects**: Converted to JSON arrays using `model_dump()` for each item
- **String responses**: Used directly as message content
- **Other types**: Encoded using `jsonpickle` for complex object serialization

### Async Support

The `a_invoke` method supports both synchronous and asynchronous functions:

- For regular functions: Executes the function normally
- For async functions: Automatically detects await-able responses using `inspect.isawaitable()` and awaits them
- Returns results as an async generator (`MsgsAGen`)

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

## Decorators

The `FunctionTool` class uses the `@use_command(Command)` decorator, which enables integration with the command pattern for tool execution within the workflow system.

By providing a consistent interface for function execution, the `FunctionTool` enables developers to integrate custom computational logic into event-driven workflows while maintaining clean separation between workflow orchestration and business logic implementation.
