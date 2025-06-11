# OllamaTool

Similar to OpenAI tool, `OllamaTool` is an implementation of the `LLM` interface designed to interface with Ollama’s language model API. It supports synchronous and asynchronous execution patterns, converting workflow `Message` objects into an Ollama-compatible format and translating API responses back into the workflow.

Fields:

| Field      | Description                                                                    |
|------------|--------------------------------------------------------------------------------|
| `name`     | Descriptive identifier for the tool (defaults to `"OllamaTool"`).              |
| `type`     | Tool type indicator (defaults to `"OllamaTool"`).                              |
| `api_url`  | URL of the Ollama API endpoint (defaults to `"http://localhost:11434"`).       |
| `model`    | Ollama model name (defaults to `"qwen3"`).                                   |

Methods:

| Method             | Description                                                                                                       |
|--------------------|-------------------------------------------------------------------------------------------------------------------|
| `prepare_api_input`| Adapts the list of `Message` objects to match Ollama’s expected input format, including function calls if present.|
| `execute`          | Synchronously calls the Ollama API, returning a `Message` with the resulting content or function calls.           |
| `a_execute`        | Asynchronously calls the Ollama API, yielding a `Message` in an async generator for real-time processing.         |
| `to_message`       | Converts Ollama’s raw API response into a `Message`, supporting function call data when present.                  |
| `to_dict`          | Provides a dictionary representation of the `OllamaTool` configuration.                                           |

This tool can be configured with its internal `Builder` class, allowing customization of fields such as the `api_url` or `model` before constructing an instance. By integrating `OllamaTool` into the workflow, developers can leverage local or remote Ollama services without altering the overarching event-driven logic. Messages from the workflow are passed to Ollama, and responses are returned in a consistent format, preserving a clear separation between orchestration and execution logic.
