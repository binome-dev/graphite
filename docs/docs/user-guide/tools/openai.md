# OpenAITool

`OpenAITool` is a concrete implementation of the `LLM` interface, integrating directly with OpenAI’s language model APIs. It supports synchronous and asynchronous interactions, as well as streaming responses for real-time experience.

The OpenAI tool fields are

| Field        | Description                                                                        |
|--------------|------------------------------------------------------------------------------------|
| `name`       | Name of the tool (inherited from `LLM`, defaults to `"OpenAITool"`).               |
| `type`       | Type indicator for this tool (inherited from `LLM`, defaults to `"OpenAITool"`).   |
| `api_key`    | API key required to authenticate with OpenAI’s services.                           |
| `model`      | Model name used for OpenAI API calls (defaults to `"gpt-4o-mini"`).                |
| `chat_params`| Additional optional [chat completion parameters](https://platform.openai.com/docs/api-reference/chat/create)|

The OpenAI tool methods are

| Method          | Description                                                                                                                                               |
|-----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `prepare_api_input` | Adapts the list of `Message` objects to match the input schema expected by OpenAI’s API, optionally extracting function tools from the latest message.|
| `execute`       | Synchronous method that calls the OpenAI API using the prepared input, returning a single `Message` as the response.                                      |
| `a_execute`     | Asynchronous version of `execute`, returning responses using an async generator for concurrent or streaming workflows.                                    |
| `stream`        | Deprecated synchronous streaming method that yields partial token results as they become available.                                                       |
| `a_stream`      | Asynchronous streaming method that yields partial token results, useful for real-time applications.                                                       |
| `to_stream_message` | Converts partial response chunks (`ChatCompletionChunk`) from OpenAI’s streaming API into a `Message` object.                                         |
| `to_message`    | Converts a fully realized response (`ChatCompletion`) from OpenAI’s API into a single `Message` object.                                                   |
| `to_dict`       | Serializes `OpenAITool` configuration, hiding the `api_key` for security.                                                                                 |

It will take 3 main steps to finish a request. They are

1. **Prepare Input**: Using `prepare_api_input`, the tool converts incoming messages and any associated function specifications into the OpenAI-compatible format.
2. **Execute or Stream**: Depending on whether you call `execute`/`a_execute` or `stream`/`a_stream`, the tool invokes OpenAI’s API to generate a response, optionally streaming tokens.
3. **Response Conversion**: Partial or complete responses are converted into `Message` objects via `to_stream_message` or `to_message`, enabling uniform handling across the workflow.

When create a openai tool, consider following

- **Builder Pattern**: Use the `Builder` class to specify the API key and model before building an `OpenAITool` instance.
- **Model Customization**: Configure the `model` field (e.g., `"gpt-4"`, `"gpt-4o-mini"`) to target specific OpenAI model endpoints.
- **Key Management**: Provide the `api_key` either as an environment variable (`OPENAI_API_KEY`) or explicitly through the builder.
- **Streaming**: For real-time or large-scale tasks, leverage `a_stream` to handle partial responses incrementally.

By integrating `OpenAITool` into your node-based workflows, you can seamlessly introduce advanced language model capabilities powered by OpenAI, maintaining consistency and modularity throughout the system.
