# Event-Driven Workflow

The event-driven workflow serves as the dynamic execution layer of Graphite, orchestrating node execution through a publish/subscribe (pub/sub) model. This architecture structures workflows as interconnected nodes that communicate via event queues (topics), enabling asynchronous, scalable, and flexible processing.

## Fields

The fields of the EventDrivenWorkflow are:

| Field Name          | Type                              | Description                                                                                           |
|---------------------|-----------------------------------|-------------------------------------------------------------------------------------------------------|
| `name`              | `str`                             | Unique identifier for the workflow instance (default: `"EventDrivenWorkflow"`).                       |
| `type`              | `str`                             | The type identifier for the workflow, typically matching the class name (`"EventDrivenWorkflow"`).    |
| `oi_span_type`      | `OpenInferenceSpanKindValues`     | Semantic attribute from OpenInference used for tracing and observability (default: `AGENT`).         |
| `workflow_id`       | `str`                             | Unique identifier for the workflow instance, auto-generated UUID.                                     |
| `nodes`             | `Dict[str, Node]`                 | Collection of all nodes defined within this workflow, keyed by node name.                             |
| `_topics`           | `Dict[str, TopicBase]`            | Private dictionary storing all event topics managed by the workflow.                                  |
| `_topic_nodes`      | `Dict[str, List[str]]`            | Private mapping of topic names to lists of node names subscribed to each topic.                       |
| `_invoke_queue`     | `deque[Node]`                     | Private queue of nodes that are ready to execute, triggered by event availability.                    |
| `_tracker`          | `AsyncNodeTracker`                | Tracks active nodes and workflow idle state for proper async termination.                             |

## Methods

The following table summarizes key methods within the EventDrivenWorkflow class, highlighting their role in managing workflow execution, event handling, and node orchestration:

| Method Name               | Description                                                                                                                                               |
|---------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `model_post_init`         | Model initialization hook that sets up topics and handles function calling nodes after model creation.                                                  |
| `builder`                 | Class method that returns a WorkflowBuilder for fluent workflow construction.                                                                            |
| `_add_topics`             | Sets up topic subscriptions and node-to-topic mappings from node configurations.                                                                         |
| `_add_topic`              | Registers a topic within the workflow and sets default publish event handlers.                                                                           |
| `_handle_function_calling_nodes` | Links function calling nodes with LLM nodes to enable function specification sharing.                                                             |
| `_a_commit_events`        | Commits processed events to their respective topics, updating consumer offsets.                                                                          |
| `_get_output_events`      | Retrieves and returns consumed events from agent output and in-workflow output topics.                                                                   |
| `invoke`                  | Synchronous workflow execution that processes nodes from the invoke queue until completion.                                                              |
| `a_invoke`                | Asynchronous workflow execution with streaming support and concurrent node processing.                                                                   |
| `_invoke_node`            | Invokes a single node asynchronously with proper stream handling and error management.                                                                   |
| `a_init_workflow`         | Asynchronously initializes workflow state, either restoring from stored events or creating new workflow with input data.                                |
| `on_event`                | Event handler that responds to topic publish events, evaluates node readiness, and queues nodes for execution.                                          |
| `initial_workflow`        | Initializes workflow state, either restoring from stored events or creating new workflow with input data.                                               |
| `to_dict`                 | Serializes the workflow to a dictionary representation including nodes, topics, and topic-node mappings.                                                |

## Workflow Execution Flow

The following diagram illustrates the execution flow of a Node within an event-driven workflow:

```mermaid
graph TD
    Start[Start Workflow Execution] --> Init[initial_workflow: Restore or Initialize State]
    Init --> EventListener[Event Listener: on_event]
    EventListener --> CheckCriteria[Evaluate Node can_invoke Criteria]
    CheckCriteria -->|Conditions Met| QueueNode[Add Node to _invoke_queue]
    QueueNode --> InvokeNode[Execute Next Node in Queue]
    InvokeNode --> PublishResults[Publish Results via _publish_events]
    PublishResults --> EventListener
    EventListener -->|No Pending Nodes| Output[Assistant Output]
```

## Workflow Initialization

When an EventDrivenWorkflow instance is initialized, the `model_post_init` method performs several critical setup tasks:

1. **Topic Setup** (`_add_topics`): Constructs the workflow graph by analyzing each node's subscription expressions and publish destinations
2. **Function Calling Integration** (`_handle_function_calling_nodes`): Links function-calling nodes with LLM nodes to enable tool recognition

The topic setup process:

- Extracts topics from node subscription expressions using `extract_topics`
- Maps topic names to subscribing node names in `_topic_nodes`
- Registers all topics in the `_topics` dictionary with event handlers
- Validates that required `InputTopic` and `OutputTopic` exist

For function calling capabilities:

- Identifies nodes using `FunctionCallTool`
- Links them with LLM nodes that publish to the same topics
- Enables LLMs to recognize and invoke available function tools

