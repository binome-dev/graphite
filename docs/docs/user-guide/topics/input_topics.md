# Input Topics

The Graphite input topic system provides specialized topic implementations for handling workflow inputs, including initial user inputs and human-in-the-loop interactions. These topics serve as entry points for data flowing into the workflow system.

## Overview

The input topic system includes:

- **InputTopic**: Handles initial agent input from users or external systems
- **InWorkflowInputTopic**: Manages input within workflows, particularly for human-in-the-loop scenarios
- **Event Publishing**: Converts input data into publishable topic events
- **Workflow Integration**: Seamlessly integrates with the event-driven workflow system

## Core Components

### InputTopic

The foundational topic for receiving initial input into a workflow.

#### InputTopic Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Topic name (typically "agent_input_topic") |
| `type` | `str` | Topic type identifier ("AgentInput") |
| `condition` | `Callable[[Messages], bool]` | Function to filter publishable messages |
| `event_cache` | `TopicEventQueue` | Manages event storage and consumer offsets |

*Inherits all fields from `TopicBase`*

#### InputTopic Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `builder` | `() -> InputTopicBuilder` | Class method returning builder instance |
| `publish_data` | `(invoke_context, publisher_name, publisher_type, data, consumed_events) -> PublishToTopicEvent` | Publish input messages to the topic |
| `a_publish_data` | `(invoke_context, publisher_name, publisher_type, data, consumed_events) -> PublishToTopicEvent` | Async version of publish_data |

### InWorkflowInputTopic

A specialized input topic for managing human-in-the-loop interactions within running workflows.

#### InWorkflowInputTopic Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Topic name for workflow input |
| `type` | `str` | Topic type identifier ("InWorkflowInput") |
| `paired_in_workflow_output_topic_name` | `str` | Name of the paired output topic |
| `condition` | `Callable[[Messages], bool]` | Function to filter publishable messages |
| `event_cache` | `TopicEventQueue` | Manages event storage and consumer offsets |

*Inherits all fields from `TopicBase`*

#### InWorkflowInputTopic Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `builder` | `() -> InWorkflowInputTopicBuilder` | Class method returning builder instance |
| `publish_input_data` | `(upstream_event: OutputTopicEvent, data: Messages) -> PublishToTopicEvent` | Publish input data based on upstream event |
| `a_publish_input_data` | `(upstream_event: OutputTopicEvent, data: Messages) -> PublishToTopicEvent` | Async version of publish_input_data |

### Builders

#### InputTopicBuilder

Builder for constructing InputTopic instances.

| Method | Signature | Description |
|--------|-----------|-------------|
| `name` | `(name: str) -> Self` | Set the topic name |
| `condition` | `(condition: Callable[[Messages], bool]) -> Self` | Set message filtering condition |

#### InWorkflowInputTopicBuilder  

Builder for constructing InWorkflowInputTopic instances.

| Method | Signature | Description |
|--------|-----------|-------------|
| `name` | `(name: str) -> Self` | Set the topic name |
| `paired_in_workflow_output_topic_name` | `(name: str) -> Self` | Set the paired output topic name |
| `condition` | `(condition: Callable[[Messages], bool]) -> Self` | Set message filtering condition |

## InputTopic Usage

### Basic Input Publishing

```python
from grafi.topics.topic import InputTopic
from grafi.common.models.message import Message
from grafi.common.models.invoke_context import InvokeContext

# Create input topic
input_topic = InputTopic(name="agent_input_topic")

# Create context and messages
context = InvokeContext(
    conversation_id="conv_123",
    invoke_id="invoke_456",
    assistant_request_id="req_789"
)
messages = [Message(role="user", content="Hello, assistant!")]

# Publish to input topic
event = input_topic.publish_data(
    invoke_context=context,
    publisher_name="user_interface",
    publisher_type="external",
    data=messages,
    consumed_events=[]
)

print(f"Published input event: {event.event_id}")
```

### Using Builder Pattern

```python
# Build input topic with custom condition
input_topic = (InputTopic.builder()
    .name("custom_input_topic")
    .condition(lambda msgs: len(msgs) > 0 and msgs[0].role == "user")
    .build())
```

### Workflow Integration

```python
from grafi.workflows.workflow import WorkflowBuilder
from grafi.nodes.node import Node

# Create workflow with input topic
workflow = (WorkflowBuilder()
    .node(Node(
        name="input_processor",
        tool=some_tool,
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publish_to=[some_output_topic]
    ))
    .build())
```

## InWorkflowInputTopic Usage

### Creating Paired Topics

```python
from grafi.topics.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.in_workflow_output_topic import InWorkflowOutputTopic

# Create paired topics for human-in-the-loop
workflow_output_topic = InWorkflowOutputTopic(
    name="approval_output",
    paired_in_workflow_input_topic_name="approval_input"
)

workflow_input_topic = InWorkflowInputTopic(
    name="approval_input",
    paired_in_workflow_output_topic_name="approval_output"
)
```

### Publishing User Responses

