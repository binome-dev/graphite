# FunctionCallTool

`FunctionCallTool` is designed to allow Language Models (LLMs) to invoke specific Python functions directly through JSON-formatted calls. When a message from the LLM references a particular function name along with arguments, `FunctionCallTool` checks if it has a function matching that name and, if so, invokes it.

This design greatly reduces the complexity of integrating advanced logic: the LLM simply issues a request to invoke a function, and the tool handles the invocation details behind the scenes.

## Fields

| Field               | Description                                                                                   |
|---------------------|-----------------------------------------------------------------------------------------------|
| `name`             | Descriptive identifier (defaults to `"FunctionCallTool"`).                                       |
| `type`             | Tool type (defaults to `"FunctionCallTool"`).                                                    |
| `function_specs`   | Captures metadata describing the registered function, such as parameter definitions.          |
| `function`         | The actual callable that `FunctionCallTool` invokes when a function call matches `function_specs`.|
| `oi_span_type`     | Semantic tracing attribute (`TOOL`) for observability.                                        |

## Methods

| Method               | Description                                                                                                              |
|----------------------|--------------------------------------------------------------------------------------------------------------------------|
| `function` (Builder) | Builder method to register a function. Automatically applies `@llm_function` if not already decorated.                   |
| `register_function`  | Assigns a function to this tool, generating function specs if missing.                                                   |
| `get_function_specs` | Retrieves detailed metadata about the function (including parameter info), enabling structured LLM-based function calls. |
| `execute`            | Evaluates whether incoming messages match the registered function’s name and, if so, calls it with the JSON arguments.  |
| `a_execute`          | Asynchronous equivalent to `execute`, allowing concurrency if the function is a coroutine.                               |
| `to_message`         | Converts execution results into a `Message` object, preserving context like the `tool_call_id`.                          |
| `to_dict`            | Serializes the `FunctionCallTool` instance, listing function specifications for debugging or persistence.                    |

## How It Works

1. **Function Registration**: A Python function is wrapped or decorated using `@llm_function`. This generates a schema (`function_specs`) describing its name, arguments, and docstring.
2. **Invocation**: When a message arrives specifying a function call, `FunctionCallTool` checks whether it corresponds to the registered function’s name.
3. **JSON Parsing**: The arguments are parsed from the `tool_call` field. If they match, the tool dispatches the function call with the given parameters.
4. **Response**: After execution, the returned data is converted into a new `Message`, allowing the workflow to process the function’s output seamlessly.

## Usage and Customization

- **Builder Pattern**: Use the builder’s `.function(...)` method to assign the function you want to expose. This ensures your function is properly decorated if not already.
- **Flexible**: By simply swapping out the underlying callable, you can quickly adapt to new or updated logic without modifying the rest of the workflow.
- **Observability**: Because `FunctionCallTool` implements the `Tool` interface and integrates with the event-driven architecture, all executions can be monitored and logged.

With `FunctionCallTool`, you can integrate specialized Python functions into an LLM-driven workflow with minimal extra overhead. As your system grows and evolves, it provides a clean way to add or modify functionality while retaining a uniform interaction pattern with the LLM.

## Agent Calling Tool

`AgentCallingTool` extends the `FunctionCallTool` concept to enable multi-agent systems, allowing an LLM to call another agent by name, pass relevant arguments (as a message prompt), and return the agent’s response as part of the workflow.

Fields:

| Field                  | Description                                                                                                        |
|------------------------|--------------------------------------------------------------------------------------------------------------------|
| `name`                | Descriptive identifier, defaults to `"AgentCallingTool"`.                                                           |
| `type`                | Tool type indicator, defaults to `"AgentCallingTool"`.                                                              |
| `agent_name`          | Name of the agent to call; also used as the tool’s name.                                                            |
| `agent_description`    | High-level explanation of what the agent does, used to generate function specs.                                    |
| `argument_description` | Describes the argument required (e.g., `prompt`) for the agent call.                                               |
| `agent_call`          | A callable that takes `(execution_context, Message)` and returns a dictionary (e.g., `{"content": ...}`).           |
| `oi_span_type`        | OpenInference semantic attribute (`TOOL`), enabling observability and traceability.                                 |

Methods:

| Method           | Description                                                                                                                                                                                                 |
|------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `get_function_specs` | Returns the function specification (name, description, parameters) for the agent call.                                                                                                                  |
| `execute`        | Synchronously processes incoming tool calls that match `agent_name`, passing the `prompt` to the `agent_call` callable and returning a list of `Message` objects.                                           |
| `a_execute`      | Asynchronous variant of `execute`; yields messages in an async generator for real-time or concurrent agent calls.                                                                                           |
| `to_message`     | Creates a `Message` object from the agent’s response, linking the output to `tool_call_id`.                                                                                                                 |
| `to_dict`        | Serializes all relevant fields, including agent metadata and the assigned callable, for debugging or persistence.                                                                                           |

Here is the workflow example:

1. **Tool Registration**: An `AgentCallingTool` is constructed with details about the agent (`agent_name`, `agent_description`, etc.) and the callable (`agent_call`).
2. **Agent Invocation**: When an LLM includes a tool call referencing this agent’s name, `execute` or `a_execute` receives the `prompt` and calls the agent.
3. **Response Conversion**: The agent’s return value is formed into a new `Message`, which the workflow can then process or forward.

The usage and customization are:

- **Multi-Agent Systems**: By configuring multiple `AgentCallingTool` instances, you can facilitate dynamic exchanges among multiple agents, each specializing in a different task.
- **Runtime Flexibility**: Changing or updating the underlying `agent_call` logic requires no changes to the rest of the workflow.
- **Parameter Schemas**: `argument_description` ensures the LLM knows which arguments are required and how they should be formatted.

By integrating `AgentCallingTool` into your event-driven workflow, you can build sophisticated multi-agent systems where each agent can be invoked seamlessly via structured function calls. This approach maintains a clear separation between the LLM’s orchestration and the agents’ execution details.

## Example - Weather Mock Tool

A simple mock implementation of a weather service tool that inherits from `FunctionCallTool`. This class provides a straightforward way to use `FunctionCallTool`. It is easy to use - just instantiate and call the method. And implements the `FunctionCallTool` interface for seamless integration. Uses `@llm_function` decorator for automatic registering function.

`@llm_function` is a decorator that enables your Python functions to be seamlessly called by a Language Model (LLM). By inspecting type hints, parsing docstrings, and inferring parameter definitions, this decorator automatically constructs a `FunctionSpec` object that describes your function’s name, parameters (including default values and descriptions), and return type. It then attaches this metadata to the decorated function, making it discoverable and callable within an LLM-driven workflow.

In practical terms, `@llm_function` allows an LLM to dynamically invoke your function with structured, JSON-based arguments. As a result, you can integrate arbitrary Python functions into your dialogue or workflow system without manually encoding parameter details, ensuring consistent and accurate function calls.

```python
class WeatherMock(FunctionCallTool):

    @llm_function
    async def get_weather_mock(self, postcode: str):
        """
        Function to get weather information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve weather information.

        Returns:
            str: A string containing a weather report for the given postcode.
        """
        return f"The weather of {postcode} is bad now."
```

## Example - Tavily Search Tool

