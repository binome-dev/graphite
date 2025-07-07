# LLM (Base Class)

The `LLM` class is the abstract base class for all language model tools in Graphite. It provides a unified interface and common functionality for integrating various language model providers, including OpenAI, Ollama, and other LLM services. This base class handles function specifications, chat parameters, streaming configurations, and provides standardized patterns for LLM tool implementations.

## Fields

| Field              | Type                          | Description                                                                                           |
|--------------------|-------------------------------|-------------------------------------------------------------------------------------------------------|
| `system_message`   | `Optional[str]`               | Optional system message to include in API calls (defaults to `None`).                                |
| `oi_span_type`     | `OpenInferenceSpanKindValues` | Semantic attribute for tracing (set to `LLM` for observability).                                     |
| `api_key`          | `Optional[str]`               | API key for the LLM service (defaults to `None`).                                                    |
| `model`            | `str`                         | The name of the LLM model to use (e.g., `'gpt-4o-mini'`, defaults to empty string).                 |
| `chat_params`      | `Dict[str, Any]`              | Additional chat completion parameters specific to the LLM provider (defaults to empty dict).         |
| `is_streaming`     | `bool`                        | Whether to enable streaming mode for responses (defaults to `False`).                                |
| `structured_output`| `bool`                        | Whether the output is structured (e.g., JSON) or unstructured (e.g., plain text, defaults to `False`). |
| `_function_specs`  | `FunctionSpecs` (private)     | Private attribute storing function specifications for function calling capabilities.                  |

## Methods

| Method               | Signature                                      | Description                                                                                  |
|----------------------|------------------------------------------------|----------------------------------------------------------------------------------------------|
| `add_function_specs` | `(function_spec: FunctionSpecs) -> None`      | Adds function specifications to the LLM for function calling capabilities.                  |
| `get_function_specs` | `() -> FunctionSpecs`                         | Returns a copy of the function specifications currently registered with the LLM.            |
| `prepare_api_input`  | `(input_data: Messages) -> Any`               | Abstract method that must be implemented by subclasses to prepare API input data.           |
| `to_dict`            | `() -> dict[str, Any]`                        | Serializes the LLM configuration into a dictionary format.                                  |

## Builder Pattern

The `LLM` class uses the `LLMBuilder` base class that provides common builder methods:

| Builder Method    | Signature                                        | Description                                                                           |
|-------------------|--------------------------------------------------|---------------------------------------------------------------------------------------|
| `model`          | `(model: str) -> Self`                          | Sets the model name for the LLM.                                                     |
| `chat_params`    | `(params: Dict[str, Any]) -> Self`              | Sets chat completion parameters. Automatically enables `structured_output` if `response_format` is present. |
| `is_streaming`   | `(is_streaming: bool) -> Self`                  | Enables or disables streaming mode.                                                  |
| `system_message` | `(system_message: Optional[str]) -> Self`      | Sets the system message to be included in API calls.                                 |

## Usage Patterns

### Basic LLM Configuration

```python
# Example with a concrete LLM implementation
llm_tool = (
    ConcreteLLMTool.builder()
    .model("gpt-4o-mini")
    .system_message("You are a helpful assistant.")
    .chat_params({"temperature": 0.7, "max_tokens": 1000})
    .build()
)
```

### Function Calling Setup

```python
from grafi.common.models.function_spec import FunctionSpec

# Create function specifications
function_specs = [
    FunctionSpec(
        name="get_weather",
        description="Get current weather for a location",
        parameters={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"}
            },
            "required": ["location"]
        }
    )
]

# Add to LLM
llm_tool.add_function_specs(function_specs)

# Verify function specs are registered
registered_specs = llm_tool.get_function_specs()
print(f"Registered {len(registered_specs)} function specifications")
```

### Streaming Configuration

```python
# Enable streaming for real-time responses
streaming_llm = (
    ConcreteLLMTool.builder()
    .model("gpt-4o")
    .is_streaming(True)
    .build()
)
```

### Structured Output Configuration

```python
# Configure for structured JSON output
structured_llm = (
    ConcreteLLMTool.builder()
    .model("gpt-4o")
    .chat_params({
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    })
    .build()
)
# structured_output will automatically be set to True
```

## Function Specification Management

The LLM base class provides built-in support for managing function specifications:

