# Topic Base

The Graphite topic base system provides the foundational components for implementing topic-based messaging patterns. It enables publishers to send messages to named topics and consumers to receive them in order, supporting decoupled communication between system components.

## Overview

The topic base system implements a publish-subscribe messaging pattern where:

- **Publishers**: Send messages to named topics
- **Consumers**: Subscribe to topics and receive messages
- **Routing**: A topic is a queue with no condition of its own; the publishing node's routes decide which topics an event goes to
- **Offsets**: Track consumption progress for each consumer
- **Events**: Maintain a complete audit trail of all operations

## Core Components

### TopicBase

The base class for all topic implementations, providing core messaging functionality.

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique identifier for the topic |
| `type` | `TopicType` | Topic type identifier (`TopicType.DEFAULT_TOPIC_TYPE` by default) |
| `event_queue` | `TopicEventQueue` | FIFO queue of the topic's events and consumer offsets, for using the topic on its own (in memory by default; never saved) |

#### Core Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `publish_data` | `async (publish_event: PublishToTopicEvent) -> PublishToTopicEvent` | Publish a source event to the topic and return the enqueued publication |
| `prepare_publication` | `(publish_event: PublishToTopicEvent) -> PublishToTopicEvent` | Build this topic's publication of a source event, without enqueueing it |
| `add_event` | `async (event: TopicEvent) -> Optional[TopicEvent]` | Enqueue a publication and return it with its offset set |
| `can_consume` | `async (consumer_name: str) -> bool` | Check if consumer has unread messages |
| `unconsumed_count` | `async (consumer_name: str) -> int` | Number of messages the consumer has not yet consumed |
| `consume` | `async (consumer_name: str, timeout: Optional[float] = None) -> List[TopicEvent]` | Retrieve unread messages for consumer |
| `commit` | `async (consumer_name: str, offset: int) -> None` | Commit processed messages up to offset |
| `reset` | `async () -> None` | Reset topic to initial state |
| `restore_topic` | `async (topic_event: TopicEvent) -> None` | Restore topic from event |

#### Utility Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `model_dump(mode="json")` | `() -> dict[str, Any]` | Save the topic as data: its class, name and type (its `event_queue` is left out). See [Manifests](../manifests.md). |

### TopicBaseBuilder

Builder pattern implementation for constructing topic instances.

#### Builder Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `name` | `(name: str) -> Self` | Set topic name |
| `type` | `(type_name: str) -> Self` | Set topic type |

## Topic Types

`grafi.topics.topic_types.TopicType` names what a topic is for; each topic
class sets its own:

- `DEFAULT_TOPIC_TYPE = "Topic"` (`Topic`)
- `AGENT_INPUT_TOPIC_TYPE = "AgentInputTopic"` (`InputTopic`)
- `AGENT_OUTPUT_TOPIC_TYPE = "AgentOutputTopic"` (`OutputTopic`)
- `IN_WORKFLOW_INPUT_TOPIC_TYPE = "InWorkflowInputTopic"` (`InWorkflowInputTopic`)
- `IN_WORKFLOW_OUTPUT_TOPIC_TYPE = "InWorkflowOutputTopic"` (`InWorkflowOutputTopic`)
- `NONE_TOPIC_TYPE = "NoneTopic"`

## Message Publishing

`publish_data(publish_event)` publishes a source event to the topic and returns
the enqueued publication. It is built from two steps:

- `prepare_publication(publish_event)` copies the event with this topic's name
  and type, a fresh `event_id`, and the source event's ID in `emission_id`.
- `add_event(publication)` enqueues it and returns it with its offset set.

A workflow run keeps its topics' events itself and calls only
`prepare_publication()`, so building a workflow with a topic that overrides any
other public `TopicBase` instance method (`publish_data()`, `consume()`,
`commit()` and the like), or that has a custom
`event_queue`, raises `WorkflowError`: those are for using a topic on its own.
To transform or validate a publication, override `prepare_publication()`: it
runs before anything is stored.

## Message Consumption

The topic's `event_queue` (a `TopicEventQueue`) manages consumed and committed offsets separately for reliable message processing.

### Consumption Check

```python
async def can_consume(self, consumer_name: str) -> bool:
    """Check if consumer has unread messages."""
    return await self.event_queue.can_consume(consumer_name)
```

### Message Retrieval

```python
async def consume(
    self, consumer_name: str, timeout: Optional[float] = None
) -> List[TopicEvent]:
    """Retrieve unread messages for this consumer."""
    return await self.event_queue.fetch(consumer_name, timeout=timeout)
```

### Offset Management

The system maintains two types of offsets:

- **Consumed Offset**: Tracks what has been fetched (advanced immediately on fetch)
- **Committed Offset**: Tracks what has been fully processed (advanced after processing)

```python
async def commit(self, consumer_name: str, offset: int) -> None:
    """Commit processed messages up to the specified offset."""
    await self.event_queue.commit_to(consumer_name, offset)
```

## Routing

A topic has no condition: it enqueues every publication it is given. Which
topics an event goes to is decided by the node publishing it, whose
`publish_to(topic, when=...)` routes each take an optional predicate on the
outgoing `PublishToTopicEvent` (by default, every event). Reusable predicates,
such as `has_tool_call` and `has_text_response`, live in
`grafi.nodes.conditions`. See [Node](../node.md).

```python
from grafi.nodes.conditions import has_text_response
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.node import Node

node = (
    Node.builder()
    .name("LLMNode")
    .subscribe(agent_input_topic)
    .tool(llm_tool)
    .publish_to(function_call_topic, when=has_tool_call)
    .publish_to(agent_output_topic, when=has_text_response)
    .build()
)
```

## Topic State Management

### Reset Topic

```python
async def reset(self) -> None:
    """Asynchronously reset the topic to its initial state."""
    await self.event_queue.reset()
```

### Restore Topic

```python
async def restore_topic(self, topic_event: TopicEvent) -> None:
    """Asynchronously restore a topic from a topic event."""
    if isinstance(topic_event, PublishToTopicEvent):
        await self.event_queue.put(topic_event)
    elif isinstance(topic_event, ConsumeFromTopicEvent):
        # Restore the consumer's cursor to the recorded commit point.
        await self.event_queue.restore_consumer(
            consumer_id=topic_event.consumer_name,
            committed_offset=topic_event.offset,
        )
```

## Serialization

A topic is saved as data with `model_dump(mode="json")`, and loaded back with
`TopicBase.model_validate(data)`, as the class it names:

```python
Topic(name="processing_results").model_dump(mode="json")
# {"class": "grafi.topics.topic_impl.topic:Topic",
#  "name": "processing_results", "type": "Topic"}
```

Nodes refer to topics by name, and a workflow saves its topics with it. See
[Manifests](../manifests.md).

## Builder Pattern Usage

### Basic Topic Creation

```python
from grafi.topics.topic_impl.topic import Topic

# Create topic with builder
topic = (Topic.builder()
    .name("processing_results")
    .build())
```

The topic base system provides the foundational structure for implementing topic-based messaging patterns in Graphite applications.
