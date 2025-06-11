# Conventional Rules

While the platform is designed for maximum flexibility, certain conventions guide how components interact. These rules ensure consistency, maintainability, and ease of integration across a range of use cases—especially when handling user requests, generating outputs, and enabling powerful LLM features.

## Reserved Topics

### Agent Input Topic

- **Triggering the Workflow**: All new assistant requests with a fresh `assistant_request_id` begin by publishing the user input to the **agent_input_topic**.
- **Downstream Consumption**: Nodes that need to process initial requests consume from this topic, triggering the rest of the workflow.

### Agent Output Topics

- **Final Responses**: All output events route to **agent_output_topic**, which the Assistant consumes to return data to the user or caller.
- **Single Consumer**: Only the Assistant should subscribe to this topic, avoiding conflicting read operations.

### Human Request Topic

- **Human in the Loop**: Used when user intervention is required; the system posts an `OutputTopicEvent` here, which the Assistant can consume to display prompts or questions.
- **User Response**: When the user replies, `append_user_input()` posts a `PublishToTopicEvent` (the user’s answer). This message is then read by downstream nodes.
- **Assistant Role**: The Assistant only consumes `OutputTopicEvent` objects, while nodes consume both the question (`OutputTopicEvent`) and the final user reply (`PublishToTopicEvent`).

**Rationale**: Structuring input and output channels ensures clarity, preventing multiple consumers from inadvertently processing final outputs and providing a clear path for user-driven requests.

## OutputTopicEvent

- **Dedicated for Assistant**: If a newly received event is an `OutputTopicEvent`, the workflow’s `on_event()` skips subscription checks, since only the Assistant should consume it.
- **Exclusive Destination**: `OutputTopicEvent` can only be published to **agent_output_topic** or **human_request_topic**, ensuring a clear boundary for user-facing outputs.

**Rationale**: Limiting `OutputTopicEvent` usage avoids confusion over who should read final results, reinforcing the principle of single responsibility for returning data to the user.

## Stream Usage

- **Output Only**: Streaming is only relevant for final outputs, letting the LLM emit partial content in real time.
- **Asynchronous Requirement**: Nodes, workflows, and assistants do not support synchronous streaming. Though the LLM tool may have a synchronous stream function, the system’s architecture uses async flows.
- **Usage Pattern**: For practical examples, see `stream_assistant`; it shows how to handle partial token streams differently from normal async generators.

**Rationale**: Maintaining an async-only stream approach for nodes, workflows, and assistants simplifies concurrency, reduces potential race conditions, and provides a consistent development experience.

## LLMFunctionCall

- **Agent-Like Interactions**: By calling functions, the LLM can access additional tools—making the system more agent-like.
- **Separation of Concerns**: The LLM node focuses on generating or interpreting responses, while a separate `LLMFunctionCall` node invokes tool logic.
- **Upstream Connections**: Each `LLMFunctionCall` must directly connect to one or more LLM node via topic(s) when want to enable upstream LLM node tool calling feature.
- **Downstream Connections**: Each LLM node can directly connect to one or more `LLMFunctionCall` nodes. If the workflow builder detects an `LLMFunctionCall` node downstream, it attaches the relevant function specs to the LLM node’s final output message, letting the LLM know which tools are available.

**Rationale**: Decoupling LLM operations from tool invocation keeps the graph modular, fosters reusability, and ensures that an LLM can dynamically discover and call specialized tools within a single workflow.