### Adding Function Specifications

```python
# Single function spec
function_spec = FunctionSpec(name="calculate", description="Perform calculation")
llm_tool.add_function_specs([function_spec])

# Multiple function specs
function_specs = [spec1, spec2, spec3]
llm_tool.add_function_specs(function_specs)

# Empty specs are safely ignored
llm_tool.add_function_specs([])  # No operation
llm_tool.add_function_specs(None)  # No operation
```

### Retrieving Function Specifications

```python
# Get a copy of all registered function specs
specs = llm_tool.get_function_specs()

# The returned list is a copy, so modifications don't affect the original
specs.append(new_spec)  # This won't affect the LLM's internal specs
```

## Chat Parameters

Different LLM providers support various chat parameters. The `chat_params` field allows provider-specific customization:

### OpenAI Parameters

```python
openai_params = {
    "temperature": 0.7,
    "max_tokens": 1000,
    "top_p": 0.9,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "response_format": {"type": "json_object"}
}
```

### Ollama Parameters

```python
ollama_params = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1
}
```

## Observability and Tracing

The LLM base class integrates with OpenInference for observability:

- **Span Type**: All LLM tools use `OpenInferenceSpanKindValues.LLM` for consistent tracing
- **Command Integration**: Uses `@use_command(LLMCommand)` for workflow integration
- **Serialization**: `to_dict()` method provides structured representation for logging and debugging

## Implementation Requirements

When creating a concrete LLM implementation, you must:

1. **Inherit from LLM**: Extend the `LLM` base class
2. **Implement `prepare_api_input`**: Convert `Messages` to provider-specific format
3. **Implement `invoke` and `a_invoke`**: Handle synchronous and asynchronous API calls
4. **Implement response conversion**: Convert provider responses back to `Messages`
5. **Create a builder**: Extend `LLMBuilder` with provider-specific configuration

### Example Implementation Structure

```python
from grafi.tools.llms.llm import LLM, LLMBuilder

class CustomLLM(LLM):
    name: str = Field(default="CustomLLM")
    type: str = Field(default="CustomLLM")

    @classmethod
    def builder(cls) -> "CustomLLMBuilder":
        return CustomLLMBuilder(cls)

    def prepare_api_input(self, input_data: Messages) -> Any:
        # Convert Messages to provider-specific format
        pass

    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        # Synchronous API call implementation
        pass

    async def a_invoke(self, invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen:
        # Asynchronous API call implementation
        pass

class CustomLLMBuilder(LLMBuilder[CustomLLM]):
    def custom_param(self, value: str) -> Self:
        self.kwargs["custom_param"] = value
        return self
```

## Available Implementations

Graphite provides several concrete LLM implementations:

- **OpenAITool**: Integration with OpenAI's GPT models
- **OllamaTool**: Integration with local Ollama deployments
- **Other providers**: Additional implementations for various LLM services

## Best Practices

### Configuration

1. **Use builders**: Always use the builder pattern for clean, readable configuration
2. **Set system messages**: Provide clear system instructions for consistent behavior
3. **Configure parameters**: Tune temperature, max_tokens, and other parameters for your use case

### Function Calling

1. **Clear descriptions**: Provide detailed function descriptions for better LLM understanding
2. **Proper schemas**: Use complete JSON schemas with required fields and descriptions
3. **Validation**: Validate function specifications before adding them

### Error Handling

1. **API key management**: Handle missing or invalid API keys gracefully
2. **Network issues**: Implement proper retry logic and timeout handling
3. **Rate limiting**: Respect provider rate limits and implement back-off strategies

### Performance

1. **Streaming**: Use streaming for long responses to improve user experience
2. **Caching**: Consider caching responses for repeated queries
3. **Batch processing**: Group multiple requests when possible

## Integration with Graphite

The LLM base class integrates seamlessly with Graphite's architecture:

- **Tool Interface**: Implements the standard `Tool` interface
- **Event-Driven**: Works with Graphite's event-driven workflow system
- **Observability**: Built-in tracing and monitoring capabilities
- **Command Pattern**: Uses `LLMCommand` for consistent workflow integration

By leveraging the LLM base class, you can create powerful, consistent, and observable language model integrations that work seamlessly within Graphite's event-driven architecture.
