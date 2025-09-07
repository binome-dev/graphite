# Topic Base

The Graphite topic base system provides the foundational components for implementing topic-based messaging patterns. It enables publishers to send messages to named topics and consumers to receive messages based on configurable conditions, supporting decoupled communication between system components.

## Overview

The topic base system implements a publish-subscribe messaging pattern where:

- **Publishers**: Send messages to named topics
- **Consumers**: Subscribe to topics and receive messages
- **Conditions**: Filter messages based on custom logic
- **Offsets**: Track consumption progress for each consumer
- **Events**: Maintain a complete audit trail of all operations

## Core Components

### TopicBase

The base class for all topic implementations, providing core messaging functionality.

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique identifier for the topic |
| `type` | `str` | Topic type identifier |
| `condition` | `Callable[[Messages], bool]` | Function to filter publishable messages |
| `event_cache` | `TopicEventQueue` | Manages event storage and consumer offsets |
| `publish_event_handler` | `Optional[Callable]` | Handler for publish events |

#### Core Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `publish_data` | `(invoke_context, publisher_name, publisher_type, data, consumed_events) -> PublishToTopicEvent` | Publish messages to the topic (abstract) |
| `a_publish_data` | `(invoke_context, publisher_name, publisher_type, data, consumed_events) -> PublishToTopicEvent` | Async version of publish_data (abstract) |
| `can_consume` | `(consumer_name: str) -> bool` | Check if consumer has unread messages |
| `consume` | `(consumer_name: str) -> List[PublishToTopicEvent]` | Retrieve unread messages for consumer |
| `a_consume` | `(consumer_name: str, timeout: Optional[float]) -> List[TopicEvent]` | Async version of consume with timeout |
| `a_commit` | `(consumer_name: str, offset: int) -> None` | Commit processed messages up to offset |
| `reset` | `() -> None` | Reset topic to initial state |
| `a_reset` | `() -> None` | Async version of reset |
| `restore_topic` | `(topic_event: TopicEvent) -> None` | Restore topic from event |
| `a_restore_topic` | `(topic_event: TopicEvent) -> None` | Async version of restore_topic |

#### Utility Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `to_dict` | `() -> dict[str, Any]` | Serialize topic to dictionary |
| `serialize_callable` | `() -> dict` | Serialize condition function |

### TopicBaseBuilder

Builder pattern implementation for constructing topic instances.

#### Builder Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `name` | `(name: str) -> Self` | Set topic name with validation |
| `condition` | `(condition: Callable[[Messages], bool]) -> Self` | Set message filtering condition |

## Reserved Topics

The system includes reserved topic names for internal agent operations:

```python
AGENT_RESERVED_TOPICS = [
    "agent_input_topic",
    "agent_output_topic"
]
```

These topics cannot be used for custom topic names to avoid conflicts with system functionality. Additionally, the system supports workflow-specific topic types:

- `IN_WORKFLOW_INPUT_TOPIC_TYPE = "InWorkflowInput"`
- `IN_WORKFLOW_OUTPUT_TOPIC_TYPE = "InWorkflowOutput"`

## Message Publishing

The publishing mechanism is abstract and must be implemented by subclasses:

```python
def publish_data(
    self,
    invoke_context: InvokeContext,
    publisher_name: str,
    publisher_type: str,
    data: Messages,
    consumed_events: List[ConsumeFromTopicEvent],
) -> PublishToTopicEvent:
    """
    Publish data to the topic if it meets the condition.
    """
    raise NotImplementedError(
        "Method 'publish_data' must be implemented in subclasses."
    )
```

## Message Consumption

The topic system uses a sophisticated caching mechanism (`TopicEventQueue`) that manages consumed and committed offsets separately for reliable message processing.

### Consumption Check

```python
def can_consume(self, consumer_name: str) -> bool:
    """Check if consumer has unread messages."""
    return self.event_cache.can_consume(consumer_name)
```

### Message Retrieval

```python
def consume(self, consumer_name: str) -> List[PublishToTopicEvent | OutputTopicEvent]:
    """Retrieve unread messages for consumer."""
    # Get new events using the offset range
    new_events = self.event_cache.fetch(consumer_name)

    # Filter to only return PublishToTopicEvent instances for backward compatibility
    return [
        event
        for event in new_events
        if isinstance(event, (PublishToTopicEvent, OutputTopicEvent))
    ]
```

