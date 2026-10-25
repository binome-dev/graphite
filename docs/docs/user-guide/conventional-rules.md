# Conventional Rules

While the platform is designed for maximum flexibility, certain conventions guide how components interact. These rules ensure consistency, maintainability, and ease of integration across a range of use cases—especially when handling user requests, generating outputs, and enabling powerful LLM features.

## Reserved Topics

### Agent Input Topic

- **Triggering the Workflow**: All new assistant requests with a fresh `assistant_request_id` begin by publishing the user input to the **agent_input_topic**.
- **Downstream Consumption**: Nodes that need to process initial requests consume from this topic, triggering the rest of the workflow.

### Agent Output Topics

- **Final Responses**: All output events route to **agent_output_topic**, which the Assistant consumes to return data to the user or caller.
- **Single Consumer**: Only the Assistant should subscribe to this topic, avoiding conflicting read operations.

### InWorkflow Topics

- **Human in the Loop**: Used when user intervention is required within workflows; the system uses paired InWorkflowOutputTopic and InWorkflowInputTopic for coordinated human interactions.
- **InWorkflowOutputTopic**: Posts `OutputTopicEvent` objects that require human interaction or review.
- **InWorkflowInputTopic**: Receives user responses via `publish_input_data()` based on upstream events from the paired output topic.
- **Workflow Coordination**: These topics work together to enable seamless human-in-the-loop workflows with proper event coordination.

**Rationale**: Structuring input and output channels ensures clarity, preventing multiple consumers from inadvertently processing final outputs and providing a clear path for user-driven requests.

## OutputTopicEvent

- **Dedicated for Assistant**: If a newly received event is an `OutputTopicEvent`, the workflow's `on_event()` skips subscription checks, since only the Assistant should consume it.
- **Exclusive Destination**: `OutputTopicEvent` can only be published to **agent_output_topic** or **InWorkflowOutputTopic**, ensuring a clear boundary for user-facing outputs.

**Rationale**: Limiting `OutputTopicEvent` usage avoids confusion over who should read final results, reinforcing the principle of single responsibility for returning data to the user.

## Stream Usage

- **Caller's Choice**: The caller decides whether to stream, with `invoke(..., stream=True)`. It then gets the deltas the tools emit, such as an LLM's tokens, between the outputs.
- **Side Channel**: Deltas are never published to topics or stored. Routing and the event log only see whole messages, so a stream never changes what a workflow does.
- **Usage Pattern**: For practical examples, see `simple_stream_assistant`; it shows a caller reading deltas and outputs from one stream.

**Rationale**: Keeping partial output out of the event log keeps routing decisions and history to whole messages, and keeps the log to a few records per step rather than one per token.

## Function Calls

- **Agent-Like Interactions**: By calling functions, the LLM can access additional tools, making the system more agent-like.
- **Separation of Concerns**: The LLM node focuses on generating or interpreting responses, while a separate function-call node, running a `FunctionCallTool`, invokes tool logic.
- **Connections**: A function-call node subscribes to a topic an LLM node publishes its calls to (or, for an in-workflow output topic, to a topic paired with it), and publishes the results back to a topic the LLM node reads.
- **Wiring**: As each run starts, the workflow offers each LLM node the functions of the function-call nodes reading its calls, and makes one function-call node on each topic carrying calls answer, with an error, a call naming a function no LLM calling there was offered. See [Event-Driven Workflow](event-driven-workflow.md#workflow-initialization).

**Rationale**: Decoupling LLM operations from tool invocation keeps the graph modular, fosters reusability, and ensures that an LLM can dynamically discover and call specialized tools within a single workflow.
