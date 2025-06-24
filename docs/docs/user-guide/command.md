# Command

In our platform, the **Command** implements the Command Pattern, effectively separating workflow orchestration (Nodes) from invoke logic (Tools). Commands encapsulate the request or invoke logic, allowing the orchestrator (Node) to delegate invoke to the executor (Tool) without needing to know the internal details of the invoke process.

Using the Command Pattern brings several significant benefits:

- **Separation of Concerns:** Clearly separates orchestration logic from invoke logic, making the system more modular.
- **Flexibility and Extensibility:** Allows for easy swapping, extension, and customization of invoke logic without altering workflow structures.
- **Improved Maintainability:** Facilitates testing and debugging by isolating command logic within distinct units.

The `Command` interface class itself primarily defines the interface structure and thus does not contain specific instance fields.

| Method           | Description                                                                                         |
|------------------|-----------------------------------------------------------------------------------------------------|
| `invoke`        | Defines synchronous invoke logic to process inputs and return results; must be implemented by subclasses.|
| `a_invoke`      | Defines asynchronous invoke logic supporting streaming or concurrent processes; must be implemented by subclasses.|
| `to_dict`        | Serializes command configurations or state for persistence or debugging purposes; must be implemented by subclasses.|

The `Command` interface class utilizes an inner `Builder` class to facilitate structured and step-by-step construction of Command instances, enhancing readability and configurability.

Developers implement custom Commands tailored to specific logic or operational needs by inheriting from this base Command class and overriding the required methods. This approach empowers developers to flexibly craft specialized behaviors while maintaining consistency across the workflow invoke environment.

The concrete implementation of `Command` interface should be with its associated tools. Here are some examples.

## LLM Response Command and LLM Stream Command

