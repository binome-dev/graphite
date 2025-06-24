# Models

In the Graphite, varies models provide the fundamental data structures that underpin the event-driven workflow. Message represents the content exchanged between users, assistants, and language models, enabling consistent communication and processing. Event captures the various actions and state changes in the system, from workflow initiation to final outputs. Meanwhile, Topic defines the named channels where events are published and consumed, establishing a structured mechanism for coordinating data flow across the platform.

## Message

`Message` extends OpenAI’s `ChatCompletionMessage`, serving as a standardized data structure for both incoming and outgoing content in the event-driven workflow. Each `Message` instance retains essential metadata such as timestamps, unique identifiers, and optional tool references, facilitating robust and traceable communication between users, assistants, and LLM tools.

### Fields

| Field           | Description                                                                                               |
|-----------------|-----------------------------------------------------------------------------------------------------------|
| `name`          | An optional name indicating the source or identifier for the message (e.g., function name).               |
| `message_id`    | A unique identifier for the message, defaulting to a generated UUID.                                      |
| `timestamp`     | The time in nanoseconds when the message was created, allowing strict chronological ordering.             |
| `role`          | Specifies the speaker’s role (`system`, `user`, `assistant`, or `tool`).                                  |
| `tool_call_id`  | Associates the message with a particular tool invocation if relevant.                                     |
| `tools`         | An optional list of OpenAI's `ChatCompletionToolParam` for referencing available tool calls.              |

### Usage Example

```python
from grafi.common.models.message import Message

# Creating a user message
user_message = Message(
    role="user",
    content="What is the capital of France?"
)

# Creating an assistant message
assistant_message = Message(
    role="assistant",
    content="The capital of France is Paris."
)
```

In both cases, the `Message` class provides a consistent structure for storing conversation state, bridging the gap between OpenAI’s chat messages and the system’s event-driven architecture.

## Event

`Event` is the foundational data model in the event driven architecture, capturing the common fields and logic shared by all event types. Each subclass of `Event` (e.g., Node events, Topic events) extends this base with specialized data. The core `Event` model also offers a standard interface for serialization (`to_dict`) and deserialization (`from_dict`), promoting consistency across the platform.

The `Event` fields are:

| Field              | Description                                                                                         |
|--------------------|-----------------------------------------------------------------------------------------------------|
| `event_id`         | Unique identifier for the event, defaulting to a generated UUID.                                    |
| `invoke_context`| A reference to the workflow’s current state, including assistant request details and other metadata.|
| `event_type`       | An `EventType` enum value describing the kind of event (e.g., NodeInvoke, ToolRespond).             |
| `timestamp`        | The UTC timestamp of event creation, used for ordering and auditing.                                |

The benefits are:

- **Consistency**: All events adhere to the same schema for IDs, context, and timestamps.
- **Extensibility**: Subclasses can introduce additional fields while still retaining base serialization logic.
- **Traceability**: The shared timestamp and `invoke_context` fields provide a reliable audit trail.

By leveraging this **Event** model, the system enforces uniform data handling for everything from node invocations to assistant responses, simplifying debugging and logging throughout the workflow lifecycle.

### Component activity event

In the Graphite’s layered architecture, each principal component (Assistant, Node, Tool, and Workflow) can invoke, respond, or fail during invoke. And there are events associate with each actions, such as invoke  event, respond event and failed event. For nodes specifically, these actions are tracked as three distinct event types:

1. **NodeInvokeEvent**: The node is invoked with input data.
2. **NodeRespondEvent**: The node completes invoke and returns output data.
3. **NodeFailedEvent**: The node encounters an error during invoke.

These events capture the inputs, outputs, timestamps, and other metadata essential for observing and debugging node behavior.

Here is the `Node` base event `NodeEvent`:

| Field                | Description                                                                  |
|----------------------|------------------------------------------------------------------------------|
| `node_id`            | Unique identifier for the node. Defaults to a generated UUID.                |
| `node_name`          | Human-readable name of the node.                                             |
| `node_type`          | Describes the functional category of the node (e.g., "LLMNode").             |
| `subscribed_topics`  | The list of event topics to which this node is subscribed.                   |
| `publish_to_topics`  | The list of event topics where the node publishes output.                    |
| `invoke_context`  | Workflow metadata, including request details and IDs.                        |
| `event_type`         | The specific event variant: `NODE_INVOKE`, `NODE_RESPOND`, or `NODE_FAILED`. |
| `timestamp`          | The UTC timestamp when the event was generated.                              |

