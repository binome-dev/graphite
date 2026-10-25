# FunctionCallTool

`FunctionCallTool` lets a Language Model (LLM) call Python functions. It answers each tool call it is given with exactly one `role="tool"` message: what the function returned, as text, or, if the call failed, the error, so the LLM can recover.

This design greatly reduces the complexity of integrating advanced logic: the LLM simply issues a request to invoke a function, and the tool handles the invocation details behind the scenes.

## Fields

| Field               | Description                                                                                   |
|---------------------|-----------------------------------------------------------------------------------------------|
| `name`             | Descriptive identifier (defaults to `"FunctionCallTool"`).                                       |
| `type`             | Tool type (defaults to `"FunctionCallTool"`).                                                    |
| `function_specs`   | The `FunctionSpec`s the tool is given, of functions it calls elsewhere, such as an MCP server's; saved when not empty. The specs of its own functions are derived, not held here (see `get_function_specs`). |
| `functions`        | The functions the tool is given, such as with the builder's `function()`, by name; saved by import path. Its class's `@llm_function` methods are not held here: they load with its class, and the tool calls them beside these (a given function replaces a method of the same name). |
| `on_error`         | `"return"` (default) answers a failed call with its error; `"raise"` fails the node with `FunctionCallException` instead. |
| `oi_span_type`     | Semantic tracing attribute (`TOOL`) for observability.                                        |

## Methods

