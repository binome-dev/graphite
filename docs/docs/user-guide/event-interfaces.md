# Event Interfaces

## Overview

Graphite uses a consistent event-driven interface pattern where components communicate exclusively through two primary event types:
- **PublishToTopicEvent**: Used to publish data to topics
- **ConsumeFromTopicEvent**: Used to consume data from topics

This design creates a clean separation of concerns and enables loose coupling between components.

## Interface Patterns

### Component Communication Flow

The event interface creates a bidirectional flow pattern:

```mermaid
graph LR
    A[Assistant/Workflow] -->|PublishToTopicEvent| B[Topics]
    B -->|ConsumeFromTopicEvent| C[Nodes]
    C -->|PublishToTopicEvent| D[Topics]
    D -->|ConsumeFromTopicEvent| A
```

### Component Interfaces

| Component | Input Type | Output Type | Description |
|-----------|------------|-------------|-------------|
| **Assistant** | `PublishToTopicEvent` | `List[ConsumeFromTopicEvent]` | Receives published events, returns consumed events |
| **Workflow** | `PublishToTopicEvent` | `List[ConsumeFromTopicEvent]` | Orchestrates nodes through event flow |
| **Node** | `List[ConsumeFromTopicEvent]` | `PublishToTopicEvent` | Consumes events, processes, publishes results |
| **Tool** | `Messages` | `Messages` | Transforms message data (used within nodes) |

## Event Structure

### PublishToTopicEvent

Published when a component sends data to a topic:

```python
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message

event = PublishToTopicEvent(
    publisher_name="ProcessorNode",
    publisher_type="node",
    invoke_context=InvokeContext(
        conversation_id="conversation-1",
        invoke_id="invoke-1",
        assistant_request_id="request-1",
    ),
    consumed_event_ids=["evt_1", "evt_2"],  # Events that led to this publication
    data=[Message(role="assistant", content="Processed result")]
)
```

### ConsumeFromTopicEvent

Created when data is consumed from a topic. It names its consumer, and the
publication it took by its topic and offset:

```python
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from grafi.topics.topic_types import TopicType

event = ConsumeFromTopicEvent(
    name="output_topic",  # Topic consumed from
    type=TopicType.DEFAULT_TOPIC_TYPE,
    offset=42,  # Offset of the publication consumed
    consumer_name="SummaryNode",  # The node (or workflow) consuming it
    consumer_type="node",
    invoke_context=InvokeContext(
        conversation_id="conversation-1",
        invoke_id="invoke-1",
        assistant_request_id="request-1",
    ),
    data=[Message(role="assistant", content="Processed result")]
)
```

## Implementation Examples

### Assistant Implementation

An `Assistant` runs its workflow and records its invoke and respond events,
from which an LLM's history is read on the next turn. An `invoke` of your own
calls `super().invoke(input_data, is_sequential, stream=stream)`, so those
events are recorded, and declares `Assistant.invoke`'s two overloads: see
[Assistant](assistant.md#invoke) for the whole override. One calling
`self.workflow.invoke(...)` itself records no assistant events, so the LLM
loses every earlier turn.

### Node Implementation

```python
from grafi.nodes.node import Node
from grafi.common.exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.decorators.record_decorators import record_node_invoke
from typing import List, AsyncGenerator

class ProcessorNode(Node):
    @record_node_invoke
    async def invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent]
    ) -> AsyncGenerator[PublishToTopicEvent, None]:
        """Process consumed events and publish the result, if any."""
        command = self.command  # None for a node without a tool.
        if command is None:
            raise NodeExecutionError(
                node_name=self.name,
                message="Cannot invoke a node without a tool.",
                invoke_context=invoke_context,
            )
        # Run the tool, through its command, on the input
        messages = await command.invoke(invoke_context, node_input)
        if messages:  # No output: nothing to publish.
            yield PublishToTopicEvent(
                publisher_name=self.name,
                publisher_type=self.type,
                invoke_context=invoke_context,
                consumed_event_ids=[event.event_id for event in node_input],
                data=messages
            )
```

### Workflow Integration

```python
from typing import AsyncGenerator, Union

from grafi.workflows.workflow import Workflow
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from grafi.runtime import Delta

class MyWorkflow(Workflow):
    async def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        """Execute workflow asynchronously."""
        # Initialize workflow with input event
        await self.init_workflow(input_data)

        # Process nodes until completion
        while not self._invoke_queue.empty():
            node = self._invoke_queue.get()
            async for output in node.invoke(...):
                # Publish output to topics
                yield output
```

## Benefits of Event Interfaces

### 1. Loose Coupling
Components don't need direct references to each other - they communicate through events and topics.

### 2. Traceability
Every event carries:
- `invoke_context`: Request correlation information

A `PublishToTopicEvent` also carries:
- `consumed_event_ids`: Chain of events that led to this event
- Publisher information: Source component details

A `ConsumeFromTopicEvent` names its consumer, and the topic and offset it
consumed.

### 3. Flexibility
- Easy to add new components without modifying existing ones
- Components can be tested in isolation
- Workflows can be composed dynamically

### 4. Observability
- Complete audit trail through event chain
- Easy to trace data flow through the system
- Built-in support for distributed tracing

### 5. Recovery
- Events can be replayed from any point
- Workflows can resume from interruption
- State can be reconstructed from event history

## Migration from Direct Invocation

If migrating from older patterns that used direct method calls:

**Old Pattern:**
```python
def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
    return self.workflow.invoke(invoke_context, input_data)
```

**New Pattern** (with `Assistant.invoke`'s two overloads above it, as
[Assistant](assistant.md#invoke) shows):
```python
async def invoke(
    self,
    input_data: PublishToTopicEvent,
    is_sequential: bool = False,
    *,
    stream: bool = False,
) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
    # Through Assistant.invoke, which records the events an LLM's history is
    # read from.
    async for output in super().invoke(input_data, is_sequential, stream=stream):
        yield output
```

Key changes:
1. Input is now a single `PublishToTopicEvent` instead of separate context and data
2. Output is an async generator yielding `ConsumeFromTopicEvent` objects
3. Context and data are embedded within the event objects
4. Method is now async and uses `async for` for streaming responses
5. Event IDs enable tracing the full processing chain

## Best Practices

1. **Always preserve event chains**: Include `consumed_event_ids` when creating a `PublishToTopicEvent`
2. **Use descriptive names**: Set meaningful `publisher_name` values for debugging
3. **Type your components**: Use proper type hints for event interfaces
4. **Handle streaming properly**: Use async generators for streaming responses
5. **Validate event data**: Ensure data types match expected formats

## See Also

- [Events System](./events/events.md) - Detailed event documentation
- [Topics](./topics/topic.md) - Topic-based messaging
- [Event-Driven Workflow](./event-driven-workflow.md) - Workflow orchestration
- [Node](./node.md) - Node component documentation