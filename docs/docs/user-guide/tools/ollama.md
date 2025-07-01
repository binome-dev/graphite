# OllamaTool

`OllamaTool` is an implementation of the `LLM` interface designed to interface with Ollama's language model API. It supports synchronous and asynchronous interaction patterns, streaming responses, and function calling, converting workflow `Message` objects into an Ollama-compatible format and translating API responses back into the workflow.

## Fields

| Field              | Type                    | Description                                                                                                    |
|--------------------|-------------------------|----------------------------------------------------------------------------------------------------------------|
| `name`             | `str`                   | Descriptive identifier for the tool (defaults to `"OllamaTool"`).                                             |
| `type`             | `str`                   | Tool type indicator (defaults to `"OllamaTool"`).                                                             |
| `api_url`          | `str`                   | URL of the Ollama API endpoint (defaults to `"http://localhost:11434"`).                                      |
| `model`            | `str`                   | Ollama model name (defaults to `"qwen3"`).                                                                    |
| `system_message`   | `Optional[str]`         | Optional system message to include in API calls (inherited from `LLM`).                                       |
| `chat_params`      | `Dict[str, Any]`        | Additional optional chat completion parameters (inherited from `LLM`).                                        |
| `is_streaming`     | `bool`                  | Whether to enable streaming mode for responses (defaults to `False`, inherited from `LLM`).                   |
| `structured_output`| `bool`                  | Whether to use structured output mode (defaults to `False`, inherited from `LLM`).                            |
| `oi_span_type`     | `OpenInferenceSpanKindValues` | Semantic attribute for tracing (set to `LLM`, inherited from `LLM`).                                    |

## Methods

| Method              | Signature                                                          | Description                                                                                         |
|---------------------|--------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `builder()`         | `classmethod -> OllamaToolBuilder`                                | Returns a builder instance for constructing OllamaTool objects.                                    |
| `prepare_api_input` | `(input_data: Messages) -> tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]` | Adapts Message objects to Ollama API format, including function specifications. |
| `invoke`            | `(invoke_context: InvokeContext, input_data: Messages) -> Messages` | Synchronously calls the Ollama API and returns the response as Messages.                          |
| `a_invoke`          | `async (invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen` | Asynchronously calls the Ollama API, supporting both streaming and non-streaming modes.     |
| `to_stream_messages`| `(chunk: ChatResponse \| dict[str, Any]) -> Messages` | Converts streaming response chunks from Ollama's API into Message objects. |
| `to_messages`       | `(response: ChatResponse) -> Messages`                            | Converts a complete response from Ollama's API into Message objects.                               |
| `to_dict`           | `() -> dict[str, Any]`                                             | Provides a dictionary representation of the OllamaTool configuration.                              |

## How It Works

The Ollama tool processes requests through several key steps:

1. **Input Preparation**: The `prepare_api_input` method converts incoming `Message` objects into the format expected by Ollama's API:
   - Adds system message if configured
   - Converts message fields, mapping `function` role to `tool` role for Ollama compatibility
   - Extracts function specifications and converts them to Ollama tool format
   - Handles function calls by converting them to tool_calls format

2. **API Invocation**: Depending on the method called:
   - **Synchronous (`invoke`)**: Creates an Ollama client and makes a direct API call
   - **Asynchronous (`a_invoke`)**: Uses AsyncClient for concurrent operations
   - **Streaming**: When `is_streaming=True`, processes responses incrementally
   - **Function Calling**: Supports tool/function calling through Ollama's API

3. **Response Processing**:
   - **Streaming responses**: Processed chunk by chunk via `to_stream_messages`
   - **Complete responses**: Processed via `to_messages`
   - **Function calls**: Converted to proper tool_call format with generated IDs
   - All responses are converted to standardized `Message` objects

## Builder Pattern

The `OllamaTool` uses a builder pattern through the `OllamaToolBuilder` class:

