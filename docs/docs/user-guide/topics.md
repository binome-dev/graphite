`TopicBase` and `Topic` represent logical message queues in the event-driven workflow. They temporarily store messages in a First-In-First-Out (FIFO) fashion and track how many messages each consumer has read using an offset system. This allows components—like Nodes, Assistants, or Tools—to communicate asynchronously by publishing and consuming messages.

#### TopicBase

`TopicBase` provides the core interface and data structures for managing published events, consumption offsets, and conditions used to filter which messages are accepted.

Fields:

| Field                      | Description                                                                                   |
|----------------------------|-----------------------------------------------------------------------------------------------|
| `name`                     | The topic’s human-readable name.                                                              |
| `condition`                | A function deciding if incoming messages should be published to this topic. Defaults to True. |
| `publish_event_handler`    | An optional callback that runs after a successful publish.                                    |
| `topic_events`             | A list of `TopicEvent` objects representing messages accepted by the topic.                   |
| `consumption_offsets`      | Maps consumer identifiers to the index of the last message they consumed.                     |

Methods:

| Method                              | Description                                                                                                                                |
|-------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| `publish_data(...)`                 | Publishes data to the topic if it meets the `condition`. Must be implemented in subclasses.                                                |
| `can_consume(consumer_name)`        | Checks if a consumer has unread messages in this topic.                                                                                    |
| `consume(consumer_name)`            | Retrieves the unread messages for the consumer, updates its offset, and returns the relevant events.                                       |
| `reset()`                           | Clears `topic_events` and `consumption_offsets`, effectively reverting the topic to its initial state.                                     |
| `restore_topic(topic_event)`        | Rebuilds the topic’s state from a `TopicEvent`, adding to `topic_events` or adjusting consumption offsets.                                 |
| `to_dict()`                         | Serializes basic fields like `name` and `condition`.                                                                                       |
| `serialize_callable()`              | Helper that extracts details about the `condition` function (e.g., lambda source code or function name).                                   |

`TopicBase` also includes a builder pattern that simplifies creating and customizing topics (e.g., adding a `condition`). Subclasses extend `publish_data`, `can_consume`, and `consume` to store and retrieve messages in a more concrete manner.

#### Topic

`Topic` is a direct subclass of `TopicBase` that implements the required methods for a working FIFO message queue. Components publish via `publish_data`, and consumers read new messages via `consume`, each consumer having an independent offset.

`Topic` shares all fields from `TopicBase` and does not introduce additional fields beyond its default name.

Methods:

| Method                              | Description                                                                                                               |
|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| `publish_data(...)`                 | Creates a `PublishToTopicEvent` if the `condition` is met and calls `publish_event_handler` to handle event.              |
| `can_consume(consumer_name)`        | Checks if `consumer_name`’s offset is behind `len(topic_events)`, meaning there are new, unread messages.                 |
| `consume(consumer_name)`            | Retrieves unconsumed messages, updates the consumer’s offset, and returns the new events.                                 |

A typical workflow involves creating a `Topic` instance (or more specialized subclass), optionally setting a `condition` to filter messages, and then connecting nodes or assistants that publish or consume messages. Whenever data is published, `Topic` increments the offset and stores the new event. When a consumer checks `can_consume`, the topic compares its offset with the total published messages to determine if any remain unread.

This design ensures that each consumer reads messages in the correct order, preserving FIFO behavior while enabling asynchronous, distributed interactions across the event-driven workflow.

#### Output Topic

`OutputTopic` is a specialized subclass of `Topic` designed for user-facing events. When data is published to an `OutputTopic`, it uses `OutputTopicEvent` rather than a standard `PublishToTopicEvent`, indicating that these messages should ultimately be returned to the user.

Fields:

| Field                      | Description                                                                                                    |
|----------------------------|----------------------------------------------------------------------------------------------------------------|
| `name`                     | Defaults to `AGENT_OUTPUT_TOPIC`, representing the system’s standard output channel.                           |
| `publish_event_handler`    | An optional callback that executes whenever an `OutputTopicEvent` is successfully published.                   |
| `topic_events`             | A list of `OutputTopicEvent` objects, maintaining the published output messages in FIFO order.                 |
| `consumption_offsets`      | Maps consumer identifiers (e.g., assistant names) to the last read event offset, ensuring each reads in order. |

Methods:

| Method                            | Description                                                                                                                |
|-----------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| `publish_data(...)`               | Creates an `OutputTopicEvent` with the given messages if the `condition` is met. Append event to topic, then call handler. |
| `_publish(event)`                 | Inherited from `TopicBase`; assigns an offset and appends the event to `topic_events` if allowed by `condition`.           |

Use Case:

Typically, an assistant consumer will subscribe to the OutputTopic to retrieve user-facing results. By separating output into a dedicated topic, the system can more easily track final responses, funneling them back to the user through consistent workflows.

#### Human Request Topic

