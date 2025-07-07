# Command

The **Command** implements the Command Pattern in Graphite, providing a crucial abstraction layer that separates workflow orchestration (Nodes) from execution logic (Tools). Commands encapsulate the execution logic and data preparation, allowing nodes to delegate processing to tools without needing to understand the internal implementation details.

## Architecture Overview

The Command Pattern in Graphite creates a clear separation between:

- **Orchestration Layer**: Nodes manage workflow execution and topic-based messaging
- **Execution Layer**: Tools perform the actual processing (LLM calls, function execution, etc.)
- **Command Layer**: Commands bridge the gap, handling data transformation and tool invocation

This architecture enables flexible, testable, and maintainable workflows where components can be easily swapped, extended, or customized.

## Core Benefits

### 1. Separation of Concerns

Commands isolate tool invocation logic from workflow orchestration, making the system more modular and easier to understand.

### 2. Data Transformation

Commands handle the complex task of transforming topic event data into the format expected by tools, including:

- Message aggregation from multiple topic events
- Conversation history reconstruction
- Tool call message ordering
- Context-specific data preparation

### 3. Automatic Tool Registration

The `@use_command` decorator provides automatic command registration for tool types:

```python
@use_command(LLMCommand)
class MyLLMTool(LLM):
    # Tool implementation
    pass

# Command is automatically created when tool is used
command = Command.for_tool(my_llm_tool)  # Returns LLMCommand instance
```

### 4. Flexibility and Extensibility

Tools can be easily swapped without changing workflow structure, and new command types can be added for specialized processing needs.

### 5. Improved Testability

Commands can be tested independently from workflows and nodes, enabling better unit testing and debugging.

## Base Command Class

The `Command` base class provides the foundational interface:

```python
class Command(BaseModel):
    """Base command class for tool execution."""

    tool: Tool

    def invoke(self, invoke_context: InvokeContext,
               input_data: List[ConsumeFromTopicEvent]) -> Messages:
        """Synchronous tool invocation."""
        return self.tool.invoke(
            invoke_context,
            self.get_tool_input(invoke_context, input_data)
        )

    async def a_invoke(self, invoke_context: InvokeContext,
                       input_data: List[ConsumeFromTopicEvent]) -> MsgsAGen:
        """Asynchronous tool invocation."""
        async for message in self.tool.a_invoke(
            invoke_context,
            self.get_tool_input(invoke_context, input_data)
        ):
            yield message

    def get_tool_input(self, invoke_context: InvokeContext,
                       input_data: List[ConsumeFromTopicEvent]) -> Messages:
        """Transform topic events into tool input format."""
        all_messages = []
        for event in input_data:
            all_messages.extend(event.data)
        return all_messages
```

### Key Methods

| Method | Description |
|--------|-------------|
| `invoke` | Synchronous tool execution with data transformation |
| `a_invoke` | Asynchronous tool execution supporting streaming |
| `get_tool_input` | Transforms topic events into tool-compatible format |
| `to_dict` | Serializes command state for persistence or debugging |

### Factory Method

The `Command.for_tool()` factory method automatically selects the appropriate command class:

```python
# Automatic command selection based on tool type
llm_command = Command.for_tool(my_llm_tool)      # Returns LLMCommand
func_command = Command.for_tool(my_func_tool)    # Returns FunctionCallCommand
base_command = Command.for_tool(generic_tool)    # Returns Command
```

## Built-in Command Types

### LLMCommand

The `LLMCommand` handles complex data preparation for Language Model tools, including conversation history and tool call ordering. This command automatically applies sophisticated data preparation logic specific to LLM interactions.

**Key Features**:

- **Conversation History Reconstruction**: Retrieves and orders conversation history from previous assistant responses
- **Tool Call Message Ordering**: Ensures tool call responses immediately follow their corresponding LLM tool calls
- **Event Graph Processing**: Uses topological sorting to maintain proper message chronology
- **Context-Aware Data Preparation**: Filters out current request data to prevent circular references

**Data Processing Flow**:

1. Retrieves conversation history from the event store
2. Filters out messages from the current assistant request
3. Processes current topic events using event graph topology
4. Reorders tool call messages to follow their corresponding LLM messages
5. Combines and sorts all messages by timestamp

**Use Cases**:

- Conversational AI assistants with memory
- Context-aware language model interactions

### FunctionCallCommand

The `FunctionCallCommand` processes tool call messages for function execution, extracting unprocessed function calls from topic events.

**Key Features**:

- **Unprocessed Tool Call Detection**: Identifies tool calls that haven't been processed yet
- **Duplicate Prevention**: Filters out tool call messages that already have responses
- **Event Processing**: Handles messages from nodes in the workflow

**Data Processing Logic**:

```python
def get_tool_input(self, _: InvokeContext,
                   node_input: List[ConsumeFromTopicEvent]) -> Messages:
    # Extract all input messages from events
    input_messages = [msg for event in node_input for msg in event.data]

    # Find already processed tool calls
    processed_tool_calls = [msg.tool_call_id for msg in input_messages if msg.tool_call_id]

    # Return only unprocessed tool call messages
    tool_calls_messages = []
    for message in input_messages:
        if (message.tool_calls and
            message.tool_calls[0].id not in processed_tool_calls):
            tool_calls_messages.append(message)

    return tool_calls_messages
```

**Use Cases**:

- Function calling in LLM workflows
- Tool execution based on model-generated tool calls  
- Structured function invocation with parameter extraction

## Example Command Implementations

These examples show commands from test integrations that demonstrate specialized data preparation patterns.

### EmbeddingResponseCommand

The `EmbeddingResponseCommand` is used in test integrations for embedding-based retrieval tasks. It extracts the latest message for embedding processing:

```python
class EmbeddingResponseCommand(Command):
    def get_tool_input(self, invoke_context: InvokeContext,
                       node_input: List[ConsumeFromTopicEvent]) -> Messages:
        # Only consider the last message contains the content to query
        latest_event_data = node_input[-1].data
        latest_message = (
            latest_event_data[0]
            if isinstance(latest_event_data, list)
            else latest_event_data
        )
        return [latest_message]
```

**Key Features**:

- **Latest Message Extraction**: Focuses on the most recent message for processing
- **Simple Data Preparation**: Minimal transformation for embedding queries

### RagResponseCommand

The `RagResponseCommand` is used in test integrations for retrieval-augmented generation tasks. Similar to `EmbeddingResponseCommand`, it extracts the latest message:

```python
class RagResponseCommand(Command):
    def get_tool_input(self, invoke_context: InvokeContext,
                       node_input: List[ConsumeFromTopicEvent]) -> Messages:
        # Only consider the last message contains the content to query
        latest_event_data = node_input[-1].data
        latest_message = (
            latest_event_data[0]
            if isinstance(latest_event_data, list)
            else latest_event_data
        )
        return [latest_message]
```

**Key Features**:

- **Query Focus**: Extracts the latest user query for RAG processing
- **Streamlined Input**: Provides clean input for retrieval-augmented generation

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

## Command Registration

### Using the @use_command Decorator

Register custom commands for specific tool types:

```python
from grafi.common.models.command import use_command

@use_command(MyCustomCommand)
class MySpecialTool(Tool):
    """Tool that requires special data preparation."""
    pass

class MyCustomCommand(Command):
    def get_tool_input(self, invoke_context: InvokeContext,
                       input_data: List[ConsumeFromTopicEvent]) -> Messages:
        # Custom data transformation logic
        return transformed_messages
```

### Registry Lookup

The command registry uses inheritance-based lookup:

```python
# Registry checks for exact match first
TOOL_COMMAND_REGISTRY[MySpecialTool] = MyCustomCommand

# Then checks parent classes
if isinstance(tool, RegisteredToolType):
    return AssociatedCommand(tool=tool)

# Falls back to base Command
return Command(tool=tool)
```

## Creating Custom Commands

### When to Create Custom Commands

Create custom commands when you need:

1. **Specialized Data Preparation**: Complex transformation of topic events into tool input
2. **Context-Specific Logic**: Tool invocation that depends on workflow context
3. **Multi-Source Data**: Aggregating data from multiple sources beyond topic events
4. **Custom Error Handling**: Specialized error processing or recovery logic
5. **Performance Optimization**: Optimized data processing for specific use cases

### Implementation Guide

#### 1. Define Your Custom Command

```python
from typing import List
from grafi.common.models.command import Command
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages

class DatabaseQueryCommand(Command):
    """Command for database query tools with caching and optimization."""

    def get_tool_input(self, invoke_context: InvokeContext,
                       input_data: List[ConsumeFromTopicEvent]) -> Messages:
        # Extract query parameters from messages
        query_messages = []
        for event in input_data:
            for message in event.data:
                if message.content and "query:" in message.content:
                    query_messages.append(message)

        # Add context-specific optimizations
        if invoke_context.metadata.get("use_cache"):
            query_messages = self._add_cache_hints(query_messages)

        return query_messages

    def _add_cache_hints(self, messages: Messages) -> Messages:
        """Add caching hints to query messages."""
        # Custom caching logic
        return messages
```

#### 2. Register the Command

```python
@use_command(DatabaseQueryCommand)
class DatabaseQueryTool(Tool):
    """Tool for executing database queries."""

    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        # Database query implementation
        pass
```

#### 3. Advanced Custom Command with Multiple Data Sources

