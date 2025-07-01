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

The base class defines abstract methods `invoke` and `a_invoke` that must be implemented by concrete subclasses to define their specific behavior.

## Node Implementation

The `Node` class is a concrete implementation of `NodeBase` that provides a working node with standard invoke behavior. Unlike the abstract base class, `Node` actually implements the `invoke` and `a_invoke` methods by delegating to an internal `Command` object.

Key features of the Node class include:

- **Automatic Command Setup**: Creates commands automatically from tools during initialization
- **Event-Driven Invocation**: Uses `can_invoke()` to determine readiness based on subscribed topics
- **Decorator Support**: Includes built-in instrumentation via `@record_node_invoke` and `@record_node_a_invoke`

The following table describes each field within the Node class, highlighting its purpose and usage in the workflow:

| Field                    | Description                                                       |
|--------------------------|-------------------------------------------------------------------|
| `node_id`                | A unique identifier for the node instance.                        |
| `name`                   | A unique name identifying the node within the workflow.           |
| `type`                   | Defines the category or type of node, indicating its function.    |
| `tool`                   | Optional tool that the node uses; automatically creates a command when set. |
| `command`                | Property providing access to the internal command object for invoke logic. |
| `oi_span_type`           | Semantic attribute from OpenInference for tracing purposes.       |
| `subscribed_expressions` | List of DSL-based subscription expressions used by the node.      |
| `publish_to`             | List of designated topics the node publishes events to.           |
| `_subscribed_topics`     | Internal mapping of subscribed topic names to Topic instances.    |
| `_command`               | Private field storing the command object.                         |

The following table summarizes the methods available in the Node class, highlighting their purpose and intended usage:

| Method               | Description                                                                                              |
|----------------------|----------------------------------------------------------------------------------------------------------|
| `builder`           | Class method that returns a `NodeBaseBuilder` for fluent node construction.                              |
| `model_post_init`   | Model post-initialization hook that sets up subscribed topics and auto-creates commands from tools during initialization. |
| `invoke`            | Synchronously invokes the node's command with the provided input events and context.                     |
| `a_invoke`          | Asynchronously invokes the node's command, yielding response messages as they become available.          |
| `can_invoke`        | Evaluates subscription conditions to determine whether the node is ready to invoke based on new events. |
| `to_dict`            | Serializes node attributes to a dictionary, suitable for persistence or transmission.                    |

## NodeBaseBuilder

The `NodeBaseBuilder` class provides a fluent interface for constructing nodes with a builder pattern. It allows for readable and maintainable node configuration through method chaining.

Available builder methods:

| Method        | Description                                                                           |
|---------------|---------------------------------------------------------------------------------------|
| `name`        | Sets the unique name for the node within the workflow.                                |
| `type`        | Sets the node type, indicating its function or category.                              |
| `tool`        | Sets the tool for the node; automatically creates a command from the tool.            |
| `oi_span_type`| Sets the OpenInference span type for tracing purposes.                                |
| `subscribe`   | Adds subscription expressions to topics or SubExpr objects.                           |
| `publish_to`  | Adds topics that this node will publish events to.                                    |

Example usage:

```python
node = Node.builder()
    .name("ProcessorNode")
    .type("DataProcessor")
    .tool(my_tool)
    .subscribe(input_topic)
    .publish_to(output_topic)
    .build()
```