```python
ollama_tool = (
    OllamaTool.builder()
    .api_url("http://localhost:11434")
    .model("llama3.2")
    .system_message("You are a helpful assistant.")
    .chat_params({"temperature": 0.7})
    .is_streaming(True)
    .build()
)
```

## Usage Examples

### Basic Usage

```python
from grafi.tools.llms.impl.ollama_tool import OllamaTool
from grafi.common.models.message import Message

# Create the tool
ollama_tool = (
    OllamaTool.builder()
    .api_url("http://localhost:11434")
    .model("llama3.2")
    .build()
)

# Create input messages
messages = [Message(role="user", content="Hello, how are you?")]

# Synchronous invocation
response = ollama_tool.invoke(invoke_context, messages)
print(response[0].content)
```

### Streaming Usage

```python
# Enable streaming
ollama_tool = (
    OllamaTool.builder()
    .api_url("http://localhost:11434")
    .model("qwen3")
    .is_streaming(True)
    .build()
)

# Asynchronous streaming
async def stream_example():
    messages = [Message(role="user", content="Tell me a story")]
    async for message_batch in ollama_tool.a_invoke(invoke_context, messages):
        for message in message_batch:
            if message.content:
                print(message.content, end="", flush=True)
```

### Function Calling

```python
from grafi.common.models.function_spec import FunctionSpec

# Add function specifications
function_spec = FunctionSpec(
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

ollama_tool.add_function_specs([function_spec])

# The tool will now include function specifications in API calls
```

## Configuration Options

### API Configuration

- **`api_url`**: Customize the Ollama server endpoint (default: `http://localhost:11434`)
- **`model`**: Specify the Ollama model to use (default: `qwen3`)

### Common Models

Popular Ollama models you can use:

- `llama3.2` - Meta's Llama 3.2 model
- `qwen3` - Alibaba's Qwen3 model  
- `mistral` - Mistral AI's model
- `codellama` - Code-specialized Llama model
- `phi3` - Microsoft's Phi-3 model

### Chat Parameters

You can include additional parameters in `chat_params`:

```python
chat_params = {
    "temperature": 0.7,        # Creativity level
    "top_p": 0.9,              # Nucleus sampling
    "top_k": 40,               # Top-k sampling
    "repeat_penalty": 1.1,     # Penalty for repetition
}
```

## Streaming Response Handling

The `to_stream_messages` method handles both `ChatResponse` objects and plain dictionaries:

- **Empty content filtering**: Skips empty deltas to avoid blank messages
- **Role mapping**: Ensures proper role assignment with fallback to "assistant"
- **Streaming flag**: Sets `is_streaming=True` on streamed messages
- **Incremental content**: Provides delta content for real-time display

## Function Call Support

Ollama tool provides comprehensive function calling support:

- **Input mapping**: Converts `function_call` messages to Ollama's `tool_calls` format
- **Role conversion**: Maps `function` role to `tool` role for Ollama compatibility
- **Tool specifications**: Converts function specs to Ollama tool format
- **Response handling**: Generates proper tool_call IDs and formats responses

## Error Handling

The Ollama tool provides robust error handling:

- **Import errors**: Clear error message if `ollama` package is not installed
- **API errors**: Ollama-specific errors are caught and re-raised as `RuntimeError` with descriptive messages
- **Connection issues**: Network and server connectivity issues are properly handled

## Installation Requirements

The OllamaTool requires the `ollama` package:

```bash
pip install ollama
```

## Integration

The `OllamaTool` integrates seamlessly with Graphite's architecture:

- **Command Pattern**: Uses `@use_command(LLMCommand)` for workflow integration
- **Observability**: Includes OpenInference tracing with `LLM` span type
- **Decorators**: Uses `@record_tool_invoke` and `@record_tool_a_invoke` for monitoring
- **Local Deployment**: Perfect for local or on-premises LLM deployments

By leveraging `OllamaTool` in your workflows, you can utilize powerful local language models through Ollama while maintaining consistency with Graphite's tool architecture and event-driven patterns. This enables privacy-focused, locally-hosted AI capabilities without external API dependencies.