and the `Node` base event methods

| Method                      | Description                                                                                                   |
|-----------------------------|---------------------------------------------------------------------------------------------------------------|
| `node_event_dict()`         | Returns a dictionary merging base event data (`event_dict()`) with node-specific fields (e.g., ID, topics).   |
| `node_event_base()`         | Class method that reconstructs node-specific fields (like `node_id` and `node_name`) from a dictionary.       |
| `event_dict()`              | Inherited from `Event`; provides flattening of `invoke_context` and standard event metadata.               |
| `event_base()`              | Inherited from `Event`; extracts `event_id`, `event_type`, and `timestamp` from a serialized event.           |
| `to_dict()` / `from_dict()` | Implemented in subclasses, each adjusts data serialization or deserialization for the event’s unique fields.  |

`NodeInvokeEvent` extended from  `NodeEvent`, with additional field:

| Field       | Description                                                                                    |
|-------------|------------------------------------------------------------------------------------------------|
| `input_data`| A list of `ConsumeFromTopicEvent` representing the node’s consumed messages upon invocation.   |

`NodeInvokeEvent` implemented the serialise and deserialise methods `to_dict()` and `from_dict(data)`.  

| Method            | Description                                                                                                                                 |
|-------------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| `to_dict()`       | Returns the merged dictionary from `node_event_dict()` plus the serialized list of input events (`input_data`).                             |
| `from_dict(data)` | Class method that calls `node_event_base` for the base event fields, then rebuilds `input_data` by deserializing each consumed event dict.  |  

`NodeRespondEvent` extended from `NodeEvent`, with two additional fields:

| Field         | Description                                                                                     |
|---------------|-------------------------------------------------------------------------------------------------|
| `input_data`  | A list of `ConsumeFromTopicEvent` messages that the node consumed.                              |
| `output_data` | The resulting message(s) (`Message` or list of `Message`) produced by the node’s invoke.     |

`NodeRespondEvent` implemented the serialise and deserialise methods `to_dict()` and `from_dict(data)`.

| Method          | Description                                                                              |
|-----------------|------------------------------------------------------------------------------------------|
| `to_dict()`     | Calls `node_event_dict()` and includes JSON-serialized `output_data`.                    |
| `from_dict()`   | Deserializes `input_data` and `output_data`; uses `node_event_base` for common fields.   |

`NodeFailedEvent` extended from  `NodeEvent`, with additional field:

| Field         | Description                                                                                           |
|---------------|-------------------------------------------------------------------------------------------------------|
| `input_data`  | A list of `ConsumeFromTopicEvent` messages that led to this error condition.                          |
| `error`       | Contains information about the error encountered (stack trace, message, or custom error object).      |

`NodeFailedEvent` implemented the serialise and deserialise methods `to_dict()` and `from_dict(data)`.

| Method          | Description                                                                                      |
|-----------------|--------------------------------------------------------------------------------------------------|
| `to_dict()`     | Uses `node_event_dict()` and adds an `error` field.                                              |
| `from_dict()`   | Builds the event from `node_event_base`, restoring `input_data` and capturing `error` details.   |

Collectively, these **Node Activity Events** form a consistent pattern for tracking node lifecycle across invoke, respond, and fail states. The same concept applies to other components in the system (e.g., Assistant, Tool, Workflow), each featuring its respective invoke, respond, and failed events. This design ensures clear traceability and systematic error handling within the event-driven workflow architecture.

### Publish and Subscribe Event

Publish and subscribe events capture data published to or consumed from specific channels - topics - in the system. They enable Nodes to communicate asynchronously by sending and receiving messages on named topics. The platform distinguishes three main types:

1. **PublishToTopicEvent**: Emitted when data is published to a topic.
2. **ConsumeFromTopicEvent**: Occurs when a consumer retrieves data from a topic.
3. **OutputTopicEvent**: A special publish event intended for final user-facing outputs, typically consumed by an Assistant.

`TopicEvent` is the base event, it extends from `Event` class, and added following fields

