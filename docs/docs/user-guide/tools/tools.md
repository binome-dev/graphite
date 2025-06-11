# Tools Core

In our platform, **Tools** represent the execution components within a workflow. A Tool is essentially a function designed to transform input data into output based on specified rules or logic. Tools can encompass interactions with Language Models (LLMs), external API calls, or purely deterministic functions. Crucially, Tools operate independently of the workflow context—they are unaware of the invoking node or their position within the workflow graph. Each Tool strictly adheres to a defined schema, processing a list of `Message` objects as input and returning a list of `Message` objects as output.

The following table describes each field within the Tool interface class

| Field           | Description                                                               |
|-----------------|---------------------------------------------------------------------------|
| `tool_id`       | Unique identifier assigned to each Tool instance.                         |
| `name`          | Human-readable identifier for the Tool.                                   |
| `type`          | Specifies the category or nature of the Tool.                             |
| `oi_span_type`  | Semantic attribute from OpenInference used for tracing and observability. |

The following table describes each method within the Tool interface class

| Method           | Description                                                                                       |
|------------------|---------------------------------------------------------------------------------------------------|
| `execute`        | Synchronously processes input messages according to the Tool's logic and returns a result message.|
| `a_execute`      | Asynchronously processes input messages, typically used for streaming or concurrent operations.   |
| `to_message`     | Converts the Tool's raw response into a standardized `Message` object.                            |
| `to_dict`        | Serializes the Tool instance into a dictionary format for persistence or debugging.               |

Developers can implement custom Tools tailored to specific business logic or operational requirements. By following the clearly defined interface, new Tools can seamlessly integrate into existing workflows, enhancing modularity, extensibility, and maintainability of the overall system.

Here we introduce some build in tools with corresponding command implementation.

## LLMTool Interface and OpenAITool Implementation

The **LLM** class is a specialized `Tool` designed to interface with Language Model (LLM) services such as OpenAI, Claude, or other third-party providers. It provides both synchronous and asynchronous streaming options, making it suitable for various real-time or batch processing scenarios. By adhering to the base `Tool` interface, it remains compatible with the broader event-driven workflow and command pattern used throughout the system.

### Fields

| Field            | Description                                                                                            |
|------------------|--------------------------------------------------------------------------------------------------------|
| `tool_id`        | Unique identifier for the LLM tool instance (inherited from `Tool`).                                   |
| `name`           | Human-readable name identifying the LLM tool (inherited from `Tool`).                                  |
| `type`           | Specifies the type of the tool (inherited from `Tool`).                                                |
| `system_message` | An optional system or instructional message to guide the LLM’s behavior.                               |
| `oi_span_type`   | Semantic attribute from OpenInference used for tracing, specifically set to `LLM`.                     |

### Methods

| Method              | Description                                                                                                  |
|---------------------|--------------------------------------------------------------------------------------------------------------|
| `execute`           | Implements the core logic for synchronous requests (inherited from `Tool`). Must be overridden by subclasses.|
| `a_execute`         | Implements the core logic for asynchronous requests (inherited from `Tool`). Must be overridden.             |
| `stream`            | Provides synchronous streaming functionality, yielding LLM responses as they become available.               |
| `a_stream`          | Provides asynchronous streaming functionality, useful for real-time or larger-scale deployments.             |
| `prepare_api_input` | Prepares input data (list of messages) to match the expected format of the LLM API.                          |
| `to_dict`           | Serializes the LLM tool’s current configuration into a dictionary format.                                    |

### Usage and Customization

- **Subclasses**: To implement a concrete LLM tool, create a subclass of `LLM` and override `execute`, `a_execute`, `stream`, and `a_stream` methods. This allows for integration with various LLM providers (e.g., OpenAI, Claude) while following a consistent interface.
- **System Message**: You can specify a `system_message` to influence the tone or purpose of the LLM’s responses. This is particularly useful for role-based messaging systems or specialized tasks.
- **API Input Preparation**: Use `prepare_api_input` to adapt your workflow messages into the required schema for each LLM provider’s endpoint, making integration with new or changing APIs more flexible.

By adhering to the `Tool` interface and focusing on LLM operations, the `LLM` class bridges message-based workflows with language model services, ensuring a clean separation of concerns and streamlined integration into the rest of the system.

### Streaming

We added two stream interface for LLM, adding the user friendly interaction with the agent. However, when we use the stream in assistant, we only use a_stream for async capability.