```mermaid
graph TD
    A[Initialize Workflow] --> B[model_post_init]
    B --> C[_add_topics: Build Topic Graph]
    B --> D[_handle_function_calling_nodes]
    C --> E([Extract Topics from Nodes])
    C --> F([Map Topics to Nodes])
    C --> G([Register Event Handlers])
    D --> H([Link Function Tools to LLMs])
    E --> I([Validate Required Topics])
    F --> I
    G --> I
    H --> I
    I --> J[Workflow Ready]
```

## Node Execution Process

The EventDrivenWorkflow supports both synchronous (`invoke`) and asynchronous (`a_invoke`) execution modes, each handling node orchestration differently.

### Synchronous Execution (`invoke`)

1. **Workflow Initialization**: Calls `initial_workflow` to restore state or set up new workflow
2. **Node Processing Loop**: Processes nodes from `_invoke_queue` sequentially until empty
3. **Event Collection**: Collects consumed events using `_get_consumed_events`
4. **Output Assembly**: Sorts output messages by timestamp and returns results

### Asynchronous Execution (`a_invoke`)

The asynchronous execution model provides sophisticated event-driven processing with proper coordination:

1. **Workflow Initialization**: Sets up initial state with `a_init_workflow`
2. **Concurrent Node Processing**: Spawns individual tasks for each node using `_invoke_node`  
3. **Output Listening**: Creates listeners for each output topic to capture results
4. **Event Streaming**: Uses `MergeIdleQueue` to stream events as they become available
5. **Proper Termination**: Coordinates workflow completion using `AsyncNodeTracker`

#### Key Components

- **AsyncNodeTracker**: Manages active node state and idle detection
- **Output Listeners**: Monitor output topics for new events
- **MergeIdleQueue**: Coordinates between event availability and workflow idle state
- **Offset Management**: Commits events immediately to prevent duplicates

### Event-Driven Node Triggering

The pub/sub model governs node execution through the `on_event` handler:

1. **Event Reception**: Receives `PublishToTopicEvent` from topics
2. **Subscriber Identification**: Finds all nodes subscribed to the published topic
3. **Readiness Check**: Evaluates each node's `can_invoke()` criteria
4. **Queue Management**: Adds ready nodes to `_invoke_queue` for execution

```mermaid
graph TD
    A[Event Published] --> B[on_event Handler]
    B --> C[Find Subscribed Nodes]
    C --> D{Node can_invoke?}
    D -->|Yes| E[Add to _invoke_queue]
    D -->|No| F[Wait for More Events]
    E --> G[Node Execution]
    G --> H[Publish Results]
    H --> A
    F --> A
```

## Input Preparation & Execution Logic

Before executing a node, the workflow's `get_node_input` method collects all relevant events from the node's subscribed topics:

1. **Topic Iteration**: Processes each topic in `node._subscribed_topics`
2. **Event Consumption**: Uses `topic.consume(node.name)` to retrieve available events
3. **Event Conversion**: Converts topic events to `ConsumeFromTopicEvent` instances
4. **Input Assembly**: Returns list of consumed events for node execution

### Subscription Logic Support

The system provides flexible subscription expressions through topic expressions that support complex logic:

- **AND Logic**: Node executes when ALL subscription conditions are met
- **OR Logic**: Node executes when ANY subscription condition is met

## Async Flow Architecture

The EventDrivenWorkflow implements a sophisticated async architecture that addresses the challenges of coordinating multiple concurrent nodes while ensuring proper workflow termination and data consistency.

### AsyncNodeTracker

The `AsyncNodeTracker` manages workflow state and coordination:

```python
class AsyncNodeTracker:
    def __init__(self) -> None:
        self._active: set[str] = set()
        self._processing_count: Dict[str, int] = defaultdict(int)
        self._cond = asyncio.Condition()
        self._idle_event = asyncio.Event()
```

#### Key Features

- **Active Node Tracking**: Maintains a set of currently processing nodes
- **Processing Count**: Tracks total processing cycles to detect workflow progress
- **Idle Detection**: Signals when no nodes are active
- **Activity Monitoring**: Detects when new processing activity occurs

### Output Listeners and MergeIdleQueue

The async workflow uses output listeners to monitor topics and a merge queue to coordinate termination:

```python
# Launch one listener per output topic
listener_tasks = [
    asyncio.create_task(output_listener(t, queue, self.name, self._tracker))
    for t in output_topics
]

# Coordinate between data availability and workflow idle state
async for event in MergeIdleQueue(queue, self._tracker):
    yield event.data
```

#### MergeIdleQueue Logic

The `MergeIdleQueue` implements sophisticated termination logic:

1. **Data Available**: If queue has data, yield it immediately
2. **Idle Detection**: If workflow becomes idle, check for completion
3. **Grace Period**: Allow time for downstream node activation
4. **Activity Monitoring**: Track processing count to detect progress

### Offset Management and Duplicate Prevention

The async workflow implements proper offset management to prevent duplicate data:

