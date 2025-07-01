# OpenAITool

`OpenAITool` is a concrete implementation of the `LLM` interface, integrating directly with OpenAI's language model APIs. It supports synchronous and asynchronous interactions, as well as streaming responses for real-time applications.

## Fields

| Field              | Type                    | Description                                                                                                    |
|--------------------|-------------------------|----------------------------------------------------------------------------------------------------------------|
| `name`             | `str`                   | Name of the tool (defaults to `"OpenAITool"`).                                                                |
| `type`             | `str`                   | Type indicator for this tool (defaults to `"OpenAITool"`).                                                    |
| `api_key`          | `Optional[str]`         | API key required to authenticate with OpenAI's services (defaults to `OPENAI_API_KEY` environment variable). |
| `model`            | `str`                   | Model name used for OpenAI API calls (defaults to `"gpt-4o-mini"`).                                           |
| `system_message`   | `Optional[str]`         | Optional system message to include in API calls (inherited from `LLM`).                                       |
| `chat_params`      | `Dict[str, Any]`        | Additional optional [chat completion parameters](https://platform.openai.com/docs/api-reference/chat/create) (inherited from `LLM`). |
| `is_streaming`     | `bool`                  | Whether to enable streaming mode for responses (defaults to `False`, inherited from `LLM`).                   |
| `structured_output`| `bool`                  | Whether to use structured output mode via OpenAI's beta API (defaults to `False`, inherited from `LLM`).      |
| `oi_span_type`     | `OpenInferenceSpanKindValues` | Semantic attribute for tracing (set to `LLM`, inherited from `LLM`).                                    |

## Methods

| Method              | Signature                                                          | Description                                                                                         |
|---------------------|--------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `builder()`         | `classmethod -> OpenAIToolBuilder`                                | Returns a builder instance for constructing OpenAITool objects.                                    |
| `prepare_api_input` | `(input_data: Messages) -> tuple[List[ChatCompletionMessageParam], Union[List[ChatCompletionToolParam], NotGiven]]` | Adapts Message objects to OpenAI API format, including function specifications. |
| `invoke`            | `(invoke_context: InvokeContext, input_data: Messages) -> Messages` | Synchronously calls the OpenAI API and returns the response as Messages.                          |
| `a_invoke`          | `async (invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen` | Asynchronously calls the OpenAI API, supporting both streaming and non-streaming modes.     |
| `to_stream_messages`| `(chunk: ChatCompletionChunk) -> Messages`                        | Converts streaming response chunks from OpenAI's API into Message objects.                         |
| `to_messages`       | `(response: ChatCompletion) -> Messages`                          | Converts a complete response from OpenAI's API into Message objects.                               |
| `to_dict`           | `() -> Dict[str, Any]`                                             | Serializes OpenAITool configuration, masking the API key for security.                             |

## How It Works

The OpenAI tool processes requests through several key steps:

1. **Input Preparation**: The `prepare_api_input` method converts incoming `Message` objects into the format expected by OpenAI's API:
   - Adds system message if configured
   - Converts message fields (role, content, tool_calls, etc.) to OpenAI format
   - Extracts function specifications and converts them to OpenAI tool format

2. **API Invocation**: Depending on the method called:
   - **Synchronous (`invoke`)**: Creates an OpenAI client and makes a direct API call
   - **Asynchronous (`a_invoke`)**: Uses AsyncClient for concurrent operations
   - **Streaming**: When `is_streaming=True`, processes responses incrementally
   - **Structured Output**: When `structured_output=True`, uses OpenAI's beta parsing API

3. **Response Processing**:
   - **Streaming responses**: Processed chunk by chunk via `to_stream_messages`
   - **Complete responses**: Processed via `to_messages`
   - All responses are converted to standardized `Message` objects

## Builder Pattern

The `OpenAITool` uses a builder pattern through the `OpenAIToolBuilder` class:

```python
openai_tool = (
    OpenAITool.builder()
    .api_key("your-api-key")
    .model("gpt-4o")
    .system_message("You are a helpful assistant.")
    .chat_params({"temperature": 0.7, "max_tokens": 1000})
    .is_streaming(True)
    .build()
)
```

## Usage Examples

### Basic Usage

```python
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.common.models.message import Message

# Create the tool
openai_tool = (
    OpenAITool.builder()
    .api_key("your-openai-api-key")
    .model("gpt-4o-mini")
    .build()
)

# Create input messages
messages = [Message(role="user", content="Hello, how are you?")]

# Synchronous invocation
response = openai_tool.invoke(invoke_context, messages)
print(response[0].content)
```

### Streaming Usage

```python
# Enable streaming
openai_tool = (
    OpenAITool.builder()
    .api_key("your-openai-api-key")
    .model("gpt-4o")
    .is_streaming(True)
    .build()
)

# Asynchronous streaming
async def stream_example():
    messages = [Message(role="user", content="Tell me a story")]
    async for message_batch in openai_tool.a_invoke(invoke_context, messages):
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

openai_tool.add_function_specs([function_spec])

# The tool will now include function specifications in API calls
```

## Configuration Options

### Environment Variables

- `OPENAI_API_KEY`: Default API key if not explicitly provided

### Chat Parameters

Common chat completion parameters you can include in `chat_params`:

```python
chat_params = {
    "temperature": 0.7,        # Creativity level (0.0-2.0)
    "max_tokens": 1000,        # Maximum response length
    "top_p": 0.9,              # Nucleus sampling
    "frequency_penalty": 0.0,  # Penalty for repeated tokens
    "presence_penalty": 0.0,   # Penalty for new topics
    "response_format": {"type": "json_object"}  # For structured output
}
```

### Structured Output

When using structured output mode:

```python
openai_tool = (
    OpenAITool.builder()
    .chat_params({"response_format": {"type": "json_object"}})
    .build()
)
# structured_output will automatically be set to True
```

## Error Handling

The OpenAI tool provides robust error handling:

- **API Errors**: OpenAI-specific errors are caught and re-raised as `RuntimeError` with descriptive messages
- **Cancellation**: Async operations properly handle `asyncio.CancelledError`
- **Network Issues**: Connection and timeout issues are wrapped in appropriate exceptions

## Integration

The `OpenAITool` integrates seamlessly with Graphite's architecture:

- **Command Pattern**: Uses `@use_command(LLMCommand)` for workflow integration
- **Observability**: Includes OpenInference tracing with `LLM` span type
- **Decorators**: Uses `@record_tool_invoke` and `@record_tool_a_invoke` for monitoring

By leveraging `OpenAITool` in your workflows, you gain access to OpenAI's powerful language models while maintaining consistency with Graphite's tool architecture and event-driven patterns.
