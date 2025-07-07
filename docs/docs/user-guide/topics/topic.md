# Topic

The `Topic` class is a concrete implementation of `TopicBase` that provides a complete message queue system for publishing and consuming messages within Graphite applications. It includes built-in logging, event handling, and condition-based message filtering.

## Overview

The `Topic` class extends `TopicBase` to provide:

- **Conditional Publishing**: Messages are only published if they meet the topic's condition
- **Event Handling**: Optional event handlers for publish operations
- **Logging Integration**: Automatic logging of publish operations
- **Builder Pattern**: Fluent API for topic configuration

## Core Components

### Topic Class

A complete topic implementation with publishing logic and event handling.

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `topic_events` | `List[TopicEvent]` | List of all topic events (overrides base) |
| `publish_event_handler` | `Optional[Callable[[PublishToTopicEvent], None]]` | Optional handler called after successful publishing |

*Inherits all fields from `TopicBase`: `name`, `condition`, `consumption_offsets`*

#### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `builder` | `() -> TopicBuilder` | Class method returning a TopicBuilder instance |
| `publish_data` | `(invoke_context, publisher_name, publisher_type, data, consumed_events) -> PublishToTopicEvent` | Publishes messages if condition is met |

*Inherits all methods from `TopicBase`: `can_consume`, `consume`, `reset`, `restore_topic`, etc.*

### TopicBuilder

Enhanced builder for `Topic` instances with additional configuration options.

#### Builder Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `publish_event_handler` | `(handler: Callable[[PublishToTopicEvent], None]) -> Self` | Set event handler for publish operations |

*Inherits all builder methods from `TopicBaseBuilder`: `name`, `condition`*

## Publishing Logic

### Conditional Publishing

