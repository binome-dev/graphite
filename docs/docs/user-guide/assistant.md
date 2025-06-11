# Assistant

In our platform, the **Assistant** serves as the primary interface between the user and the underlying agent system. Its core responsibility includes processing user input, constructing and managing workflows, and coordinating interactions between users and the workflow components.

## AssistantBase Class

The `AssistantBase` class provides an abstract base interface defining the foundational properties required by all assistants.

### AssistantBase Class Fields

| Field            | Description                                                         |
|------------------|---------------------------------------------------------------------|
| `assistant_id`   | Unique identifier for the assistant instance.                       |
| `name`           | Human-readable name identifying the assistant.                      |
| `type`           | Category or type specification for the assistant.                   |
| `oi_span_type`   | Semantic attribute from OpenInference for tracing purposes.         |
| `workflow`       | Associated workflow instance managed by the assistant.              |

## Assistant Class

The concrete `Assistant` class extends `AssistantBase`, implementing workflow execution and managing the interactions between user inputs and the agent’s workflow components.

### Assistant Class Methods

| Method                | Description                                                                                                  |
|-----------------------|--------------------------------------------------------------------------------------------------------------|
| `execute`             | Processes input messages synchronously through the workflow and returns sorted response messages.            |
| `a_execute`           | Processes input messages asynchronously through the workflow, suitable for streaming or concurrent use cases.|
| `_get_consumed_events`| Internally retrieves and processes consumed events from workflow topics.                                     |
| `to_dict`             | Serializes the assistant's workflow state and configuration into a dictionary.                               |
| `generate_manifest`   | Generates a manifest file representing the assistant’s configuration and workflow state.                     |

Both `AssistantBase` and `Assistant` utilize an inner `Builder` class to facilitate structured and configurable construction of Assistant instances, enhancing clarity and ease of use.

Developers can extend the base classes to implement specific business logic or functionality required by their unique applications. By leveraging the provided interfaces, assistants can seamlessly manage complex workflow orchestration and user interaction scenarios.
