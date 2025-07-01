# FunctionCallTool

`FunctionCallTool` is designed to allow Language Models (LLMs) to invoke specific Python functions directly through JSON-formatted calls. When a message from the LLM references a particular function name along with arguments, `FunctionCallTool` checks if it has a function matching that name and, if so, invokes it.

This design greatly reduces the complexity of integrating advanced logic: the LLM simply issues a request to invoke a function, and the tool handles the invocation details behind the scenes.

## Fields

| Field               | Description                                                                                   |
|---------------------|-----------------------------------------------------------------------------------------------|
| `name`             | Descriptive identifier (defaults to `"FunctionCallTool"`).                                       |
| `type`             | Tool type (defaults to `"FunctionCallTool"`).                                                    |
| `function_specs`   | List of `FunctionSpec` objects describing registered functions and their parameters.          |
| `functions`        | Dictionary mapping function names to their callable implementations.                           |
| `oi_span_type`     | Semantic tracing attribute (`TOOL`) for observability.                                        |

## Methods

| Method               | Description                                                                                                              |
|----------------------|--------------------------------------------------------------------------------------------------------------------------|
| `function` (Builder Class) | Builder method to register a function. Automatically applies `@llm_function` if not already decorated.                   |
| `get_function_specs` | Retrieves detailed metadata about registered functions (including parameter info), enabling structured LLM-based function calls. |
| `invoke`            | Evaluates incoming messages for tool calls, matches them to registered functions, and executes with JSON arguments.  |
| `a_invoke`          | Asynchronous equivalent to `invoke`, allowing concurrency and awaiting coroutine functions.                               |
| `to_messages`       | Converts invoke results into `Message` objects with proper `tool_call_id` linkage.                          |
| `to_dict`            | Serializes the `FunctionCallTool` instance, listing function specifications for debugging or persistence.                    |

## LLM Function Decorator

### @llm_function

The `@llm_function` decorator exposes methods to Language Learning Models by automatically generating function specifications.

**Location**: `grafi.common.decorators.llm_function`

**Purpose**:

- Extracts function metadata (name, docstring, parameters, type hints)
- Constructs a `FunctionSpec` object with JSON Schema-compatible parameter descriptions
- Stores the specification as a `_function_spec` attribute on the decorated function

**Usage**:

```python
from grafi.common.decorators.llm_function import llm_function

@llm_function
def calculate_sum(x: int, y: int, precision: float = 0.1) -> float:
    """
    Calculate the sum of two numbers with optional precision.

    Args:
        x (int): The first number to add.
        y (int): The second number to add.
        precision (float, optional): Precision level. Defaults to 0.1.

    Returns:
        float: The sum of x and y.
    """
    return float(x + y)
```

**Features**:

- Automatically maps Python types to JSON Schema types
- Extracts parameter descriptions from docstrings
- Marks parameters without defaults as required
- Supports type hints for comprehensive schema generation

**Type Mapping**:

| Python Type | JSON Schema Type |
|-------------|------------------|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list` | `"array"` |
| `dict` | `"object"` |
| Other | `"string"` (default) |

## How It Works

1. **Function Registration**: Functions are registered either via the builder pattern using `.function()` method or by inheriting from `FunctionCallTool` and decorating methods with `@llm_function`. This automatically generates `FunctionSpec` objects describing each function's metadata.

2. **Automatic Discovery**: When inheriting from `FunctionCallTool`, the `__init_subclass__` method automatically discovers all methods decorated with `@llm_function` and adds them to the `functions` dictionary and `function_specs` list.

3. **Message Processing**: When `invoke` or `a_invoke` receives messages, it examines the `tool_calls` field in the first message to find function calls that match registered function names.

4. **Function Execution**: For each matching tool call:
   - Arguments are parsed from JSON in the `tool_call.function.arguments` field
   - The corresponding function is called with the parsed arguments
   - Results are converted to `Message` objects with the appropriate `tool_call_id`

5. **Response Handling**: The `to_messages` method formats function results into proper `Message` objects, maintaining the link between function calls and responses through `tool_call_id`.

## Usage and Customization

- **Builder Pattern**: Use the builder's `.function(...)` method to assign the function you want to expose. This ensures your function is properly decorated if not already.
- **Flexible**: By simply swapping out the underlying callable, you can quickly adapt to new or updated logic without modifying the rest of the workflow.
- **Observability**: Because `FunctionCallTool` implements the `Tool` interface and integrates with the event-driven architecture, all invocations can be monitored and logged.

With `FunctionCallTool`, you can integrate specialized Python functions into an LLM-driven workflow with minimal extra overhead. As your system grows and evolves, it provides a clean way to add or modify functionality while retaining a uniform interaction pattern with the LLM.

## Implementation Examples

### Example - Simple Weather Mock Tool

A straightforward implementation that inherits from `FunctionCallTool`. This class provides a simple way to use `FunctionCallTool` by just instantiating and calling the method:

```python
from grafi.common.decorators.llm_function import llm_function
from grafi.tools.function_calls.function_call_tool import FunctionCallTool

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

