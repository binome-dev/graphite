# Features

The core design principles that set Graphite apart from other agent frameworks are:

1. **A Simple 3-Layer Invoke Model**  
   Three distinct layers—assistant, node, and tool—manage invoke, while a dedicated workflow layer oversees orchestration.

2. **Pub/Sub Event-Driven Orchestration**  
   Communication relies on publishing and subscribing to events, ensuring a decoupled, modular flow of data throughout the system.

3. **Events as the Single Source of Truth**  
   All operational states and transitions are recorded as events, providing a uniform way to track and replay system behavior if needed.

Combining these elements, **Graphite** provides a production-grade AI application framework capable of operating reliably at scale, handling failures gracefully, and maintaining user and stakeholder trust. Four essential capabilities form the backbone of this approach:

1. **Observability**  
   Complex AI solutions involve multiple steps, data sources, and models. Graphite’s event-driven architecture, logging, and tracing make it possible to pinpoint bottlenecks or errors in real time, ensuring that each component’s behavior is transparent and measurable.

2. **Idempotency**  
   Asynchronous workflows often require retries when partial failures occur or network conditions fluctuate. Graphite’s design emphasizes idempotent operations, preventing pub/sub data duplication or corruption when calls must be repeated.

3. **Auditability**  
   By treating events as the single source of truth, Graphite automatically logs every state change and decision path. This level of detailed recordkeeping is indispensable for users working in regulated sectors or who need full traceability for debugging and compliance.

4. **Restorability**  
   Long-running AI tasks risk substantial rework if they fail mid-invoke. In Graphite, checkpoints and event-based playback enable workflows to resume from the precise point of interruption, minimizing downtime and maximizing resource efficiency.

Together, these capabilities—observability, idempotency, auditability, and restorability—distinguish **Graphite** as a framework for building robust and trustworthy AI applications. Below is a detailed breakdown of how Graphite implements each feature.

## Observability

The system leverages event sourcing to record all operations, combined with OpenTelemetry for standardized tracing. Thanks to the clearly defined three-layer invoke model (assistant, node, tool) plus an orchestration workflow, each invoke function is decorated to capture inputs, outputs, and any exceptions. These captures are converted into events (stored in the event store) and traces (exported to platforms like Arize or other OpenTelemetry services).

Meanwhile, each Topic instance logs pub/sub interactions in the event store after processing. Coupled with the InvokeContext object, this approach makes the entire data flow within the agentic workflow fully transparent. Because every node and tool has a unique name and ID, and each operation is stamped with invoke context IDs, locating specific inputs and outputs is straightforward. Then given pub/sub events, the framework can build directed data flows between nodes. Even when there are circles, the data flow can form a DAG with publishing and consuming offset in each topic.

## Idempotency

Graphite adopts an event-driven architecture where topics function as logical message queues, storing each event exactly once in an event store. When a workflow fails, needs to be retried, or is paused (e.g., for a human-in-the-loop intervention), it can resume from the last known valid state by replaying events that were produced but not yet consumed by downstream nodes.

Consumption events are only recorded once the entire node processing completes successfully. Until that point, the system treats partial or failed node invokes as if they never happened, preventing duplicated outputs or broken states. Should a node encounter an error (e.g., an LLM connection failure, external API issue, or function exception), Graphite detects the unconsumed events upon restoration and places the associated node(s) back into the invoke queue. This design ensures the node can safely retry from the same input without creating conflicting or duplicated consumption records.

By storing each event exactly once and withholding consumption records until success, Graphite guarantees idempotent behavior. Even if a node issues multiple invocations due to an error, the event logs and consumption rules still reconstruct a single, consistent path from invocation to response. This approach produces correct outcomes on retries while maintaining a complete, conflict-free audit trail.

## Auditability

Auditability in Graphite emerges naturally from its observability. By automatically persisting all invoke events and pub/sub events in a centralized event store, the platform provides a complete historical record of every action taken. Function decorators capture each invoke (including inputs, outputs, and exceptions), while Topic operations log every publish and consume operation, and effectively acting as a “cache” layer of orchestration events.

Moreover, Graphite’s modular design and clear separation of concerns simplify the process of examining specific components—such as an LLM node and its associated tool. Each module has well-defined responsibilities, ensuring that every action is accurately documented in the event store and easily traceable. This end-to-end audit trail not only supports today’s nascent AI regulations but positions Graphite to adapt to evolving compliance requirements. By preserving all relevant data in a consistent, verifiable format, Graphite provides the transparency and accountability that organizations demand from AI solutions.

## Restorability

Restorability in Graphite builds on top of idempotency, ensuring that whenever a workflow stops—due to an exception, human intervention, or any other cause—it always concludes at a point where an event has been successfully published. This guarantees that upon resuming the workflow for an unfinished assistant_request_id, any node subscribed to that newly published event is reactivated, effectively restarting the process from where it left off.

Internally, Graphite uses offset-based consumption in each topic. Whenever a node publishes an event (including self-loops or circular dependencies), the system records the publish offset in `PublishToTopicEvent` instance. When a node later consumes that event, it updates a corresponding consumption offset in topic, and store the offset in `ConsumeFromTopicEvent`. If a workflow is interrupted before consumption offsets are written, the node remains subscribed to the “unconsumed” event. As a result, when the workflow recovers, the engine identifies these outstanding events and places the node(s) back into the invoke queue.

This mechanism effectively transforms cyclical or looping dependencies into a directed acyclic graph. The event store, combined with offset tracking, reveals which events have been fully processed and which remain pending, letting Graphite re-trigger only the incomplete parts of the workflow. The result is a resilient system that can resume from exactly where it stopped—without reprocessing entire segments or risking inconsistent states.
