# OllamaTool

`OllamaTool` is an implementation of the `LLM` interface designed to interface with Ollama's language model API. It supports asynchronous interaction, streaming its answer to a caller that streams the run, and function calling, converting workflow `Message` objects into an Ollama-compatible format and translating API responses back into the workflow.

## Fields

| Field              | Type                    | Description                                                                                                    |
|--------------------|-------------------------|----------------------------------------------------------------------------------------------------------------|
| `name`             | `str`                   | Descriptive identifier for the tool (defaults to `"OllamaTool"`).                                             |
| `type`             | `str`                   | Tool type indicator (defaults to `"OllamaTool"`).                                                             |
| `api_url`          | `str`                   | URL of the Ollama API endpoint (defaults to `"http://localhost:11434"`).                                      |
| `model`            | `str`                   | Ollama model name (defaults to `"qwen3"`).                                                                    |
| `system_message`   | `Optional[str]`         | Optional system message to include in API calls (inherited from `LLM`).                                       |
| `chat_params`      | `Dict[str, Any]`        | Additional optional chat parameters, passed to `chat()`; a key set here replaces the tool's own, such as `model` (inherited from `LLM`). |
| `is_streaming`     | `bool`                  | Whether to stream the answer to a caller that streams the run (defaults to `True`, inherited from `LLM`).     |
| `structured_output`| `bool`                  | Whether to use structured output mode (defaults to `False`, inherited from `LLM`).                            |
| `oi_span_type`     | `OpenInferenceSpanKindValues` | Semantic attribute for tracing (set to `LLM`, inherited from `LLM`).                                    |

## Methods

| Method              | Signature                                                          | Description                                                                                         |
|---------------------|--------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `builder()`         | `classmethod -> OllamaToolBuilder`                                | Returns a builder instance for constructing OllamaTool objects.                                    |
| `prepare_api_input` | `(input_data: Messages) -> tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]` | Adapts Message objects to Ollama API format, including function specifications. |
| `invoke`          | `async (invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen` | Calls the Ollama API and yields its answer as one message, streaming its text while a caller streams the run. |
| `to_messages`       | `(response: ChatResponse) -> Messages`                            | Converts a complete response from Ollama's API into Message objects.                               |
| `model_dump(mode="json")` | `() -> dict[str, Any]`                                       | Saves the tool as data. See [Manifests](../manifests.md).                                         |

## How It Works

The Ollama tool processes requests through several key steps:

1. **Input Preparation**: The `prepare_api_input` method converts incoming `Message` objects into the format expected by Ollama's API:
   - Adds system message if configured
   - Converts message fields, mapping `function` role to `tool` role for Ollama compatibility
   - Extracts function specifications and converts them to Ollama tool format
   - Handles function calls by converting them to tool_calls format

2. **API Invocation**:
   - **Asynchronous (`invoke`)**: Uses AsyncClient for concurrent operations
   - **Streaming**: While a caller streams the run and `is_streaming` is on, asks for a stream and emits its text as deltas
   - **Function Calling**: Supports tool/function calling through Ollama's API

3. **Response Processing**:
   - **Streamed responses**: The text and tool calls of every chunk are gathered into one message
   - **Complete responses**: Processed via `to_messages`
   - **Function calls**: Converted to proper tool_call format with generated IDs
   - Either way, the tool yields one `Message`: its text and its tool calls

## Builder Pattern

The `OllamaTool` uses a builder pattern through the `OllamaToolBuilder` class:

```python
ollama_tool = (
    OllamaTool.builder()
    .api_url("http://localhost:11434")
    .model("llama3.2")
    .system_message("You are a helpful assistant.")
    .chat_params({"temperature": 0.7})
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

# Asynchronous invocation
async for response in ollama_tool.invoke(invoke_context, messages):
    print(response[0].content)
```

### Streaming Usage

In a workflow, the caller streams the run with `invoke(..., stream=True)` (see [Runtime](../runtime.md#streaming)). Invoking the tool directly, collect its deltas with `deltas_to`:

```python
from grafi.runtime import deltas_to

async def stream_example():
    messages = [Message(role="user", content="Tell me a story")]
    with deltas_to(lambda delta: print(delta.content, end="", flush=True)):
        async for message_batch in ollama_tool.invoke(invoke_context, messages):
            story = message_batch[0]  # The whole answer, once it is complete.
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

## Function Call Support

Ollama tool provides comprehensive function calling support:

- **Input mapping**: Converts `function_call` messages to Ollama's `tool_calls` format
- **Role conversion**: Maps `function` role to `tool` role for Ollama compatibility
- **Tool specifications**: Converts function specs to Ollama tool format
- **Response handling**: Generates proper tool_call IDs and formats responses

## Error Handling

The Ollama tool provides robust error handling:

- **Import errors**: Clear error message if `ollama` package is not installed
- **API errors**: Failures are raised as `LLMToolException`, with the original error as its cause
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
- **Decorators**: Uses `@record_tool_invoke` for monitoring
- **Local Deployment**: Perfect for local or on-premises LLM deployments

By leveraging `OllamaTool` in your workflows, you can utilize powerful local language models through Ollama while maintaining consistency with Graphite's tool architecture and event-driven patterns. This enables privacy-focused, locally-hosted AI capabilities without external API dependencies.
