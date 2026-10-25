# LLM (Base Class)

The `LLM` class is the abstract base class for all language model tools in Graphite. It provides a unified interface and common functionality for integrating various language model providers, including OpenAI, Ollama, and other LLM services. This base class handles function specifications, chat parameters, streaming configurations, and provides standardized patterns for LLM tool implementations.

An LLM returns its answer as one message: its text, its refusal, if any, and its tool calls. While a caller streams the run, it also streams the answer's text as the provider produces it (see [Runtime](../runtime.md#streaming)).

## Fields

| Field              | Type                          | Description                                                                                           |
|--------------------|-------------------------------|-------------------------------------------------------------------------------------------------------|
| `system_message`   | `Optional[str]`               | Optional system message to include in API calls (defaults to `None`).                                |
| `oi_span_type`     | `OpenInferenceSpanKindValues` | Semantic attribute for tracing (set to `LLM` for observability).                                     |
| `api_key`          | `Optional[str]`               | API key for the LLM service, declared with `env_secret`: each provider reads it from its variable, such as `OPENAI_API_KEY`, and saves it as `{"env": "OPENAI_API_KEY"}`, never as its value (the base class has no variable, and defaults to `None`). |
| `model`            | `str`                         | The name of the LLM model to use (e.g., `'gpt-4o-mini'`, defaults to empty string).                 |
| `chat_params`      | `Dict[str, Any]`              | Additional chat completion parameters specific to the LLM provider (defaults to empty dict). A pydantic model class in it, such as a `response_format`, is saved by import path. |
| `is_streaming`     | `bool`                        | Whether to stream the answer, token by token, to a caller that streams the run (defaults to `True`). The provider is asked for a stream only then; Claude always is, as its SDK refuses a long request otherwise, and streams its text to the caller only then. |
| `structured_output`| `bool`                        | Whether the output is structured (e.g., JSON) or unstructured (e.g., plain text, defaults to `False`). |
| `function_specs`   | `FunctionSpecs`               | The specs of functions it is given, besides those its workflow wires to it: functions whose calls the app answers, routing them out of the workflow. Saved when not empty, the first of each name kept. A function-call node's function of the same name is offered with its own spec instead, and a `UserWarning` says so as the workflow is built, or when `offered_to` is called. |

## Methods

