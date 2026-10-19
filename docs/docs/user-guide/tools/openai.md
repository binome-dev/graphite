# OpenAITool

`OpenAITool` is a concrete implementation of the `LLM` interface, integrating directly with OpenAI's language model APIs. It answers with one message, and streams the answer's text to a caller that streams the run.

## Fields

| Field              | Type                    | Description                                                                                                    |
|--------------------|-------------------------|----------------------------------------------------------------------------------------------------------------|
| `name`             | `str`                   | Name of the tool (defaults to `"OpenAITool"`).                                                                |
| `type`             | `str`                   | Type indicator for this tool (defaults to `"OpenAITool"`).                                                    |
| `api_key`          | `Optional[str]`         | API key required to authenticate with OpenAI's services (defaults to `OPENAI_API_KEY` environment variable). |
| `model`            | `str`                   | Model name used for OpenAI API calls (defaults to `"gpt-4.1-nano"`).                                           |
| `system_message`   | `Optional[str]`         | Optional system message to include in API calls (inherited from `LLM`).                                       |
| `chat_params`      | `Dict[str, Any]`        | Additional optional [chat completion parameters](https://platform.openai.com/docs/api-reference/chat/create) (inherited from `LLM`). |
| `is_streaming`     | `bool`                  | Whether to stream the answer to a caller that streams the run (defaults to `True`, inherited from `LLM`).     |
| `structured_output`| `bool`                  | Whether to use structured output mode via OpenAI's beta API (defaults to `False`, inherited from `LLM`).      |
| `oi_span_type`     | `OpenInferenceSpanKindValues` | Semantic attribute for tracing (set to `LLM`, inherited from `LLM`).                                    |

## Methods

| Method              | Signature                                                          | Description                                                                                         |
|---------------------|--------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `builder()`         | `classmethod -> OpenAIToolBuilder`                                | Returns a builder instance for constructing OpenAITool objects.                                    |
| `prepare_api_input` | `(input_data: Messages) -> tuple[List[ChatCompletionMessageParam], Union[List[ChatCompletionToolParam], Omit]]` | Adapts Message objects to OpenAI API format, including function specifications. |
| `invoke`          | `async (invoke_context: InvokeContext, input_data: Messages) -> MsgsAGen` | Calls the OpenAI API and yields its answer as one message, streaming its text while a caller streams the run. |
| `to_messages`       | `(response: ChatCompletion) -> Messages`                          | Converts a complete response from OpenAI's API into Message objects.                               |
| `to_dict`           | `() -> Dict[str, Any]`                                             | Serializes OpenAITool configuration, masking the API key for security.                             |

## How It Works

The OpenAI tool processes requests through several key steps:

1. **Input Preparation**: The `prepare_api_input` method converts incoming `Message` objects into the format expected by OpenAI's API:
   - Adds system message if configured
   - Converts message fields (role, content, tool_calls, etc.) to OpenAI format, sending each tool call's standard fields only, whichever provider made it
   - Extracts function specifications and converts them to OpenAI tool format

2. **API Invocation**:
   - **Asynchronous (`invoke`)**: Uses AsyncClient for concurrent operations
   - **Streaming**: While a caller streams the run and `is_streaming` is on, asks for a stream and emits its text as deltas
   - **Structured Output**: When `structured_output=True`, uses OpenAI's beta parsing API, never streamed

3. **Response Processing**:
   - **Streamed responses**: The text and the tool-call fragments are gathered into one message, its tool calls whole. Only text and arguments are joined, as providers differ in which fields, such as the role, they repeat in every chunk
   - **Complete responses**: Processed via `to_messages`
   - Either way, the tool yields one `Message`: its text, refusal and tool calls

## Builder Pattern

The `OpenAITool` uses a builder pattern through the `OpenAIToolBuilder` class:

```python
openai_tool = (
    OpenAITool.builder()
    .api_key("your-api-key")
    .model("gpt-4o")
    .system_message("You are a helpful assistant.")
    .chat_params({"temperature": 0.7, "max_tokens": 1000})
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

# Asynchronous invocation
async for response in openai_tool.invoke(invoke_context, messages):
    print(response[0].content)
```

### Streaming Usage

In a workflow, the caller streams the run with `invoke(..., stream=True)` (see [Runtime](../runtime.md#streaming)). Invoking the tool directly, collect its deltas with `deltas_to`:

```python
from grafi.runtime import deltas_to

async def stream_example():
    messages = [Message(role="user", content="Tell me a story")]
    with deltas_to(lambda delta: print(delta.content, end="", flush=True)):
        async for message_batch in openai_tool.invoke(invoke_context, messages):
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
- **Decorators**: Uses `@record_tool_invoke` for monitoring

By leveraging `OpenAITool` in your workflows, you gain access to OpenAI's powerful language models while maintaining consistency with Graphite's tool architecture and event-driven patterns.
