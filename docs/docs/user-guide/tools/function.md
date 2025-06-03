The **FunctionTool** class is a specialized `Tool` designed to execute custom function-based operations within event-driven workflows. It provides a flexible framework for integrating arbitrary function logic, allowing developers to wrap any callable function and seamlessly integrate it into the workflow system. The tool handles both synchronous and asynchronous execution patterns while maintaining compatibility with the broader tool interface.

#### Fields

| Field          | Description                                                                                            |
|----------------|--------------------------------------------------------------------------------------------------------|
| `tool_id`      | Unique identifier for the FunctionTool instance (inherited from `Tool`).                              |
| `name`         | Human-readable name identifying the function tool (`"FunctionTool"` by default).                      |
| `type`         | Specifies the type of the tool (`"FunctionTool"`).                                                    |
| `function`     | The callable function that processes input messages and returns output data.                           |
| `oi_span_type` | Semantic attribute from OpenInference used for tracing, specifically set to `TOOL`.                   |

#### Methods

| Method              | Description                                                                                                  |
|---------------------|--------------------------------------------------------------------------------------------------------------|
| `execute`           | Synchronously executes the wrapped function with input messages and returns the result as messages.         |
| `a_execute`         | Asynchronously executes the function, supporting both regular and awaitable functions.                       |
| `to_messages`       | Converts the function's raw response into standardized `Message` objects with appropriate formatting.        |
| `to_dict`           | Serializes the tool's configuration into a dictionary format for persistence or debugging.                  |

#### Usage and Customization

- **Function Integration**: The `FunctionTool` can wrap any callable that accepts a `Messages` list as input and returns various output types including `BaseModel`, `List[BaseModel]`, strings, or other serializable objects.
- **Output Handling**: The tool automatically handles different response types:
  - `BaseModel` instances are serialized to JSON
  - Lists of `BaseModel` objects are converted to JSON arrays
  - String responses are used directly
  - Other types are encoded using `jsonpickle`
- **Async Support**: The tool supports both synchronous and asynchronous functions, automatically detecting and handling awaitable responses.

#### Builder Pattern

The `FunctionTool` uses a builder pattern for construction:

```python
function_tool = (
    FunctionTool.Builder()
    .function(your_custom_function)
    .build()
)
```

By providing a consistent interface for function execution, the `FunctionTool` enables developers to integrate custom computational logic into event-driven workflows while maintaining clean separation between workflow orchestration and business logic implementation.