```python
class MultiSourceCommand(Command):
    """Command that aggregates data from multiple sources."""

    def get_tool_input(self, invoke_context: InvokeContext,
                       input_data: List[ConsumeFromTopicEvent]) -> Messages:
        # 1. Get base messages from topic events
        base_messages = super().get_tool_input(invoke_context, input_data)

        # 2. Retrieve external context
        external_data = self._get_external_context(invoke_context)

        # 3. Combine and optimize
        combined_messages = self._combine_data_sources(
            base_messages,
            external_data,
            invoke_context
        )

        return combined_messages

    def _get_external_context(self, invoke_context: InvokeContext) -> Messages:
        """Retrieve additional context from external sources."""
        # Fetch from databases, APIs, files, etc.
        return external_messages

    def _combine_data_sources(self, base: Messages, external: Messages,
                              context: InvokeContext) -> Messages:
        """Intelligently combine multiple data sources."""
        # Custom combination logic
        return combined_messages
```

## Advanced Usage Patterns

### 1. Conditional Command Selection

```python
class ConditionalCommand(Command):
    """Command that adapts behavior based on context."""

    def get_tool_input(self, invoke_context: InvokeContext,
                       input_data: List[ConsumeFromTopicEvent]) -> Messages:
        if invoke_context.metadata.get("mode") == "streaming":
            return self._prepare_streaming_input(input_data)
        elif invoke_context.metadata.get("mode") == "batch":
            return self._prepare_batch_input(input_data)
        else:
            return super().get_tool_input(invoke_context, input_data)
```

### 2. Command with State Management

```python
class StatefulCommand(Command):
    """Command that maintains state across invocations."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state_cache = {}

    def get_tool_input(self, invoke_context: InvokeContext,
                       input_data: List[ConsumeFromTopicEvent]) -> Messages:
        request_id = invoke_context.assistant_request_id

        # Use cached state if available
        if request_id in self._state_cache:
            return self._update_with_cache(input_data, self._state_cache[request_id])

        # Create new state entry
        processed_data = self._process_fresh_input(input_data)
        self._state_cache[request_id] = processed_data

        return processed_data
```

### 3. Command with Error Recovery

```python
class ResilientCommand(Command):
    """Command with built-in error recovery."""

    async def a_invoke(self, invoke_context: InvokeContext,
                       input_data: List[ConsumeFromTopicEvent]) -> MsgsAGen:
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                tool_input = self.get_tool_input(invoke_context, input_data)
                async for message in self.tool.a_invoke(invoke_context, tool_input):
                    yield message
                break
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    # Yield error message as fallback
                    yield [Message(role="assistant", content=f"Error: {str(e)}")]
                else:
                    # Modify input for retry
                    input_data = self._prepare_retry_input(input_data, e)
```

## Best Practices

### 1. Keep Commands Focused

Each command should have a single, well-defined responsibility:

```python
# Good - Focused on LLM data preparation
class LLMCommand(Command):
    def get_tool_input(self, ...):
        # Only LLM-specific data preparation
        pass

# Avoid - Mixed responsibilities
class LLMAndDatabaseCommand(Command):  # Don't do this
    def get_tool_input(self, ...):
        # Both LLM and database logic
        pass
```

### 2. Use Meaningful Names

Command names should clearly indicate their purpose:

```python
# Good
class ConversationHistoryCommand(Command): pass
class FunctionCallProcessingCommand(Command): pass
class RealTimeDataCommand(Command): pass

# Avoid
class MyCommand(Command): pass
class SpecialCommand(Command): pass
```

### 3. Handle Edge Cases

Always consider edge cases in data preparation:

```python
def get_tool_input(self, invoke_context: InvokeContext,
                   input_data: List[ConsumeFromTopicEvent]) -> Messages:
    if not input_data:
        return []  # Handle empty input

    messages = []
    for event in input_data:
        if not event.data:
            continue  # Skip empty events

        # Validate message format
        valid_messages = [msg for msg in event.data if self._is_valid_message(msg)]
        messages.extend(valid_messages)

    return messages if messages else [Message(role="system", content="No valid input")]
```

### 4. Document Complex Logic

Use clear documentation for complex data transformations:

```python
def get_tool_input(self, invoke_context: InvokeContext,
                   input_data: List[ConsumeFromTopicEvent]) -> Messages:
    """
    Prepare LLM input with proper tool call ordering.

    Process:
    1. Retrieve conversation history excluding current request
    2. Process current topic events in topological order
    3. Ensure tool call messages immediately follow LLM tool calls
    4. Sort all messages by timestamp

    Args:
        invoke_context: Current invocation context
        input_data: Topic events from workflow

    Returns:
        Properly ordered messages for LLM consumption
    """
    # Implementation...
```

## Integration with Workflows

Commands integrate seamlessly with Graphite's event-driven workflows:

```python
# In a Node
@record_node_invoke
def invoke(self, invoke_context: InvokeContext,
           node_input: List[ConsumeFromTopicEvent]) -> Messages:
    # Command automatically handles data transformation
    response = self.command.invoke(invoke_context, node_input)
    return response

# Command selection happens automatically
node = Node.builder().tool(my_llm_tool).build()
# node.command is automatically set to LLMCommand(tool=my_llm_tool)
```

This architecture enables clean separation of concerns while maintaining the flexibility to customize data processing for specific use cases.