**Key Features**:

- Uses `@llm_function` decorator for automatic function registration
- Simple implementation for basic use cases
- Inherits all FunctionCallTool capabilities

### Example - Tavily Search Tool

[TavilyTool](https://github.com/binome-dev/graphite/blob/main/grafi/tools/function_calls/impl/tavily_tool.py) extends FunctionCallTool to provide web search capabilities through the Tavily API. This example demonstrates more complex configuration and a builder pattern for reusable tools.

**Key Features**:

- **Configurable Search Depth**: Supports both "basic" and "advanced" search modes
- **Token Management**: Limits response size to prevent overly large outputs
- **Builder Pattern**: Provides fluent configuration interface

**Fields**:

| Field           | Description                                                                                                      |
|-----------------|------------------------------------------------------------------------------------------------------------------|
| `name`          | Descriptive identifier for the tool (default: `"TavilyTool"`).                                                   |
| `type`          | Tool type indicator (default: `"TavilyTool"`).                                                                   |
| `client`        | Instance of the `TavilyClient` used for performing search queries.                                               |
| `search_depth`  | Defines the search mode (either `"basic"` or `"advanced"`) for Tavily.                                           |
| `max_tokens`    | Limits the total size (in tokens) of the returned JSON string, preventing overly large responses.                |

**Usage Example**:

```python
tavily_tool = (
    TavilyTool.builder()
    .api_key("YOUR_API_KEY")
    .search_depth("advanced")
    .max_tokens(6000)
    .build()
)
```

The `@llm_function` decorated `web_search_using_tavily` method accepts a query and optional max_results parameter, returning JSON-formatted search results with token management.

### Additional Search Tool Examples

#### DuckDuckGo Search Tool

[DuckDuckGoTool](https://github.com/binome-dev/graphite/blob/main/grafi/tools/function_calls/impl/duckduckgo_tool.py) provides web search functionality using the DuckDuckGo Search API, offering a privacy-focused alternative to other search engines.

**Key Features**:

- **Privacy-focused Search**: Uses DuckDuckGo's API for searches without tracking
- **Configurable Parameters**: Supports custom headers, proxy settings, and timeout configurations
- **Flexible Result Limits**: Allows both fixed and dynamic result count settings

**Fields**:

| Field               | Description                                                                     |
|---------------------|---------------------------------------------------------------------------------|
| `name`              | Tool identifier (default: `"DuckDuckGoTool"`).                                 |
| `type`              | Tool type (default: `"DuckDuckGoTool"`).                                       |
| `fixed_max_results` | Optional fixed maximum number of results to return.                            |
| `headers`           | Optional custom headers for requests.                                          |
| `proxy`             | Optional proxy server configuration.                                           |
| `timeout`           | Request timeout in seconds (default: 10).                                     |

**Usage Example**:

```python
duckduckgo_tool = (
    DuckDuckGoTool.builder()
    .fixed_max_results(10)
    .timeout(15)
    .build()
)
```

#### Google Search Tool

[GoogleSearchTool](https://github.com/binome-dev/graphite/blob/main/grafi/tools/function_calls/impl/google_search_tool.py) extends FunctionCallTool to provide web search functionality using the Google Search API with advanced configuration options.

**Key Features**:

- **Language Support**: Configurable language settings for international searches
- **Result Customization**: Fixed or dynamic result count limits
- **Advanced Configuration**: Support for custom headers, proxy, and timeout settings

**Fields**:

| Field               | Description                                                                     |
|---------------------|---------------------------------------------------------------------------------|
| `name`              | Tool identifier (default: `"GoogleSearchTool"`).                               |
| `type`              | Tool type (default: `"GoogleSearchTool"`).                                     |
| `fixed_max_results` | Optional fixed maximum number of results.                                      |
| `fixed_language`    | Optional fixed language code for searches.                                     |
| `headers`           | Optional custom headers for requests.                                          |
| `proxy`             | Optional proxy server configuration.                                           |
| `timeout`           | Request timeout in seconds (default: 10).                                     |

**Usage Example**:

```python
google_tool = (
    GoogleSearchTool.builder()
    .fixed_max_results(8)
    .fixed_language("en")
    .timeout(20)
    .build()
)
```

#### MCP (Model Context Protocol) Tool

[MCPTool](https://github.com/binome-dev/graphite/blob/main/grafi/tools/function_calls/impl/mcp_tool.py) provides integration with Model Context Protocol servers, enabling access to external tools, resources, and prompts.

**Key Features**:

- **Dynamic Function Discovery**: Automatically discovers and registers functions from MCP servers
- **Resource Access**: Provides access to MCP server resources and prompts
- **Extensible Configuration**: Supports custom MCP server configurations

**Fields**:

| Field               | Description                                                                     |
|---------------------|---------------------------------------------------------------------------------|
| `name`              | Tool identifier (default: `"MCPTool"`).                                        |
| `type`              | Tool type (default: `"MCPTool"`).                                              |
| `mcp_config`        | Configuration dictionary for MCP server connections.                           |
| `resources`         | List of available MCP resources.                                               |
| `prompts`           | List of available MCP prompts.                                                 |

This tool automatically discovers available functions from connected MCP servers and makes them available for LLM function calling.

## Agent Calling Tool

`AgentCallingTool` extends the `FunctionCallTool` concept to enable multi-agent systems, allowing an LLM to call another agent by name, pass relevant arguments (as a message prompt), and return the agent's response as part of the workflow.

**Fields**:

| Field                  | Description                                                                                                        |
|------------------------|--------------------------------------------------------------------------------------------------------------------|
| `name`                | Descriptive identifier, defaults to `"AgentCallingTool"`.                                                           |
| `type`                | Tool type indicator, defaults to `"AgentCallingTool"`.                                                              |
| `agent_name`          | Name of the agent to call; also used as the tool's name.                                                            |
| `agent_description`    | High-level explanation of what the agent does, used to generate function specs.                                    |
| `argument_description` | Describes the argument required (e.g., `prompt`) for the agent call.                                               |
| `agent_call`          | A callable that takes `(invoke_context, Message)` and returns a dictionary (e.g., `{"content": ...}`).           |
| `oi_span_type`        | OpenInference semantic attribute (`TOOL`), enabling observability and traceability.                                 |

**Methods**:

| Method           | Description                                                                                                                                                                                                 |
|------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `get_function_specs` | Returns the function specification (name, description, parameters) for the agent call.                                                                                                                  |
| `invoke`        | Synchronously processes incoming tool calls that match `agent_name`, passing the `prompt` to the `agent_call` callable and returning a list of `Message` objects.                                           |
| `a_invoke`      | Asynchronous variant of `invoke`; yields messages in an async generator for real-time or concurrent agent calls.                                                                                           |
| `to_messages`   | Creates a `Message` object from the agent's response, linking the output to `tool_call_id`.                                                                                                                 |
| `to_dict`        | Serializes all relevant fields, including agent metadata and the assigned callable, for debugging or persistence.                                                                                           |

**Workflow Example**:

1. **Tool Registration**: An `AgentCallingTool` is constructed with details about the agent (`agent_name`, `agent_description`, etc.) and the callable (`agent_call`).
2. **Agent Invocation**: When an LLM includes a tool call referencing this agent's name, `invoke` or `a_invoke` receives the `prompt` and calls the agent.
3. **Response Conversion**: The agent's return value is formed into a new `Message`, which the workflow can then process or forward.

**Usage and Customization**:

- **Multi-Agent Systems**: By configuring multiple `AgentCallingTool` instances, you can facilitate dynamic exchanges among multiple agents, each specializing in a different task.
- **Runtime Flexibility**: Changing or updating the underlying `agent_call` logic requires no changes to the rest of the workflow.
- **Parameter Schemas**: `argument_description` ensures the LLM knows which arguments are required and how they should be formatted.

By integrating `AgentCallingTool` into your event-driven workflow, you can build sophisticated multi-agent systems where each agent can be invoked seamlessly via structured function calls. This approach maintains a clear separation between the LLM's orchestration and the agents' invoke details.

## Best Practices

### Function Design

1. **Clear Documentation**: Always provide comprehensive docstrings for functions decorated with `@llm_function`. The LLM uses these descriptions to understand when and how to call your functions.

2. **Type Hints**: Use proper type hints for all parameters. These are used to generate accurate JSON schemas for function specifications.

3. **Error Handling**: Implement proper error handling in your functions, as exceptions will be propagated back through the tool invoke chain.

### Tool Configuration

1. **Builder Pattern**: Use the builder pattern for complex tools that require multiple configuration options.

2. **Resource Management**: For tools that use external APIs or resources, implement proper resource management and cleanup.

3. **Token Management**: For tools that return large amounts of data, implement token or size limits to prevent overwhelming downstream components.

### Integration

1. **Command Registration**: Tools that extend `FunctionCallTool` automatically use the `FunctionCallCommand` through the `@use_command` decorator.

2. **Observability**: Leverage the built-in observability features by ensuring proper tool naming and type identification.

3. **Testing**: Write comprehensive tests for your function implementations, as they will be called dynamically by LLMs.

With these patterns and examples, you can create robust, reusable function call tools that integrate seamlessly into Graphite's event-driven architecture while maintaining clean separation of concerns and excellent observability.