The `publish_data` method implements condition-based publishing:

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
    Publishes a message's event ID to this topic if it meets the condition.
    """
    if self.condition(data):
        event = PublishToTopicEvent(
            invoke_context=invoke_context,
            topic_name=self.name,
            publisher_name=publisher_name,
            publisher_type=publisher_type,
            data=data,
            consumed_event_ids=[
                consumed_event.event_id for consumed_event in consumed_events
            ],
            offset=len(self.topic_events),
        )
        self.topic_events.append(event)
        if self.publish_event_handler:
            self.publish_event_handler(event)
        logger.info(
            f"[{self.name}] Message published with event_id: {event.event_id}"
        )
        return event
    else:
        logger.info(f"[{self.name}] Message NOT published (condition not met)")
        return None
```

### Publishing Workflow

1. **Condition Check**: Evaluate if messages meet the topic's condition
2. **Event Creation**: Create `PublishToTopicEvent` with metadata and offset
3. **Event Storage**: Add event to topic's event list
4. **Handler Execution**: Call publish event handler if configured
5. **Logging**: Log success or failure with appropriate message
6. **Return Result**: Return event on success, `None` on condition failure

## Usage Examples

### Basic Topic Creation

```python
from grafi.common.topics.topic import Topic

# Create simple topic
topic = Topic(name="notifications")

# Or use builder pattern
topic = (Topic.builder()
    .name("notifications")
    .condition(lambda msgs: len(msgs) > 0)
    .build())
```

### Topic with Event Handler

```python
def on_message_published(event: PublishToTopicEvent):
    print(f"Published message to {event.topic_name}: {event.data}")

topic = (Topic.builder()
    .name("alerts")
    .condition(lambda msgs: any("error" in msg.content.lower() for msg in msgs))
    .publish_event_handler(on_message_published)
    .build())
```

### Publishing Messages

```python
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message

# Create context and messages
context = InvokeContext()
messages = [Message(role="user", content="Hello world")]

# Publish to topic
event = topic.publish_data(
    invoke_context=context,
    publisher_name="my_publisher",
    publisher_type="application",
    data=messages,
    consumed_events=[]
)

if event:
    print(f"Published: {event.event_id}")
else:
    print("Message did not meet condition")
```

### Message Consumption

```python
# Check for new messages
if topic.can_consume("consumer_1"):
    messages = topic.consume("consumer_1")
    for message in messages:
        print(f"Consumed: {message.data}")
```

## Filtering and Conditions

### Custom Conditions

```python
# Only publish error messages
error_topic = (Topic.builder()
    .name("errors")
    .condition(lambda msgs: any("error" in msg.content.lower() for msg in msgs))
    .build())

# Only publish messages from specific roles
admin_topic = (Topic.builder()
    .name("admin_messages")
    .condition(lambda msgs: any(msg.role == "admin" for msg in msgs))
    .build())

# Complex business logic
validated_topic = (Topic.builder()
    .name("validated_messages")
    .condition(lambda msgs: all(
        msg.metadata.get("validated", False) for msg in msgs
    ))
    .build())
```

### Default Behavior

```python
# Accept all messages (default condition)
all_messages_topic = Topic(name="all_messages")
# Equivalent to: condition=lambda _: True
```

## Pre-configured Topics

### Agent Input Topic

The module provides a pre-configured topic for agent input:

```python
from grafi.common.topics.topic import agent_input_topic

# Use the predefined agent input topic
event = agent_input_topic.publish_data(
    invoke_context=context,
    publisher_name="user_interface",
    publisher_type="input_handler",
    data=user_messages,
    consumed_events=[]
)
```

## Logging Integration

### Log Messages

The Topic class automatically logs publishing operations:

```python
# Successful publishing
logger.info(f"[{self.name}] Message published with event_id: {event.event_id}")

# Condition not met
logger.info(f"[{self.name}] Message NOT published (condition not met)")
```

### Log Format Examples

```text
INFO: [notifications] Message published with event_id: evt_123456
INFO: [errors] Message NOT published (condition not met)
INFO: [alerts] Message published with event_id: evt_789012
```

## Best Practices

### Topic Design

1. **Meaningful Names**: Use descriptive names that indicate the topic's purpose
2. **Focused Conditions**: Keep condition functions simple and focused
3. **Event Handlers**: Use handlers for side effects, not primary logic
4. **Error Handling**: Handle condition evaluation errors gracefully

### Performance Optimization

1. **Efficient Conditions**: Optimize condition functions for frequent evaluation
2. **Handler Performance**: Keep event handlers lightweight and fast
3. **Memory Management**: Monitor topic event accumulation
4. **Batch Processing**: Consider batching for high-volume scenarios

### Error Handling

```python
def safe_condition(messages: Messages) -> bool:
    try:
        return any("priority" in msg.metadata for msg in messages)
    except (AttributeError, KeyError):
        return False

def safe_handler(event: PublishToTopicEvent):
    try:
        process_event(event)
    except Exception as e:
        logger.error(f"Error in event handler: {e}")
```

### Testing Strategies

```python
def test_topic_publishing():
    # Create test topic
    topic = Topic(name="test_topic")
    messages = [Message(role="user", content="test")]

    # Test successful publishing
    event = topic.publish_data(
        invoke_context=InvokeContext(),
        publisher_name="test",
        publisher_type="test",
        data=messages,
        consumed_events=[]
    )

    assert event is not None
    assert len(topic.topic_events) == 1

def test_condition_filtering():
    # Create topic with condition
    topic = (Topic.builder()
        .name("filtered_topic")
        .condition(lambda msgs: len(msgs) > 1)
        .build())

    # Test with single message (should be filtered)
    single_message = [Message(role="user", content="test")]
    event = topic.publish_data(
        invoke_context=InvokeContext(),
        publisher_name="test",
        publisher_type="test",
        data=single_message,
        consumed_events=[]
    )

    assert event is None
    assert len(topic.topic_events) == 0
```

The `Topic` class provides a robust, production-ready implementation of the topic-based messaging pattern with built-in logging, event handling, and flexible configuration options for Graphite applications.