`HumanRequestTopic` is a specialized extension of `Topic` dedicated to handling requests that require human intervention or input. When the workflow needs user input, it publishes an `OutputTopicEvent` to `HumanRequestTopic`. On the user’s response, that input is appended back to the same topic, keeping the entire request-response cycle self-contained.

Fields:

| Field                            | Description                                                                                                          |
|----------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `name`                           | Defaults to `HUMAN_REQUEST_TOPIC`, indicating it’s the main channel for human-driven requests.                       |
| `publish_to_human_event_handler` | A callback triggered after successfully publishing an `OutputTopicEvent` for user-facing interactions.               |
| `topic_events`                   | A list of `TopicEvent` (or `OutputTopicEvent`) objects, preserving a history of user requests and appended responses.|
| `consumption_offsets`            | Maps consumer identifiers to the offset of the last read event, enabling a FIFO workflow for multiple consumers.     |

Methods:

| Method                                        | Description                                                                                                               |
|-----------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| `publish_data(...)`                           | Publishes data to the topic as an `OutputTopicEvent` and add to topic if `condition` is met. Then invoke `publish_to_human_event_handler`|
| `can_append_user_input(consumer_name, event)` | Check if can add the user input event given its parent `PublishToTopicEvent`.                                             |
| `append_user_input(user_input_event, data)`   | Appends actual user responses using a standard `PublishToTopicEvent`, ensuring they become available for downstream nodes.|

Usage:

1. **Publishing Requests**: When a node or another component needs user input, it calls `publish_data(...)` on `HumanRequestTopic`, generating an `OutputTopicEvent`. This signals the assistant to display or relay a query to the user.
2. **Appending User Input**: After the user responds, the assistant (or another client) calls `append_user_input(...)`, creating a `PublishToTopicEvent` that effectively stores the user’s messages in the same topic.
3. **Downstream Consumption**: Any node subscribed to the `HumanRequestTopic` can consume new messages as they appear, enabling further automated logic once the user’s response is available.

Rational:

By splitting user interaction into distinct publish and append steps, the system provides a clear interface for capturing requests and responses, all under a single, specialized topic designed for human-driven workflows.

#### Topic Expression

**Topic Expression** provides a mini DSL (Domain-Specific Language) for building complex subscription logic based on multiple topics. By combining topic references using logical operators (AND, OR), you can specify whether a node should wait for messages in all required topics (`AND`) or at least one of several possible topics (`OR`). This approach offers a flexible way to manage event-driven subscriptions.

Models

`LogicalOp`

| Enum Value | Description                                  |
|------------|----------------------------------------------|
| `AND`      | Both sides must be satisfied for expression  |
| `OR`       | At least one side must be satisfied          |

`SubExpr` (Base Class)

| Class    | Description                                          |
|----------|------------------------------------------------------|
| `SubExpr`| Abstract base class for any subscription expression. |

`TopicExpr` (extended from `SubExpr`)

| Field         | Description                                                               |
|---------------|---------------------------------------------------------------------------|
| `topic`       | A `TopicBase` object representing a single topic in the subscription tree.|

`TopicExpr` states that a subscriber is interested in a single topic. If new, unread messages exist in that topic, the expression evaluates to `True`.

`CombinedExpr` (extended from `SubExpr`)

| Field   | Description                                                                   |
|---------|-------------------------------------------------------------------------------|
| `op`    | A `LogicalOp` indicating `AND` or `OR`.                                       |
| `left`  | Another `SubExpr` node.                                                       |
| `right` | Another `SubExpr` node.                                                       |

`CombinedExpr` composes two sub-expressions with a logical operator, enabling complex nested conditions.

Methods

| Method                                              | Description                                                                                                                                                                           |
|-----------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `evaluate_subscription(expr, topics_with_new_msgs)` | Checks whether a subscription expression (`expr`) is fulfilled by the given list of topics that have new messages. Returns `True` if the condition is met (based on `AND`/`OR` logic).|
| `extract_topics(expr)`                              | Recursively collects all `TopicBase` objects from the DSL expression tree, letting the system know which topics a node depends on.                                                    |

Key Points:

1. **Flexibility**: You can nest multiple expressions to create complex logic. For instance, `(TopicA AND (TopicB OR TopicC))`.
2. **Maintainability**: By separating subscription logic into DSL expressions, the system remains clear and easy to debug.
3. **Integration**: Each `TopicExpr` references an actual `TopicBase`, ensuring that the DSL and the underlying queue system stay in sync.

#### Subscription Builder

`SubscriptionBuilder` streamlines the process of creating complex topic subscription expressions, allowing you to chain logical operations (`AND`, `OR`) and define whether a node requires messages from multiple topics or at least one. This builder pattern provides a concise DSL for specifying these conditions without manually constructing `TopicExpr` and `CombinedExpr` objects.

Fields:

| Field           | Description                                                                                           |
|-----------------|-------------------------------------------------------------------------------------------------------|
| `root_expr`     | The current root of the subscription expression tree (`SubExpr`), built incrementally by chaining.    |
| `pending_op`    | A `LogicalOp` (AND/OR) that awaits completion of the next `subscribed_to(...)` call.                  |