| Method               | Description                                                                                                              |
|----------------------|--------------------------------------------------------------------------------------------------------------------------|
| `function` (Builder Class) | Builder method to register a function, beside the class's own `@llm_function` methods. Automatically applies `@llm_function` if not already decorated. |
| `on_error` (Builder Class) | Builder method to set `on_error`.                                                                                       |
| `get_function_specs` | What the LLM is offered: the specs the tool derives, then those it is given, once each by name. |
| `derived_specs` | The specs the tool derives, by name, never saved: each function's, named as it is keyed. A subclass offering a function it makes from its fields overrides it, as the agent-calling and synthetic tools do, and as one that appended specs in `model_post_init` before should now. Where a function and such a spec share a name, the function wins, offered and called. |
| `invoke`          | Answers every tool call in its input messages, concurrently, and returns one `role="tool"` message per call, in the calls' order (none without calls). |
| `call_function`   | `async`: called for each function the tool offers (see `get_function_specs`, a spec given or derived) but does not have (its class's `@llm_function` methods and its `functions`), with the LLM's arguments; it returns what the function returns, a value or a generator. By default it raises `LookupError`, answered `No function`. Override it to call functions elsewhere, as the MCP, agent-calling and synthetic tools do, and give the tool the specs of those functions as `function_specs`, or derive them; an override answers only the names it knows and passes the rest to `super().call_function(...)`, as the agent-calling and synthetic tools answer only their `agent_name` and `tool_name`. The tool calls its own functions itself, validated against their signatures, a sync one in a worker thread. |
| `model_dump(mode="json")` | Saves the tool as data: its class, the functions given to it, by import path, and the specs it was given; the specs it derives follow from it; one given for a function of its own (warned of when the tool is made or loaded) is saved as given. See [Manifests](../manifests.md). |

### Its Functions and Specs

The tool holds no spec of its own functions, and has no set-up step that makes
them. `functions` holds only the functions it is given; the functions it calls
itself are its class's `@llm_function` methods merged with those, a given one
replacing a method of the same name, and `derived_specs()` makes each one's spec
when it is read. `function_specs` holds only the specs of functions it calls
elsewhere. When the tool is made, a validator makes its derived specs once, so a
function no spec can be made of, such as a callable object or a
`functools.partial`, is refused with `TypeError`. A spec given for one of its
own functions is not offered, the function's own spec is, and a `UserWarning`
says so: give `function_specs` only the specs of functions it calls elsewhere.

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
- Hides from the LLM the parameters named `self` or `cls`, those starting with `_`, and those typed `InvokeContext`, which the tool passes the request's context

**Type Mapping**:

| Python Type | JSON Schema Type |
|-------------|------------------|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list` | `"array"` |
| `dict` | `"object"` |
| Other class | `"object"` |

## How It Works

1. **Function Registration**: Functions are registered either via the builder pattern using `.function()` method or by inheriting from `FunctionCallTool` and decorating methods with `@llm_function`. This automatically generates `FunctionSpec` objects describing each function's metadata.

2. **Automatic Discovery**: A subclass of `FunctionCallTool` registers the methods decorated with `@llm_function` in it and in its base classes; a method it redefines replaces its base's.

3. **Message Processing**: `invoke` answers every tool call in the messages it is given. In a workflow, the node's `FunctionCallCommand` gives it the calls not yet answered that name a function it offers, since one LLM reply can call functions of several tools. The workflow also makes, on each topic carrying calls, the first function-call node reading it (preferring one with `on_error="return"`) answer the calls there naming a function no LLM calling there was offered, so that every call reaching a function-call node gets a result.

4. **Function Execution**: The calls run concurrently, each to one result:
   - Arguments are parsed from the JSON in `tool_call.function.arguments`; for the tool's own functions they are then validated and coerced against the function's signature (with Pydantic's `validate_call`), so a parameter typed as a Pydantic model gets the model.
   - A parameter typed `InvokeContext` is passed the request's context. A function whose first parameter is `self`, such as an `@llm_function` method, is passed the tool; a method is called on the tool, so a subclass's override, decorated or not, is the one that runs.
   - The function may be sync or async, or a generator. Sync code runs in a worker thread, so a blocking call never stalls the event loop; calls run concurrently, so a tool's sync functions must be thread-safe. Sync code cannot be stopped midway: a stop or cancellation drops a call not yet started, and waits for one running to return, so sync code must not wait for the event loop. Each string a generator yields, and each `emit_delta` the function calls, reaches a caller streaming the run as a delta tagged with the call's `tool_call_id` (see [Runtime](../runtime.md#streaming)).
   - A failure, such as an unknown function, malformed JSON, invalid arguments or an exception the function raises, becomes the call's result, `Error: <type>: <message>`, which the LLM can act on. With `on_error="raise"`, it fails the node with `FunctionCallException` instead (a `ToolInvocationError` the function raised is raised as it is).

5. **Response Handling**: Each result becomes one `role="tool"` message linked by `tool_call_id`. Its content is always text: a string as it is, anything else (a number, a dict, a Pydantic model, None) as JSON. A generator's result is the text it yielded, joined, or the other values it yielded, one per line. With no tool call to answer, the tool returns no messages, and its node publishes nothing.

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

### Example - Calling Functions Elsewhere

A tool whose functions run elsewhere, such as on a service, overrides
`call_function` and is given the specs of what it offers. They are saved with
it, so a loaded tool offers them too. `call_function` is called only for those:
the tool calls its own functions, if it has any, itself.

```python
from typing import Any, Dict

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


class RemoteSearch(FunctionCallTool):
    async def call_function(
        self, invoke_context: InvokeContext, name: str, arguments: Dict[str, Any]
    ) -> Any:
        return f"found {arguments['q']}"  # Call the service here.


search = FunctionSpec(
    name="search",
    description="Search the web.",
    parameters=ParametersSchema(
        properties={"q": ParameterSchema(type="string")}, required=["q"]
    ),
)
tool = RemoteSearch(function_specs=[search])
```

### Example - Offering a Function Made From Fields

A tool offering a function it makes from its fields, rather than one it is
given, overrides `derived_specs()` to add that function's spec, and answers it
in `call_function`, as `AgentCallingTool` does. The spec is never saved: the
fields are, and a loaded tool derives it again.

```python
from typing import Any, Dict

from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


class TableLookup(FunctionCallTool):
    table: str = "customers"

    def derived_specs(self) -> Dict[str, FunctionSpec]:
        lookup = FunctionSpec(
            name=f"lookup_{self.table}",
            description=f"Look up a row of {self.table} by its id.",
            parameters=ParametersSchema(
                properties={"id": ParameterSchema(type="string")}, required=["id"]
            ),
        )
        return {lookup.name: lookup, **super().derived_specs()}  # Its own win.

    async def call_function(
        self, invoke_context: InvokeContext, name: str, arguments: Dict[str, Any]
    ) -> Any:
        if name != f"lookup_{self.table}":  # Not the lookup: not this tool's.
            return await super().call_function(invoke_context, name, arguments)
        return {"table": self.table, "id": arguments["id"]}  # Query here.

    @llm_function
    def count_rows(self) -> int:
        """Count the rows of the table."""
        return 42
```

It offers `lookup_customers` and `count_rows`. Returning only the spec it makes,
without merging `super().derived_specs()`, would stop it offering its class's
`@llm_function` methods, here `count_rows`, and the functions it is given.

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
| `api_key`       | Tavily API key (defaults to the `TAVILY_API_KEY` environment variable; saved as `{"env": "TAVILY_API_KEY"}`). The `client` property creates the `TavilyClient` with it when first used. |
| `search_depth`  | Defines the search mode (either `"basic"` or `"advanced"`) for Tavily.                                           |
| `max_tokens`    | Limits the total size (in tokens) of the returned JSON string, preventing overly large responses.                |

**Usage Example**:

```python
tavily_tool = (
    TavilyTool.builder()  # The key is read from TAVILY_API_KEY.
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
| `mcp_config`        | Configuration dictionary for MCP server connections. A header or environment variable that holds a secret refers to a variable, as `"Bearer ${GITHUB_TOKEN}"`, expanded when connecting with the value it had when the tool was made (a variable unset or empty when the tool is made is read when it connects; unset or empty then, the connection fails). |
| `resources`         | List of available MCP resources.                                               |
| `prompts`           | List of available MCP prompts.                                                 |

This tool automatically discovers available functions from connected MCP servers and makes them available for LLM function calling: building it (`await MCPTool.builder()...build()`) checks its arguments, lists its servers, then makes the tool with what they offer. It is saved with them, so loading it does not connect. Each call connects anew, through `grafi.tools.mcp_config.connect`, as `MCPFunctionTool`'s do, so calls hold no state in common, whichever conversation makes them; calls made at once to a stdio server each start its process, with no cap. A connection failing to close is logged, and fails no call answered. A function given to the tool with `.function(...)` is called itself, and wins over a server's of the same name.

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
| `agent_call`          | A callable that takes `(invoke_context, Message)` and returns a dictionary (e.g., `{"content": ...}`). Saved by import path. |
| `oi_span_type`        | OpenInference semantic attribute (`TOOL`), enabling observability and traceability.                                 |

**Methods**:

| Method           | Description                                                                                                                                                                                                 |
|------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `get_function_specs` | Returns the function specification (name, description, parameters) for the agent call, derived from its fields, beside any function given to it; a function named as the agent wins.                                                                                                                  |
| `call_function` | Passes a call of `agent_name` its `prompt` to `agent_call`, and returns the `content` of its answer; any other name is not the agent's, and goes to `FunctionCallTool.call_function` (a function given to the tool is called itself); `invoke`, inherited from `FunctionCallTool`, makes it a tool message. |

**Workflow Example**:

1. **Tool Registration**: An `AgentCallingTool` is constructed with details about the agent (`agent_name`, `agent_description`, etc.) and the callable (`agent_call`).
2. **Agent Invocation**: When an LLM includes a tool call referencing this agent's name, `invoke` receives the `prompt` and calls the agent.
3. **Response Conversion**: The agent's answer becomes a tool message linked to the call, which the workflow can then process or forward.

**Usage and Customization**:

- **Multi-Agent Systems**: By configuring multiple `AgentCallingTool` instances, you can facilitate dynamic exchanges among multiple agents, each specializing in a different task.
- **Runtime Flexibility**: Changing or updating the underlying `agent_call` logic requires no changes to the rest of the workflow.
- **Parameter Schemas**: `argument_description` ensures the LLM knows which arguments are required and how they should be formatted.

By integrating `AgentCallingTool` into your event-driven workflow, you can build sophisticated multi-agent systems where each agent can be invoked seamlessly via structured function calls. This approach maintains a clear separation between the LLM's orchestration and the agents' invoke details.

## Synthetic Tool

`SyntheticTool` extends the `FunctionCallTool` that enables LLMs to generate synthetic or modeled data by leveraging another LLM as a data generator. Unlike traditional function call tools that execute predefined logic, `SyntheticTool` uses an LLM to produce plausible, schema-compliant, outputs based on input specifications—perfect for testing, prototyping, or generating realistic mock data.

**Fields**:

| Field                  | Description                                                                                                        |
|------------------------|--------------------------------------------------------------------------------------------------------------------|
| `name`                | Descriptive identifier, defaults to `"SyntheticTool"`.                                                              |
| `type`                | Tool type indicator, defaults to `"SyntheticTool"`.                                                                 |
| `tool_name`           | Name used for function registration and LLM tool calls.                                                             |
| `description`         | Explanation of what synthetic data this tool generates.                                                             |
| `input_model`         | Pydantic `BaseModel` class (saved by import path) or JSON schema dict defining expected input structure.            |
| `output_model`        | Pydantic `BaseModel` class (saved by import path) or JSON schema dict defining generated output structure.          |
| `model`               | OpenAI model to use for data generation (e.g., `"gpt-4o-mini"`).                                                    |
| `openai_api_key`      | API key for OpenAI authentication (defaults to the `OPENAI_API_KEY` environment variable; saved as a reference to it). |
| `oi_span_type`        | OpenInference semantic attribute (`TOOL`), enabling observability and traceability.                                 |

**Methods**:

| Method           | Description                                                                                                                                                                                                 |
|------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `get_function_specs` | Returns the function specification (name, description, input schema) for the synthetic tool, derived from its fields when it has an `input_model`, beside any function given to it. |
| `call_function` | Generates the output of a call of `tool_name` for its arguments with an LLM, as schema-compliant JSON; any other name goes to `FunctionCallTool.call_function` (a function given to the tool is called itself); `invoke`, inherited from `FunctionCallTool`, makes it a tool message. |
| `ensure_strict_schema`   | Static method that recursively adds `additionalProperties: false` to JSON schemas for OpenAI strict mode compatibility.                                                                                                                 |

**Workflow Example**:

1. **Schema Definition**: Define input and output schemas using either Pydantic models (type-safe Python) or JSON Schema dicts (flexible).
2. **Function Registration**: The tool automatically generates the `FunctionSpec`, enabling LLMs to discover and call the tool.
3. **Tool Invocation**: When an LLM invokes the tool with arguments:
    - A prompt is constructed with the arguments and the input/output schema specifications (the arguments are not validated against `input_model`: its schema is what the calling LLM is offered)
    - LLM generates synthetic data conforming to `output_model`
4. **Structured Output**:
    - **Pydantic Mode**: Uses OpenAI's `beta.chat.completions.parse()` with type safety
    - **JSON Schema Mode**: Uses `chat.completions.create()` with `strict: True` for schema validation
5. **Response Handling**: Generated data is returned as a `Message` object linked to the original `tool_call_id`.

**Usage and Customization**:

- **Flexible Schema Definition**: By supporting both Pydantic models and JSON schemas, you can choose type-safe Python development or dynamic schema-based configuration without changing the rest of your workflow.
- **Runtime Model Selection**: Easily swap between OpenAI models (e.g., `gpt-5-mini` for cost, `gpt-5` for quality) to balance generation quality and API costs without modifying tool logic.
- **Schema-Driven Generation**: Input and output schemas guide the LLM's data generation, ensuring consistent, validated outputs that conform to your exact specifications.
- **Composable Data Pipelines**: Chain multiple `SyntheticTool` instances where one tool's output becomes another's input, creating sophisticated data generation workflows.

With SyntheticTool, you can rapidly prototype data-driven workflows without building actual data sources, while maintaining full schema compliance and
type safety through Pydantic or JSON Schema validation.

## Best Practices

### Function Design

1. **Clear Documentation**: Always provide comprehensive docstrings for functions decorated with `@llm_function`. The LLM uses these descriptions to understand when and how to call your functions.

2. **Type Hints**: Use proper type hints for all parameters. These are used to generate accurate JSON schemas for function specifications.

3. **Error Handling**: An exception a function raises answers its call, so write messages the LLM can act on. Set `on_error="raise"` where a failure must stop the workflow instead.

### Tool Configuration

1. **Builder Pattern**: Use the builder pattern for complex tools that require multiple configuration options.

2. **Resource Management**: For tools that use external APIs or resources, implement proper resource management and cleanup.

3. **Token Management**: For tools that return large amounts of data, implement token or size limits to prevent overwhelming downstream components.

### Integration

1. **Command Registration**: Tools that extend `FunctionCallTool` automatically use the `FunctionCallCommand` through the `@use_command` decorator.

2. **Observability**: Leverage the built-in observability features by ensuring proper tool naming and type identification.

3. **Testing**: Write comprehensive tests for your function implementations, as they will be called dynamically by LLMs.

With these patterns and examples, you can create robust, reusable function call tools that integrate seamlessly into Graphite's event-driven architecture while maintaining clean separation of concerns and excellent observability.