[`LLMResponseCommand`](https://github.com/binome-dev/graphite/blob/main/tests_integration/rag_assistant/tools/rags/rag_response_command.py) encapsulates synchronous LLM usage within a command, allowing a node to request the LLM for a response.

Fields:

| Field | Description                                                |
|-------|------------------------------------------------------------|
| `llm` | An `LLM` instance (e.g., OpenAI) that provides the response|

Key methods are:

| Method                                        | Description                                                                                          |
|-----------------------------------------------|------------------------------------------------------------------------------------------------------|
| `invoke(invoke_context, input_data)`      | Synchronously obtains a single response from the LLM based on the provided messages.                 |
| `a_invoke(invoke_context, input_data)`    | Asynchronously streams generated messages from the LLM.                                              |
| `to_dict()`                                   | Serializes the command’s state, including its associated LLM configuration.                          |

The [`LLMStreamResponseCommand`](https://github.com/binome-dev/graphite/blob/main/grafi/tools/llms/llm_stream_response_command.py) specializes `LLMResponseCommand` for stream use cases where synchronous responses must be disabled, and only relies exclusively on asynchronous streaming via a_invoke.

## Function Calling Command

[`FunctionCallCommand`](https://github.com/binome-dev/graphite/blob/main/grafi/tools/function_calls/function_call_command.py) is a concrete implementation of the Command interface that allows a Node to call a `FunctionCallTool`. By assigning a `FunctionCallTool` to the command, the Node can trigger function invoke without needing to know how arguments are parsed or how the function is actually invoked.

Fields:

| Field             | Description                                                                                 |
|-------------------|---------------------------------------------------------------------------------------------|
| `function_tool`   | A `FunctionCallTool` instance that encapsulates the registered function and its invoke logic.|

Methods:

| Method                                            | Description                                                                                                            |
|---------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| `invoke(invoke_context, input_data)`          | Invokes the `function_tool`'s synchronous `invoke` method, returning a list of resulting `Message` objects.           |
| `a_invoke(invoke_context, input_data)`        | Calls the `function_tool`'s asynchronous `a_invoke`, yielding one or more `Message` objects in an async generator.    |
| `get_function_specs()`                            | Retrieves the function specifications (schema, name, parameters) from the underlying `function_tool`.                  |
| `to_dict()`                                       | Serializes the command’s current state, including the `function_tool` configuration.                                   |

By passing a `FunctionCallTool` to the `function_tool` field, you can seamlessly integrate function-based logic into a Node’s orchestration without embedding invoke details in the Node or the tool consumer. This separation keeps workflows flexible and easy to extend.

## Embedding Response Command and RAG Response Command

[`EmbeddingResponseCommand`](https://github.com/binome-dev/graphite/blob/main/tests_integration/embedding_assistant/tools/embeddings/embedding_response_command.py) encapsulates a `RetrievalTool` for transforming input messages into embeddings, retrieving relevant content, and returning it as a `Message`. This command is used by `EmbeddingRetrievalNode`.

`EmbeddingResponseCommand` fields:

| Field                 | Description                                                                      |
|-----------------------|----------------------------------------------------------------------------------|
| `retrieval_tool`      | A `RetrievalTool` instance for embedding-based lookups, returning relevant data  |

`EmbeddingResponseCommand` methods:

| Method                                        | Description                                                                                                    |
|-----------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| `invoke(invoke_context, input_data)`      | Synchronously calls `retrieval_tool.invoke`, returning the resulting `Message`.                               |
| `a_invoke(invoke_context, input_data)`    | Asynchronously calls `retrieval_tool.a_invoke`, yielding one or more `Message` objects.                       |
| `to_dict()`                                   | Serializes the command’s state, including the `retrieval_tool` configuration.                                  |

[`RagResponseCommand`](https://github.com/binome-dev/graphite/blob/main/tests_integration/rag_assistant/tools/rags/rag_response_command.py) similarly delegates to a `RagTool` that performs retrieval-augmented generation. This command is used by `RagNode`.

`RagResponseCommand` fields:

| Field          | Description                                                                          |
|----------------|--------------------------------------------------------------------------------------|
| `rag_tool`     | A `RagTool` instance for retrieval-augmented generation.                             |

`RagResponseCommand` methods:

| Method                                        | Description                                                                                                          |
|-----------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `invoke(invoke_context, input_data)`      | Synchronously calls `rag_tool.invoke`, returning a `Message` with retrieval results.                                |
| `a_invoke(invoke_context, input_data)`    | Asynchronously invokes `rag_tool.a_invoke`, yielding partial or complete messages from the retrieval-augmented flow.|
| `to_dict()`                                   | Serializes the command’s state, reflecting the assigned `RagTool` configuration.                                     |

Both commands enable a node to delegate specialized retrieval operations to their respective tools, without needing to manage the internal logic of how embeddings or RAG processes are performed.

## Function Command

[`FunctionCommand`](https://github.com/binome-dev/graphite/blob/main/grafi/tools/functions/function_command.py) is a concrete implementation of the Command interface that allows a Node to invoke general function-based operations through a `FunctionTool`. This command provides a flexible framework for integrating custom function logic into event-driven workflows, enabling nodes to perform various computational tasks without embedding invoke details directly in the node logic.

`FunctionCommand` fields:

| Field           | Description                                                                          |
|-----------------|--------------------------------------------------------------------------------------|
| `function_tool` | A `FunctionTool` instance that encapsulates the function invoke logic.           |

`FunctionCommand` methods:

| Method                                        | Description                                                                                                    |
|-----------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| `invoke(invoke_context, input_data)`      | Synchronously calls `function_tool.invoke`, returning the resulting `Message`.                               |
| `a_invoke(invoke_context, input_data)`    | Asynchronously calls `function_tool.a_invoke`, yielding one or more `Message` objects.                       |
| `to_dict()`                                   | Serializes the command's state, including the `function_tool` configuration.                                  |

The `FunctionCommand` enables nodes to delegate function-based operations to their respective tools, maintaining clean separation between workflow orchestration and function invoke logic. This design allows for easy integration of various computational tasks while keeping the system modular and extensible.