| Field               | Description                                                                                     |
|---------------------|-------------------------------------------------------------------------------------------------|
| `topic_name`        | Identifies the topic to which this event pertains (e.g., "agent_input", "agent_output").        |
| `offset`            | A numeric indicator of the event’s position in the topic stream.                                |
| `data`              | The message(s) (or generator of messages) being transferred.                                    |
| `event_id`          | Inherited from `Event`; unique identifier for this event.                                       |
| `event_type`        | Inherited from `Event`; marks it as a topic event variant (e.g., `PUBLISH_TO_TOPIC`).           |
| `timestamp`         | Inherited from `Event`; records the time the event was created (UTC).                           |
| `invoke_context` | Inherited from `Event`; includes metadata such as `assistant_request_id` for tracing.           |

`TopicEvent` has following methods:

| Method                    | Description                                                                                                 |
|---------------------------|-------------------------------------------------------------------------------------------------------------|
| `topic_event_dict()`      | Combines base event data (`event_dict()`) with topic-specific fields and JSON-serialized `data`.            |
| `topic_event_base(dict)`  | Class method that deserializes topic data (including `Message` objects) and merges with base event fields.  |
| `event_dict()`            | From the `Event` class; flattens `invoke_context` and includes standard metadata (event ID, type, etc.). |
| `event_base(dict)`        | From the `Event` class; extracts `event_id`, `event_type`, and `timestamp`.                                 |
| `to_dict() / from_dict()` | Implemented in each subclass, customizing how `data` or additional fields are serialized.                   |

`PublishToTopicEvent` extends `TopicEvent` with following additional fields

| Field                | Description                                                                                     |
|----------------------|-------------------------------------------------------------------------------------------------|
| `consumed_event_ids` | A list of event IDs indicating which prior events (e.g., consumed messages) led to this publish.|
| `publisher_name`     | The name of the component (Node, Assistant, etc.) publishing the data.                          |
| `publisher_type`     | The type/category of the publisher (e.g., "Node", "Assistant").                                 |

`PublishToTopicEvent` implemented the following methods

| Method                | Description                                                                                         |
|-----------------------|-----------------------------------------------------------------------------------------------------|
| `to_dict()`           | Adds `consumed_event_ids`, `publisher_name`, and `publisher_type` to the standard topic event dict. |
| `from_dict(dict)`     | Recreates the event by merging base topic fields with the additional publisher-related fields.      |

`ConsumeFromTopicEvent` extends `TopicEvent` with following additional fields

| Field            | Description                                                                       |
|------------------|-----------------------------------------------------------------------------------|
| `consumer_name`  | The name of the component consuming the data (Node, Assistant, etc.).             |
| `consumer_type`  | The category or type of the consumer (e.g., "Node", "Assistant").                |

`ConsumeFromTopicEvent` implemented the following methods

| Method            | Description                                                                                         |
|-------------------|-----------------------------------------------------------------------------------------------------|
| `to_dict()`       | Adds consumer-specific fields (`consumer_name`, `consumer_type`) to the base topic event data.      |
| `from_dict(dict)` | Restores the consume event by parsing both base topic fields and the consumer-related fields.       |

`OutputTopicEvent` is a special form of `PublishToTopicEvent` used exclusively for final outputs. Typically consumed by an **Assistant** to relay data back to the user.

`OutputTopicEvent`'s additional details are

- **EventType** is fixed to `OUTPUT_TOPIC`.
- `data` can be a single `Message`, multiple `Message` objects, or a generator of messages. Currently, serialization is pending further implementation.

`OutputTopicEvent` implemented the following methods

| Method            | Description                                                                               |
|-------------------|-------------------------------------------------------------------------------------------|
| `to_dict()`       | Extends `PublishToTopicEvent.to_dict()`, placeholder for future data serialization logic. |
| `from_dict(dict)` | Placeholder for data deserialization from a dictionary, to be implemented.                |

These topic-based events enable decoupled communication within the system. **PublishToTopicEvent** moves data onto a topic, **ConsumeFromTopicEvent** retrieves it, and **OutputTopicEvent** designates final user-facing outputs. By standardizing how messages flow through topics, the platform ensures reliability, traceability, and straightforward integration among nodes, assistants, and tools.