### Async Message Retrieval

```python
async def a_consume(
    self, consumer_name: str, timeout: Optional[float] = None
) -> List[TopicEvent]:
    """Asynchronously retrieve new/unconsumed messages for the given node."""
    return await self.event_cache.a_fetch(consumer_name, timeout=timeout)
```

### Offset Management

The system maintains two types of offsets:

- **Consumed Offset**: Tracks what has been fetched (advanced immediately on fetch)
- **Committed Offset**: Tracks what has been fully processed (advanced after processing)

```python
async def a_commit(self, consumer_name: str, offset: int) -> None:
    """Commit processed messages up to the specified offset."""
    await self.event_cache.a_commit_to(consumer_name, offset)
```

## Message Filtering

Topics support flexible message filtering through condition functions:

### Default Condition

```python
condition: Callable[[Messages], bool] = Field(default=lambda _: True)
```

### Condition Serialization

The system can serialize various types of condition functions:

```python
def serialize_callable(self) -> dict:
    """Serialize condition function for persistence."""
    if callable(self.condition):
        if inspect.isfunction(self.condition):
            if self.condition.__name__ == "<lambda>":
                # Lambda function
                try:
                    source = inspect.getsource(self.condition).strip()
                except (OSError, TypeError):
                    source = "<unable to retrieve source>"
                return {"type": "lambda", "code": source}
            else:
                # Named function
                return {"type": "function", "name": self.condition.__name__}
        elif inspect.isbuiltin(self.condition):
            return {"type": "builtin", "name": self.condition.__name__}
        elif hasattr(self.condition, "__call__"):
            return {
                "type": "callable_object",
                "class_name": self.condition.__class__.__name__,
            }
    return {"type": "unknown"}
```

## Topic State Management

### Reset Topic

```python
def reset(self) -> None:
    """Reset the topic to its initial state."""
    self.event_cache = TopicEventQueue(self.name)

async def a_reset(self) -> None:
    """Asynchronously reset the topic to its initial state."""
    self.event_cache.reset()
    self.event_cache = TopicEventQueue(self.name)
```

### Restore Topic

```python
def restore_topic(self, topic_event: TopicEvent) -> None:
    """Restore a topic from a topic event."""
    if isinstance(topic_event, PublishToTopicEvent) or isinstance(
        topic_event, OutputTopicEvent
    ):
        self.event_cache.put(topic_event)
    elif isinstance(topic_event, ConsumeFromTopicEvent):
        self.event_cache.fetch(
            consumer_id=topic_event.consumer_name, offset=topic_event.offset + 1
        )
        self.event_cache.commit_to(topic_event.consumer_name, topic_event.offset)

async def a_restore_topic(self, topic_event: TopicEvent) -> None:
    """Asynchronously restore a topic from a topic event."""
    if isinstance(topic_event, PublishToTopicEvent) or isinstance(
        topic_event, OutputTopicEvent
    ):
        await self.event_cache.a_put(topic_event)
    elif isinstance(topic_event, ConsumeFromTopicEvent):
        # Fetch the events for the consumer and commit the offset
        await self.event_cache.a_fetch(
            consumer_id=topic_event.consumer_name, offset=topic_event.offset + 1
        )
        await self.event_cache.a_commit_to(
            topic_event.consumer_name, topic_event.offset
        )
```

## Serialization

### Topic Serialization

```python
def to_dict(self) -> dict[str, Any]:
    return {"name": self.name, "condition": self.serialize_callable()}
```

## Builder Pattern Usage

### Basic Topic Creation

```python
from grafi.topics.topic_base import TopicBaseBuilder

# Create topic with builder
topic = (TopicBaseBuilder()
    .name("processing_results")
    .condition(lambda msgs: len(msgs) > 0)
    .build())
```

### Validation

The builder includes validation for reserved topic names:

```python
def name(self, name: str) -> Self:
    if name in AGENT_RESERVED_TOPICS:
        raise ValueError(f"Topic name '{name}' is reserved for the agent.")
    self.kwargs["name"] = name
    return self
```

The topic base system provides the foundational structure for implementing topic-based messaging patterns in Graphite applications.
