# Node

A Node is a discrete component in a graph-based agent system that operates under an event-driven model. Its primary role is to represent its position within a workflow graph, manage event subscriptions, and designate topics for publishing. In addition, it delegates invoke to a Command object, adhering to the Command Pattern. Each Node comprises the following elements:

- Unique Identity
  - Distinguished by a unique node_id, name, and type.
  - The name must be unique within a given workflow.
- Subscribed Topics
  - Stores the event topics to which the node subscribes, typically originating from upstream publishers.
  - Subscriptions can reference explicit topic names or apply custom subscription strategies.
- Publish-To Topics
  - Stores the event topics designated for downstream nodes to subscribe to, facilitating event routing.
- Command for Invoke
  - Encapsulates invoke logic through a Command object.
  - Allows integration of new or specialized commands without modifying the node's existing structure.

## NodeBase

The `NodeBase` class serves as the abstract foundation for all nodes in the graph-based agent system. It defines the core structure and interface that all node implementations must follow, including:

- **Core Properties**: Essential attributes like `node_id`, `name`, `type`, and `tool`
- **Event Management**: Subscription expressions and publish-to topics for event-driven communication
- **Command Integration**: Internal command management through the Command Pattern
- **Builder Pattern**: Provides a fluent interface for node construction via `NodeBaseBuilder`

The base class defines an abstract method `invoke` that must be implemented by concrete subclasses to define their specific behavior.

## Node Implementation

The `Node` class is a concrete implementation of `NodeBase` that provides a working node with standard invoke behavior. Unlike the abstract base class, `Node` actually implements the `invoke` method by delegating to an internal `Command` object.

Key features of the Node class include:

- **Automatic Command Setup**: Makes its command from its tool when it is read, again once the node holds another tool
- **Event-Driven Invocation**: Uses `can_invoke()` to determine readiness based on subscribed topics
- **Event-Based Interface**: Consumes `ConsumeFromTopicEvent` objects and publishes `PublishToTopicEvent` objects
- **Decorator Support**: Includes built-in instrumentation via `@record_node_invoke`

The following table describes each field within the Node class, highlighting its purpose and usage in the workflow:

| Field                    | Description                                                       |
|--------------------------|-------------------------------------------------------------------|
| `node_id`                | A unique identifier for the node instance.                        |
| `name`                   | A unique name identifying the node within the workflow.           |
| `type`                   | Defines the category or type of node, indicating its function.    |
| `tool`                   | Optional tool that the node uses; the node's command is made from it. A workflow wires its nodes as it is built and as each run starts (see [Workflow Initialization](event-driven-workflow.md#workflow-initialization)). |
| `command`                | Read-only property: the command the node runs its tool through, which the tool's class names with `@use_command` (the base `Command` otherwise), made from the node's tool when read, again once the node holds another; `None` without a tool. Setting it raises `AttributeError`, pointing to `@use_command`. |
| `oi_span_type`           | Semantic attribute from OpenInference for tracing purposes.       |
| `subscribed_expressions` | List of DSL-based subscription expressions used by the node, set when it is built: build a new node to change them (a run refuses a node whose subscriptions name other topics than when it was built, changed in place or copied with `model_copy(update=...)`). |
| `publisher_router`       | The node's output routing table: a `PublisherRouter` whose `routes` each pair a destination topic with a `when` predicate on the outgoing event (by default, always true). |
| `publish_to`             | Read-only property: the topics the node publishes events to, from its routes. |
| `_subscribed_topics`     | Internal mapping of subscribed topic names to Topic instances.    |
| `_command`               | Private field caching the command made from the node's tool.      |

The following table summarizes the methods available in the Node class, highlighting their purpose and intended usage:

| Method               | Description                                                                                              |
|----------------------|----------------------------------------------------------------------------------------------------------|
| `builder`           | Class method that returns a `NodeBaseBuilder` for fluent node construction.                              |
| `model_post_init`   | Model post-initialization hook that sets up subscribed topics. |
| `invoke`          | Asynchronously invokes the node's command, yielding one `PublishToTopicEvent` with its tool's output, or none when the tool output nothing. |
| `can_invoke`        | Evaluates subscription conditions to determine whether the node is ready to invoke based on available topics. |
| `can_invoke_with_topics` | Checks if the node can invoke given a specific list of topic names. |
| `model_dump(mode="json")` | Saves the node as data: its tool, subscriptions and routes, naming topics by name. See [Manifests](manifests.md). |

## NodeBaseBuilder

The `NodeBaseBuilder` class provides a fluent interface for constructing nodes with a builder pattern. It allows for readable and maintainable node configuration through method chaining.

Available builder methods:

| Method        | Description                                                                           |
|---------------|---------------------------------------------------------------------------------------|
| `name`        | Sets the unique name for the node within the workflow.                                |
| `type`        | Sets the node type, indicating its function or category.                              |
| `tool`        | Sets the tool for the node, from which its command is made.                           |
| `oi_span_type`| Sets the OpenInference span type for tracing purposes.                                |
| `subscribe`   | Adds subscription expressions to topics or SubExpr objects.                           |
| `publish_to`  | Adds a route to a topic this node publishes events to, taken when its optional `when` predicate returns true for the outgoing event (always, without one). |
| `publisher_router` | Sets the whole `PublisherRouter`, all its routes at once.                        |
| `node_id`     | Sets the node's stable identifier, so a node built again keeps its events' history.  |

Example usage:

```python
from grafi.nodes.node import Node
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic

input_topic = InputTopic(name="input_topic")
output_topic = OutputTopic(name="output_topic")

node = (
    Node.builder()
    .name("ProcessorNode")
    .type("DataProcessor")
    .tool(my_tool)
    .subscribe(input_topic)
    .publish_to(output_topic)
    .build()
)

# Node invoke signature
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent

# Asynchronous invocation
context = InvokeContext(
    conversation_id="conversation-1",
    invoke_id="invoke-1",
    assistant_request_id="request-1",
)
input_datas = [ConsumeFromTopicEvent(...)]  # List of consumed events

async for output_event in node.invoke(context, input_datas):
    # The node's PublishToTopicEvent: one, or none when its tool output nothing
    pass
```
