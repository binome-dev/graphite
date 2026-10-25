# Topic

The `Topic` class is a concrete implementation of `TopicBase` that provides a complete message queue system for publishing and consuming messages within Graphite applications. A topic is a named FIFO queue: it enqueues every publication it is given, and each consumer reads it from its own offset.

## Overview

The `Topic` class extends `TopicBase` to provide:

- **Queueing**: Publications are kept in order, and each consumer reads and commits its own offset
- **No Conditions**: A topic never drops an event; which topics an event goes to is decided by the node publishing it (see [Routing](#routing))
- **Builder Pattern**: Fluent API for topic configuration

## Core Components

### Topic Class

A complete topic implementation, with a builder.

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | The topic's name, by which nodes and manifests refer to it |
| `type` | `TopicType` | `TopicType.DEFAULT_TOPIC_TYPE` (`"Topic"`) |
| `event_queue` | `TopicEventQueue` | FIFO queue of the topic's events, for using the topic on its own (in memory by default; never saved) |

#### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `builder` | `() -> TopicBuilder` | Class method returning a TopicBuilder instance |
| `publish_data` | `async (publish_event: PublishToTopicEvent) -> PublishToTopicEvent` | Publishes a copy of the event to the topic and returns it |

*Inherits all methods from `TopicBase`: `prepare_publication`, `can_consume`, `consume`, `commit`, `reset`, `restore_topic`, etc. See [Topic Base](topic_base.md).*

### TopicBuilder

Builder for `Topic` instances.

#### Builder Methods

*Inherits all builder methods from `TopicBaseBuilder`: `name`, `type`*

## Publishing Logic

`publish_data(publish_event)` takes the event a publisher emits and enqueues
this topic's own copy of it, which it returns:

1. **Copy**: `prepare_publication()` copies the event with this topic's name and
   type, a fresh `event_id`, and the source event's ID in `emission_id`
2. **Enqueue**: the copy is added to the topic's `event_queue`, with its offset
   set
3. **Return Result**: the enqueued publication is returned; a topic never drops
   an event

In a workflow, the run keeps its topics' events itself and calls only
`prepare_publication()`; `publish_data()` and the consumption methods are for
using a topic on its own.

## Usage Examples

### Basic Topic Creation

```python
from grafi.topics.topic_impl.topic import Topic

# Create simple topic
topic = Topic(name="notifications")

# Or use builder pattern
topic = (Topic.builder()
    .name("notifications")
    .build())
```

### Publishing Messages

```python
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message

# Create context and messages
context = InvokeContext(
    conversation_id="conversation_id",
    invoke_id="invoke_id",
    assistant_request_id="assistant_request_id",
)
messages = [Message(role="user", content="Hello world")]

# Publish to topic
event = await topic.publish_data(
    PublishToTopicEvent(
        invoke_context=context,
        publisher_name="my_publisher",
        publisher_type="application",
        data=messages,
    )
)

print(f"Published: {event.event_id} at offset {event.offset}")
```

### Message Consumption

```python
# Check for new messages
if await topic.can_consume("consumer_1"):
    events = await topic.consume("consumer_1")
    for event in events:
        print(f"Consumed: {event.data}")
    # Mark them processed
    await topic.commit("consumer_1", events[-1].offset)
```

## Routing

A topic has no condition. To send only some events to a topic, give the
publishing node's route a `when` predicate, a function of the outgoing
`PublishToTopicEvent` returning a `bool`; the event goes to that route's topic
only when it returns `True`. Reusable predicates live in
`grafi.nodes.conditions`:

```python
from grafi.nodes.conditions import has_text_response
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.node import Node

llm_node = (
    Node.builder()
    .name("LLMNode")
    .subscribe(agent_input_topic)
    .tool(llm_tool)
    .publish_to(function_call_topic, when=has_tool_call)
    .publish_to(agent_output_topic, when=has_text_response)
    .build()
)


# Or your own predicate
def mentions_error(event: PublishToTopicEvent) -> bool:
    return any("error" in str(msg.content).lower() for msg in event.data)
```

A route without `when` takes every event. See [Node](../node.md).

## Input and Output Topics

A workflow's input arrives on its `InputTopic`s, and its output is read from its
`OutputTopic`s; both are `Topic`s. See [Input Topics](input_topics.md) and
[Output Topics](output_topics.md).

## Best Practices

### Topic Design

1. **Meaningful Names**: Use descriptive names that indicate the topic's purpose
2. **Route on the Node**: Put the condition for publishing on the publishing node's route, not on the topic
3. **Named Predicates**: Use importable, module-level functions, such as those in `grafi.nodes.conditions`: a manifest saves them by reference, and cannot save a lambda
4. **Memory Management**: Monitor topic event accumulation

### Error Handling

A route predicate that raises `IndexError` or `KeyError` counts as not met;
any other exception is logged as a warning and also counts as not met, so one
faulty predicate cannot halt the workflow.

```python
def has_priority(event: PublishToTopicEvent) -> bool:
    return event.data[-1].content.startswith("PRIORITY")  # IndexError on no data: not met
```

### Testing Strategies

```python
async def test_topic_publishing():
    # Create test topic
    topic = Topic(name="test_topic")
    messages = [Message(role="user", content="test")]

    # Test successful publishing
    event = await topic.publish_data(
        PublishToTopicEvent(
            invoke_context=InvokeContext(
                conversation_id="c", invoke_id="i", assistant_request_id="a"
            ),
            publisher_name="test",
            publisher_type="test",
            data=messages,
        )
    )

    assert event.name == "test_topic"
    assert event.offset == 0
    assert await topic.unconsumed_count("consumer") == 1
```

The `Topic` class provides a robust implementation of the topic-based messaging pattern for Graphite applications.