Methods:

| Method                                       | Description                                                                                                                             |
|----------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| `subscribed_to(topic: TopicBase)`            | Adds a new `TopicExpr` node referencing `topic`. If `pending_op` is set, combines it with the existing `root_expr` via a `CombinedExpr`.|
| `and_()`                                     | Sets `pending_op` to `LogicalOp.AND`, indicating the next topic reference should form an AND relationship.                              |
| `or_()`                                      | Sets `pending_op` to `LogicalOp.OR`, indicating the next topic reference should form an OR relationship.                                |
| `build()`                                    | Finalizes the builder, returning the constructed `SubExpr`.                                                                             |

Usage Example:

```python

# Suppose you have two Topic objects: topicA and topicB
# Build an expression: (topicA AND topicB)
subscription_expr = (
    SubscriptionBuilder()
    .subscribed_to(topicA)
    .and_()
    .subscribed_to(topicB)
    .build()
)

# The resulting expression can be assigned to a node, which then requires new messages from both topics.
node_builder.subscribed_to(subscription_expr)
```

Key Points:

1. **Chained Syntax**: The builder pattern enables a straightforward DSL-like syntax: `.subscribed_to(topicA).and_().subscribed_to(topicB).build()`.
2. **Operator Checks**: If `and_()` or `or_()` is called without a subsequent `subscribed_to(...)`, or vice versa, a `ValueError` is raised.
3. **Integration**: Once created, the resulting `SubExpr` can be evaluated against incoming messages with `evaluate_subscription()` or used for introspection with `extract_topics()`. This provides flexible, powerful subscription logic for nodes in an event-driven system.

#### Reserved Topics

These topics are reserved for essential system operations in the event-driven workflow, ensuring consistent handling of inputs, outputs, and user-interactive events.

1. Input Topic
    - **`agent_input_topic`**: Receives user or external inputs, starting the workflow by providing initial messages or commands for further processing.
2. Output Topics
    - **`agent_stream_output_topic`**: Streams partial or incremental responses during long-running or asynchronous operations. Typically used for real-time updates.
    - **`agent_output_topic`**: Publishes final agent responses that are ready to be returned to the user or external systems. The `Assistant` is the only consumer of this topic.
3. Human Request Topic
    - **`human_request_topic`**: A special topic for user involvement. When the system needs additional information or confirmation from humans, it posts requests here; once the user responds, messages are appended to the same topic and become available for downstream processing.

Using these reserved topics helps maintain a clear, consistent architecture for input processing, output streaming, final responses, and human-driven request handling. They are key building blocks for standardizing communication across the workflow.

### Event Graph

`EventGraph` organizes events (particularly `ConsumeFromTopicEvent` and `PublishToTopicEvent`) into a directed graph structure. It traces how messages flow from published events through consumed ones, enabling advanced operations like retrieving a sorted sequence of all ancestor messages. This is especially important for Large Language Model (LLM) interactions, where the full conversation history (including intermediate nodes) must be serialized in a coherent, chronological order.

#### Fields

| Field        | Description                                                                                                  |
|--------------|--------------------------------------------------------------------------------------------------------------|
| `nodes`      | A dictionary mapping event IDs to `EventGraphNode` objects.                                                  |
| `root_nodes` | A list of `EventGraphNode` objects representing the starting points (e.g., directly consumed events).        |

#### Methods

| Method                                | Description                                                                                                                                                                                |
|---------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `_add_event(event)`                   | Creates a new `EventGraphNode` for a given `Event` if it does not already exist.                                                                                                           |
| `build_graph(consume_events, topic_events)` | Constructs the event graph from a list of consume events and a dictionary of topic events. It links each consume event to its corresponding publish event, building upstream/downstream refs.|
| `get_root_event_nodes()`              | Returns the root nodes, i.e., the events that begin sub-graphs (often direct consume events).                                                                                               |
| `get_topology_sorted_events()`        | Performs a custom topological sort, ordering events by reverse timestamp within each dependency layer, and then reversing the result for ascending chronological output.                    |
| `to_dict()`                           | Serializes the entire graph, including each node’s event and references.                                                                                                                   |
| `from_dict(...)`                      | Deserializes the graph from a dictionary, recreating each `EventGraphNode`.                                                                                                                |

#### Rationale for Topological and Timestamp Sorting

When feeding conversation or workflow history to an LLM, it’s crucial to maintain logical and temporal ordering of all ancestor events. By combining topological ordering with timestamp-based sorting, the `EventGraph` ensures:

1. **Correct Causality**: Dependencies (publish -> consume) appear before reliant events.
2. **Chronological Consistency**: Events with similar dependency levels are ordered by their actual creation time.
3. **Complete Context**: The LLM receives a fully serialized token sequence of all ancestor interactions, enabling more coherent responses.

By leveraging the `EventGraph` class, developers can reliably trace the chain of message publications and consumptions, producing a robust representation of the workflow’s complete ancestry—critical for advanced LLM tasks or debugging complex distributed processes.