| Method               | Signature                                      | Description                                                                                  |
|----------------------|------------------------------------------------|----------------------------------------------------------------------------------------------|
| `add_function_specs` | `(function_spec: FunctionSpecs) -> None`      | Adds specs to its `function_specs`, once each by name. A workflow does not call it.          |
| `get_function_specs` | `() -> FunctionSpecs`                         | The functions the LLM is offered: in a step of its node, those its workflow wires to it, then its `function_specs`, once each by name. |
| `prepare_api_input`  | `(input_data: Messages) -> Any`               | Abstract method that must be implemented by subclasses to prepare API input data.           |
| `sdk_api_key`        | `(*, required: bool = True) -> Optional[str]` | The key to give the provider's SDK (a `str` when required): the one it holds, else its variable's, read now, as it may be set after the tool was made (see `secret_value` in [Manifests](../manifests.md#secrets)). With none it raises `LLMToolException`, naming the variable to set. `required=False` returns None instead, for an SDK that, given none, reads only its provider's own credentials (Claude's, Gemini's, Ollama's), not as an OpenAI-compatible SDK reads `OPENAI_API_KEY` whatever the provider; but a key read from another variable than the tool's own, a tenant's, is required still. |
| `model_dump(mode="json")` | `() -> dict[str, Any]`                   | Saves the LLM as data. See [Manifests](../manifests.md).                                    |

## Builder Pattern

The `LLM` class uses the `LLMBuilder` base class that provides common builder methods:

| Builder Method    | Signature                                        | Description                                                                           |
|-------------------|--------------------------------------------------|---------------------------------------------------------------------------------------|
| `api_key`        | `(api_key: SecretInput) -> Self` (`Union[str, Dict[str, str], None]`) | Sets the API key, or the variable to read it from, `{"env": "VAR"}`, as an assistant's `secret_reference("api_key")` gives it. One read from a variable is saved as that variable; any other cannot be saved. |
| `model`          | `(model: str) -> Self`                          | Sets the model name for the LLM.                                                     |
| `chat_params`    | `(params: Dict[str, Any]) -> Self`              | Sets chat completion parameters. Automatically enables `structured_output` if `response_format` is present. |
| `is_streaming`   | `(is_streaming: bool) -> Self`                  | `False` sends a streaming caller the whole answer only, such as a router's JSON.     |
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

In a workflow, an LLM node is offered the functions of the function-call nodes
reading its calls (see [Event-Driven Workflow](../event-driven-workflow.md#workflow-initialization)),
which answer them: build a `FunctionCallTool` node subscribed to the topic the
LLM node publishes its calls to. Specs given to the LLM itself, its
`function_specs`, are for functions the app answers: route those calls out of
the workflow, and answer each in the next request of the conversation, through
an assistant: the same `conversation_id`, a new `assistant_request_id`, and the
input `Message(role="tool", tool_call_id=call.id, content=...)`.

The workflow does not wait for the app. A reply calling both kinds of function
at once is answered in the workflow, with an empty result for the app's call,
and also reaches the caller, so have such an LLM make one call per reply, as
`chat_params={"parallel_tool_calls": False}` does on OpenAI-compatible tools.
The next request's history holds the conversation's inputs and outputs, not the
calls answered inside the workflow before the app's call.

```python
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.function_spec import FunctionSpec

# A function the app answers itself
show_map = FunctionSpec(
    name="show_map",
    description="Show a map of a location to the user",
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name"}
        },
        "required": ["location"]
    }
)
llm_tool.add_function_specs([show_map])  # Saved with the tool.


def calls_the_app(event: PublishToTopicEvent) -> bool:
    return any(
        call.function.name == "show_map"
        for message in event.data
        for call in message.tool_calls or []
    )

# On the LLM node: .publish_to(agent_output_topic, when=calls_the_app)
```

### Streaming Configuration

An LLM streams to a caller that streams the run (`invoke(..., stream=True)`) unless it is turned off, as for a node whose output the user should not see token by token:

```python
router_llm = (
    ConcreteLLMTool.builder()
    .model("gpt-4o")
    .is_streaming(False)  # Its answer comes whole, even to a streaming caller.
    .build()
)
```

A structured-output call made with the provider's parse endpoint is never streamed.

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

### Retrieving Function Specifications

```python
# In a step of its node: those its workflow wires to it, of the
# function-call nodes reading its calls, then those it is given; elsewhere
# only those it is given
specs = llm_tool.get_function_specs()

# What the LLM of a workflow's node is offered in its steps
specs = workflow.offered_to("LLMNode")
```

`offered_to` is a method of `EventDrivenWorkflow`; an assistant's `workflow`
is typed `Workflow`, so narrow it first, `isinstance(workflow,
EventDrivenWorkflow)`.

A provider reads `get_function_specs()` in its `invoke()`, on the event loop
(or in `asyncio.to_thread`, which keeps the step's context), and hands the
specs to sync SDK code. A node's wiring is bound to its step for its tool
alone, and copies of it (`model_copy()` keeps its `tool_id`; a copy given
another `tool_id`, such as a summarizer, is another tool). An LLM handing its
call to another, such as a fallback, passes its functions on:

```python
inner = self.primary.model_copy(update={"function_specs": self.get_function_specs()})
answer = await inner.invoke(invoke_context, input_data)
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
- **Serialization**: `model_dump(mode="json")` saves the LLM as data, its key as a reference to its environment variable (see [Manifests](../manifests.md))

## Implementation Requirements

When creating a concrete LLM implementation, you must:

1. **Inherit from LLM**: Extend the `LLM` base class
2. **Implement `prepare_api_input`**: Convert `Messages` to provider-specific format
3. **Implement `invoke`**: Call the provider, offering it `self.get_function_specs()`, read in `invoke` on the event loop, and return its answer as one message. When `self.should_stream()` is true (a caller streams the run, and `is_streaming` is on), ask the provider for a stream and send each piece of text with `emit_delta(text)` as it arrives. Give its SDK the key as `self.sdk_api_key()`, called at each call, not `self.api_key`, which is None where its variable, such as a tenant's, is unset, so an SDK would read its own default variable, perhaps another account's key; pass `required=False` only if the SDK, given none, reads only its provider's own credentials
4. **Implement response conversion**: Convert provider responses back to `Messages`
5. **Create a builder**: Extend `LLMBuilder` with provider-specific configuration

### Example Implementation Structure

```python
from typing import Any, Optional

from pydantic import Field
from typing_extensions import Self

from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.manifest import env_secret
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message, Messages
from grafi.tools.llms.llm import LLM, LLMBuilder

class CustomLLM(LLM):
    name: str = Field(default="CustomLLM")
    type: str = Field(default="CustomLLM")
    api_key: Optional[str] = env_secret("CUSTOM_API_KEY")  # Its provider's variable.
    # A component takes only the fields it declares.
    custom_param: str = ""

    @classmethod
    def builder(cls) -> "CustomLLMBuilder":
        return CustomLLMBuilder(cls)

    def prepare_api_input(self, input_data: Messages) -> Any:
        # Convert Messages to provider-specific format
        pass

    @record_tool_invoke  # Records its invoke, answer or failure, and its span.
    async def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        api_key = self.sdk_api_key()  # Raises LLMToolException without one.
        # Call the provider with it; return its answer as one message.
        answer = f"(answer from the provider, called with a {len(api_key)}-char key)"
        return [Message(role="assistant", content=answer)]

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

1. **Streaming**: Have the caller stream the run (`stream=True`) to show long answers as they come
2. **Caching**: Consider caching responses for repeated queries
3. **Batch processing**: Group multiple requests when possible

## Integration with Graphite

The LLM base class integrates seamlessly with Graphite's architecture:

- **Tool Interface**: Implements the standard `Tool` interface
- **Event-Driven**: Works with Graphite's event-driven workflow system
- **Observability**: Built-in tracing and monitoring capabilities
- **Command Pattern**: Uses `LLMCommand` for consistent workflow integration

By leveraging the LLM base class, you can create powerful, consistent, and observable language model integrations that work seamlessly within Graphite's event-driven architecture.