[TavilyTool](https://github.com/binome-dev/graphite/blob/main/grafi/tools/function_calls/impl/tavily_tool.py) extends FunctionCallTool to provide web search capabilities through the Tavily API. In general, when the tool will be reused and needs more complex construction, you can create a class with a builder pattern and apply `@llm_function` to the function that will be called by the LLM. By adding the `@llm_function` decorator to `web_search_using_tavily`, you can integrate web search logic into an LLM-driven workflow with minimal extra configuration.

TavilyTool fields:

| Field           | Description                                                                                                      |
|-----------------|------------------------------------------------------------------------------------------------------------------|
| `name`          | Descriptive identifier for the tool (default: `"TavilyTool"`).                                                   |
| `type`          | Tool type indicator (default: `"TavilyTool"`).                                                                   |
| `client`        | Instance of the `TavilyClient` used for performing search queries.                                               |
| `search_depth`  | Defines the search mode (either `"basic"` or `"advanced"`) for Tavily.                                           |
| `max_tokens`    | Limits the total size (in tokens) of the returned JSON string, preventing overly large responses.                |

`web_search_using_tavily` is decorated with `@llm_function`, so it can be invoked by an LLM using structured arguments. It calls the Tavily API with the specified query, search depth, and maximum results, then returns a JSON string containing relevant matches. The method also checks for maximum token usage before appending items to the output.

Usage example:

1. Instantiate the builder:

```python
tavily_tool = (
    TavilyTool.builder()
    .api_key("YOUR_API_KEY")
    .search_depth("advanced")
    .max_tokens(6000)
    .build()
)
```

1. A node in your workflow references `TavilyTool` by name and calls `web_search_using_tavily` when requested by the LLM.
2. The LLM sends a JSON function call containing `query` and `max_results`; TavilyTool executes the query and returns JSON-based results.

You can customize TavilyTool by extending `web_search_using_tavily` with additional parameters or logic. This approach maintains a clean, unified interface for integrating search capabilities into an event-driven or node-based workflow.

## Customized Tools

When your requirements exceed what `FunctionCallTool` can provide, you can implement a custom tool within the framework, ensuring your specialized logic and configuration remain fully integrated into the event-driven workflow.

Here are two examples

### RetrievalTool

[`RetrievalTool`](https://github.com/binome-dev/graphite/blob/main/examples/embedding_assistant/tools/embeddings/retrieval_tool.py) defines a base interface for embedding-based lookups in an event-driven workflow. It inherits from `Tool` and introduces an `embedding_model` field for custom embedding generation. By default, `RetrievalTool` provides a builder pattern so you can assign an embedding model before instantiation. When the required functionality surpasses this base retrieval capability, you can extend or subclass `RetrievalTool` for more specialized use cases.

The [`ChromadbRetrievalTool`](https://github.com/binome-dev/graphite/blob/6e2e0b5bd2959e5a3a9402399df9d66e60490535/examples/embedding_assistant/tools/embeddings/impl/chromadb_retrieval_tool.py) is a concrete subclass of `RetrievalTool`, tailored for queries against a ChromaDB collection. It uses an `OpenAIEmbedding` model (or any suitable `OpenAIEmbedding` subclass) to transform input text into vector embeddings, which are then passed to the ChromaDB collection for similarity matching. During `execute` or `a_execute`, the tool retrieves the most relevant documents by comparing the user’s query embedding against stored embeddings in ChromaDB. The resulting matches are serialized into a `Message` object, making the data seamlessly available to the rest of the workflow. Because it inherits from `RetrievalTool`, you can still configure or replace the embedding model as needed.

RetrievalTool fields:

| Field              | Description                                                                      |
|--------------------|----------------------------------------------------------------------------------|
| `name`             | Tool name (default: `"RetrievalTool"`).                                          |
| `type`             | Type identifier (default: `"RetrievalTool"`).                                    |
| `embedding_model`  | Any embedding model (e.g., OpenAIEmbedding) used to encode text for retrieval.   |
| `oi_span_type`     | Specifies an OpenInference span type (`RETRIEVER`), useful for tracing.          |

ChromadbRetrievalTool fields:

| Field              | Description                                                                                           |
|--------------------|-------------------------------------------------------------------------------------------------------|
| `name`             | Tool name (default: `"ChromadbRetrievalTool"`).                                                       |
| `type`             | Type identifier (default: `"ChromadbRetrievalTool"`).                                                 |
| `collection`       | A ChromaDB `Collection` for storing and querying document embeddings.                                 |
| `embedding_model`  | An instance of `OpenAIEmbedding` used to generate embeddings from user queries.                       |
| `n_results`        | Maximum number of results to return when querying ChromaDB.                                           |
| `oi_span_type`     | Specifies an OpenInference span type (`RETRIEVER`), useful for tracing.                               |

Typical usage involves creating an instance of either tool via its builder, providing any required models or indexes. When an input `Message` arrives, the tool encodes the message text using the configured embedding model, queries the retrieval backend (generic or ChromaDB), and returns a `Message` with the matched results. As part of an event-driven workflow, these matches can then be consumed by subsequent nodes or logic.

### RagTool

[`RagTool`](https://github.com/binome-dev/graphite/blob/main/examples/rag_assistant/tools/rags/rag_tool.py) is used for `RagNode`, providing a specialized `Tool` for Retrieval-Augmented Generation (RAG) use cases. It integrates with [`llama_index`](https://www.llamaindex.ai/) via a `BaseIndex` instance, allowing your workflow to query stored data or documents and incorporate those results into a context-aware response. Ideal for knowledge-intensive tasks, `RagTool` seamlessly translates user queries into an index lookup, returning relevant information as a `Message`.

Fields:

| Field           | Description                                                                                          |
|-----------------|------------------------------------------------------------------------------------------------------|
| `name`          | Identifier for the tool (default: `"RagTool"`).                                                      |
| `type`          | Type of the tool (default: `"RagTool"`).                                                             |
| `index`         | A `BaseIndex` instance from llama_index for retrieving relevant data.                                |
| `oi_span_type`  | An OpenInference semantic attribute indicating the retriever type (`RETRIEVER`).                     |

Execution flow:

1. `execute` or `a_execute` transforms incoming messages into queries against the assigned `BaseIndex`. For synchronous calls, `execute` returns results immediately; `a_execute` uses asynchronous logic.
2. `as_query_engine()` fetches the relevant documents from the index.
3. `to_message` converts the query result into a `Message`, enabling the rest of the workflow to consume the retrieved information.

Usage example:

```python
rag_tool = (
    RagTool.builder()
    .index(your_llama_index)  # Where your_llama_index is an instance of BaseIndex
    .build()
)

# In your workflow, supply `rag_tool` with a user query message.
# The tool will query `your_llama_index` and return a Message with the result.
```

Methods:

| Method       | Description                                                                                               |
|-------------|------------------------------------------------------------------------------------------------------------|
| `execute`    | Synchronously queries the index using the input message’s `content` as a query.                           |
| `a_execute`  | Asynchronous version of `execute`; returns the result in an async generator.                              |
| `to_message` | Converts the response from the query engine to a `Message` object, enabling uniform workflow consumption. |
| `to_dict`    | Provides a dictionary representation of the tool, including its fields and the index class name.          |

With `RagTool`, you can incorporate advanced document retrieval capabilities into your node-based workflows, providing context-rich responses sourced from external knowledge bases while maintaining a clean separation between data storage and LLM-driven logic.
