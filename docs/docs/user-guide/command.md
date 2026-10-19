# Command

A node runs its tool through a **command** (the Command pattern). The command
turns the events the node consumed into the tool's input, then streams the
tool's output back to the node:

```
consumed events ──▶ Command.get_tool_input ──▶ Tool.invoke ──▶ messages ──▶ node publishes
```

This keeps tools pure: a tool takes messages and yields messages. Everything
about where those messages come from, such as conversation history in the
event store or which tool calls are still waiting for a result, lives in the
command.

## The base command

```python
from grafi.tools.command import Command

class Command(BaseModel):
    tool: Tool

    async def get_tool_input(
        self, invoke_context: InvokeContext, input_data: List[ConsumeFromTopicEvent]
    ) -> Messages:
        """The consumed events' messages, as they are."""

    async def invoke(
        self, invoke_context: InvokeContext, input_data: List[ConsumeFromTopicEvent]
    ) -> MsgsAGen:
        """Stream the tool's output for that input."""
```

Most commands override only `get_tool_input`.

## Built-in commands

| Command | Used by | Tool input |
|---------|---------|------------|
| `Command` | Tools that name no command, such as `FunctionTool` | The consumed events' messages. |
| `LLMCommand` | Every `LLM` tool | The conversation's earlier requests and answers from the event store, then this request's messages in order, each tool call followed by its result. |
| `FunctionCallCommand` | Every `FunctionCallTool` | The tool calls no result answers yet that the tool answers, each message keeping only those calls: the calls to its own functions, and, for the node a workflow makes answer unknown calls on a topic, the calls there naming a function no LLM calling there was offered. |

## Choosing a tool's command

A tool class names its command with `@use_command`, and its subclasses inherit
it:

```python
from grafi.tools.command import Command, use_command

class LatestMessageCommand(Command):
    """Pass the tool only the latest message, such as a query to embed."""

    async def get_tool_input(self, invoke_context, input_data):
        return input_data[-1].data[-1:]

@use_command(LatestMessageCommand)
class RetrievalTool(Tool):
    ...

class MyRetrievalTool(RetrievalTool):  # Also runs through LatestMessageCommand.
    ...
```

A node picks its command when it is built, with `Command.for_tool(tool)`: the
command the tool's class names, or the base `Command`.

## When to write a command

Write a command when a tool needs input prepared from more than the consumed
messages, for example from the event store or from a filter over the
messages. Keep the tool itself free of that logic, so it stays reusable in
other workflows. The integration examples
[`EmbeddingResponseCommand`](https://github.com/binome-dev/graphite/blob/main/tests_integration/embedding_assistant/tools/embeddings/embedding_response_command.py)
and
[`RagResponseCommand`](https://github.com/binome-dev/graphite/blob/main/tests_integration/rag_assistant/tools/rags/rag_response_command.py)
both pass their tool the latest message only.