```python
async for event in MergeIdleQueue(queue, self._tracker):
    consumed_output_event = ConsumeFromTopicEvent(...)
    
    # Commit BEFORE yielding to prevent duplicate data
    await self._a_commit_events(
        consumer_name=self.name, events=[consumed_output_event]
    )
    
    # Now yield the data after committing
    yield event.data
```

#### Key Principles

- **Immediate Consumption**: Consumed offset advanced on fetch
- **Commit Before Yield**: Prevents duplicate data in output stream
- **Atomic Operations**: Event processing and commitment are coordinated

### Node Lifecycle in Async Mode

Each node runs in its own async task with proper coordination:

```python
async def _invoke_node(self, invoke_context: InvokeContext, node: Node):
    buffer: Dict[str, List[TopicEvent]] = {}
    
    try:
        while not self._stop_requested:
            # Wait for node to have sufficient data
            await wait_node_invoke(node)
            
            # Signal node is becoming active
            await self._tracker.enter(node.name)
            
            try:
                # Process events and publish results
                async for msgs in node.a_invoke(invoke_context, consumed_events):
                    published_events = await a_publish_events(...)
                    # Notify downstream nodes immediately
                    for event in published_events:
                        if event.topic_name in self._topic_nodes:
                            topic = self._topics[event.topic_name]
                            async with topic.event_cache._cond:
                                topic.event_cache._cond.notify_all()
                
                # Commit processed events
                await self._a_commit_events(...)
                
            finally:
                # Signal node is no longer active
                await self._tracker.leave(node.name)
                
    except asyncio.CancelledError:
        logger.info(f"Node {node.name} was cancelled")
        raise
```

#### Node Coordination Features

- **Buffer Management**: Each node maintains its own event buffer
- **Activity Signaling**: Nodes signal when they become active/inactive
- **Immediate Notification**: Downstream nodes notified immediately after publishing
- **Proper Cleanup**: Resources cleaned up on cancellation

### Workflow Termination Logic

The workflow terminates when all conditions are met:

1. **No Active Nodes**: `AsyncNodeTracker` reports idle state
2. **No Pending Data**: Output topics have no unconsumed data
3. **No Progress**: Activity count indicates no new processing cycles

```python
# Check for workflow completion
if tracker.is_idle() and not topic.can_consume(consumer_name):
    current_activity = tracker.get_activity_count()
    
    # If no new activity since last check, we're done
    if current_activity == last_activity_count:
        break
    
    last_activity_count = current_activity
```

This multi-layered approach ensures that workflows terminate cleanly without missing data or creating race conditions between upstream completion and downstream activation.
- **Complex Expressions**: Combination of AND/OR operators for advanced logic

**Important Consideration for OR Logic**: When using OR-based subscriptions, nodes are queued as soon as one condition is satisfied. Messages from other subscribed topics in the OR expression may not be available when `get_node_input` executes, potentially causing data inconsistencies. Careful design is recommended when implementing OR-based logic.

### Node Execution Flow

```mermaid
graph TD
    A[Node Ready to Execute] --> B[get_node_input]
    B --> C[Check Subscribed Topics]
    C --> D[Consume Available Events]
    D --> E[Convert to ConsumeFromTopicEvent]
    E --> F[Execute Node]
    F --> G[Publish Results via _publish_events]
    G --> H[Trigger on_event for Subscribers]
```

## Restoring Unfinished Workflows

A key advantage of this event-driven architecture is its ability to restore and resume unfinished workflows. When `initial_workflow()` is called, the system:

1. **Event Store Check**: Retrieves stored events for the given `assistant_request_id`
2. **State Restoration**: If events exist, restores workflow topics and state from stored events
3. **Fresh Start**: If no events exist, publishes input to `InputTopic` to begin new workflow
4. **Topic Restoration**: Replays stored `PublishToTopicEvent` and `OutputTopicEvent` to restore topic states
5. **Node Queue Setup**: Evaluates node readiness and populates `_invoke_queue` appropriately

### Benefits of Workflow Restoration

- **Human-in-the-Loop Support**: Workflows can pause while awaiting user input and resume seamlessly
- **Failure Recovery**: Resume from failure points without restarting entire workflows
- **Cost Efficiency**: Prevents unnecessary re-execution of previous steps, reducing LLM call costs
- **State Consistency**: Maintains exact workflow state across interruptions

```mermaid
graph TD
    A[initial_workflow Called] --> B{Events Exist for assistant_request_id?}
    B -->|No| C[Publish Input to InputTopic]
    B -->|Yes| D[Reset All Topics]
    D --> E[Restore Events from Event Store]
    E --> F[Replay PublishToTopicEvent Events]
    F --> G[Evaluate Node Readiness]
    G --> H[Populate _invoke_queue]
    C --> I[Begin Fresh Workflow]
    H --> I
```

This restoration mechanism enables robust, fault-tolerant workflows that can handle interruptions gracefully while maintaining consistency and efficiency.