```python
# When workflow needs human input, it publishes to output topic
output_event = workflow_output_topic.publish_data(
    invoke_context=context,
    publisher_name="approval_node",
    publisher_type="workflow",
    data=[Message(role="assistant", content="Please approve this action")],
    consumed_events=[]
)

# When user responds, publish to paired input topic
user_response = [Message(role="user", content="Approved")]
input_data = workflow_input_topic.publish_input_data(
    upstream_event=output_event,
    data=user_response
)
```

### Async Human-in-the-Loop

```python
async def human_approval_workflow():
    # Setup paired topics
    output_topic = InWorkflowOutputTopic(
        name="review_output",
        paired_in_workflow_input_topic_name="review_input"
    )
    input_topic = InWorkflowInputTopic(
        name="review_input",
        paired_in_workflow_output_topic_name="review_output"
    )

    # Request human review
    review_request = [Message(
        role="assistant",
        content="Please review the following document..."
    )]

    output_event = await output_topic.a_publish_data(
        invoke_context=context,
        publisher_name="review_system",
        publisher_type="workflow",
        data=review_request,
        consumed_events=[]
    )

    # Wait for user response (in real system, this would be event-driven)
    # ...

    # Process user response
    user_feedback = [Message(role="user", content="Looks good, approved!")]
    input_data = await input_topic.a_publish_input_data(
        upstream_event=output_event,
        data=user_feedback
    )

    return input_data
```

## Best Practices

### InputTopic Design

1. **Entry Point**: Use InputTopic as the primary entry point for workflows
2. **Validation**: Implement condition functions to validate input data
3. **Context Preservation**: Always include proper InvokeContext for traceability
4. **Error Handling**: Handle invalid inputs gracefully

### InWorkflowInputTopic Patterns

1. **Topic Pairing**: Always create InWorkflowInputTopic with its paired InWorkflowOutputTopic
2. **Event Correlation**: Use upstream_event to maintain event chain
3. **State Management**: Track workflow state between output and input events
4. **Timeout Handling**: Implement timeouts for human responses

### Integration Guidelines

```python
class HumanInLoopNode(Node):
    def __init__(self, approval_threshold: float = 0.8):
        self.approval_threshold = approval_threshold

        # Create paired topics
        self.output_topic = InWorkflowOutputTopic(
            name=f"{self.name}_output",
            paired_in_workflow_input_topic_name=f"{self.name}_input"
        )
        self.input_topic = InWorkflowInputTopic(
            name=f"{self.name}_input",
            paired_in_workflow_output_topic_name=f"{self.name}_output"
        )

        super().__init__(
            name="human_approval_node",
            tool=self.approval_tool,
            subscribed_expressions=[
                TopicExpr(topic=self.input_topic),
                TopicExpr(topic=some_data_topic)
            ],
            publish_to=[self.output_topic, next_processing_topic]
        )

    async def approval_tool(self, context, events):
        # Process incoming data
        data_events = [e for e in events if e.topic_name == "data_topic"]

        if self.needs_approval(data_events):
            # Request human approval
            approval_request = self.create_approval_request(data_events)
            await self.output_topic.a_publish_data(
                invoke_context=context,
                publisher_name=self.name,
                publisher_type="node",
                data=approval_request,
                consumed_events=events
            )

            # Wait for human response via input_topic
            # (handled by workflow event loop)
```

### Testing Strategies

```python
async def test_input_topics():
    """Test input topic functionality."""
    # Test basic InputTopic
    input_topic = InputTopic(name="test_input")

    messages = [Message(role="user", content="test input")]
    event = await input_topic.a_publish_data(
        invoke_context=InvokeContext(),
        publisher_name="test",
        publisher_type="test",
        data=messages,
        consumed_events=[]
    )

    assert event is not None
    assert event.data == messages
    assert len(input_topic.event_cache._records) == 1

    # Test InWorkflowInputTopic pairing
    output_topic = InWorkflowOutputTopic(
        name="test_output",
        paired_in_workflow_input_topic_name="test_input"
    )
    workflow_input_topic = InWorkflowInputTopic(
        name="test_input",
        paired_in_workflow_output_topic_name="test_output"
    )

    # Simulate workflow output
    output_event = await output_topic.a_publish_data(
        invoke_context=InvokeContext(),
        publisher_name="workflow",
        publisher_type="node",
        data=[Message(role="assistant", content="Need input")],
        consumed_events=[]
    )

    # Simulate user response
    user_response = [Message(role="user", content="Here's my input")]
    input_data = await workflow_input_topic.a_publish_input_data(
        upstream_event=output_event,
        data=user_response
    )

    assert input_data is not None
    assert input_data.data == user_response
    assert input_data.consumed_events == [output_event]
```

## Topic Type Constants

The system defines the following topic type constants:

```python
AGENT_INPUT_TOPIC_TYPE = "AgentInput"
IN_WORKFLOW_INPUT_TOPIC_TYPE = "InWorkflowInput"
```

These constants are used internally for topic type identification and validation within the workflow system.

## Summary

The input topic system provides essential entry points for data flowing into Graphite workflows. InputTopic serves as the primary entry point for initial user requests, while InWorkflowInputTopic enables sophisticated human-in-the-loop interactions within running workflows. Together with their output counterparts, they form a complete system for bidirectional communication in event-driven workflows.