# Output Topics

The Graphite output topic system provides specialized topic implementations for handling output events from workflows and nodes. These topics support both synchronous and asynchronous message processing, streaming capabilities, and human-in-the-loop workflows.

## Overview

The output topic system includes:

- **OutputTopic**: Handles agent output with async generator support and streaming
- **InWorkflowOutputTopic**: Handles workflow output that requires human interaction
- **Async Processing**: Support for async generators and streaming responses
- **Event Queuing**: Queue-based event management for real-time processing
- **Reserved Topics**: Pre-configured topics for agent communication

## Core Components

### OutputTopic

A specialized topic for handling agent output with advanced async capabilities.

#### OutputTopic Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Topic name (defaults to "agent_output_topic") |
| `event_queue` | `asyncio.Queue[OutputAsyncEvent]` | Queue for async events |
| `active_generators` | `List[asyncio.Task]` | List of running generator tasks |
| `publish_event_handler` | `Optional[Callable[[OutputTopicEvent], None]]` | Handler for publish events |

*Inherits all fields from `TopicBase`: `condition`, `consumption_offsets`, `topic_events`*

#### OutputTopic Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `builder` | `() -> OutputTopicBuilder` | Class method returning builder instance |
| `publish_data` | `(invoke_context, publisher_name, publisher_type, data, consumed_events) -> Optional[OutputTopicEvent]` | Publish messages synchronously |
| `add_generator` | `(generator, data, invoke_context, publisher_name, publisher_type, consumed_events) -> None` | Add async generator for streaming |
| `get_events` | `() -> AsyncIterator[OutputAsyncEvent]` | Get events as they become available |
| `wait_for_completion` | `() -> None` | Wait for all generators to complete |
| `reset` | `() -> None` | Reset topic and cancel generators |

#### Internal Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `_process_generator` | `(generator, data, invoke_context, publisher_name, publisher_type, consumed_events) -> None` | Process async generator internally |

### InWorkflowOutputTopic

A specialized topic for handling workflow output that requires human interaction.

#### InWorkflowOutputTopic Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Topic name for workflow output |
| `paired_in_workflow_input_topic_name` | `str` | Name of the paired input topic |
| `type` | `str` | Topic type ("InWorkflowOutput") |

*Inherits all fields from `TopicBase`: `condition`, `event_cache`, etc.*

#### InWorkflowOutputTopic Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `builder` | `() -> InWorkflowOutputTopicBuilder` | Class method returning builder instance |
| `publish_data` | `(invoke_context, publisher_name, publisher_type, data, consumed_events) -> OutputTopicEvent` | Async version of publish_data |

### Builders

#### OutputTopicBuilder

Enhanced builder for OutputTopic instances.

| Method | Signature | Description |
|--------|-----------|-------------|
| `publish_event_handler` | `(handler: Callable[[OutputTopicEvent], None]) -> Self` | Set event handler for publish operations |

#### InWorkflowOutputTopicBuilder

Enhanced builder for InWorkflowOutputTopic instances.

| Method | Signature | Description |
|--------|-----------|-------------|
| `paired_in_workflow_input_topic_name` | `(name: str) -> Self` | Set the paired input topic name |

## Reserved Topics

The system includes pre-configured topic instances:

```python
AGENT_OUTPUT_TOPIC = "agent_output_topic"
IN_WORKFLOW_INPUT_TOPIC_TYPE = "InWorkflowInput"
IN_WORKFLOW_OUTPUT_TOPIC_TYPE = "InWorkflowOutput"

# Example topic instances
agent_output_topic = OutputTopic(name=AGENT_OUTPUT_TOPIC)
```

Workflow topics are typically created as pairs for human-in-the-loop interactions.

## OutputTopic Usage

### Basic Output Publishing

```python
from grafi.topics.output_topic import OutputTopic, agent_output_topic
from grafi.common.models.message import Message
from grafi.common.models.invoke_context import InvokeContext

# Create context and messages
context = InvokeContext()
messages = [Message(role="assistant", content="Hello, user!")]

# Publish to output topic
event = agent_output_topic.publish_data(
    invoke_context=context,
    publisher_name="chatbot",
    publisher_type="assistant",
    data=messages,
    consumed_events=[]
)

if event:
    print(f"Published output: {event.event_id}")
```

### Async Generator Support

```python
import asyncio
from typing import AsyncIterator
from grafi.common.models.message import Messages

async def streaming_response() -> AsyncIterator[Messages]:
    """Example async generator for streaming responses."""
    responses = [
        [Message(role="assistant", content="Let me think...")],
        [Message(role="assistant", content="The answer is 42.")],
        [Message(role="assistant", content="Is there anything else?")]
    ]

    for response in responses:
        await asyncio.sleep(0.1)  # Simulate processing delay
        yield response

# Add generator to output topic
initial_data = [Message(role="assistant", content="Starting calculation...")]
agent_output_topic.add_generator(
    generator=streaming_response(),
    data=initial_data,
    invoke_context=context,
    publisher_name="calculator",
    publisher_type="tool",
    consumed_events=[]
)
```

### Event Streaming

```python
async def consume_output_events():
    """Consume events as they become available."""
    async for event in agent_output_topic.get_events():
        print(f"Received event: {event.event_id}")
        for message in event.data:
            print(f"Content: {message.content}")

        # Process the event
        await process_output_event(event)

# Run the consumer
asyncio.run(consume_output_events())
```

### Generator Management

```python
async def managed_streaming():
    """Example of managing multiple generators."""
    # Add multiple generators
    agent_output_topic.add_generator(
        generator=stream1(),
        data=initial_data1,
        invoke_context=context,
        publisher_name="stream1",
        publisher_type="generator"
    )

    agent_output_topic.add_generator(
        generator=stream2(),
        data=initial_data2,
        invoke_context=context,
        publisher_name="stream2",
        publisher_type="generator"
    )

    # Wait for all generators to complete
    await agent_output_topic.wait_for_completion()

    print("All generators completed")
```

## InWorkflowOutputTopic Usage

### Publishing Workflow Output for Human Interaction

```python
from grafi.topics.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.common.models.message import Message

# Create workflow output topic (paired with an input topic)
workflow_output_topic = InWorkflowOutputTopic(
    name="review_output",
    paired_in_workflow_input_topic_name="review_input"
)

# Create message for human review
review_message = [Message(role="assistant", content="Please review this document.")]

# Publish to workflow output topic (triggers human interaction)
event = workflow_output_topic.publish_data(
    invoke_context=context,
    publisher_name="document_reviewer",
    publisher_type="agent",
    data=review_message,
    consumed_events=[]
)

print(f"Sent request for review: {event.event_id}")
```

### Integration with InWorkflowInputTopic

```python
# InWorkflowOutputTopic works in tandem with InWorkflowInputTopic
# When a human responds, the paired InWorkflowInputTopic receives the response
# See input_topics.md for complete paired topic examples
```

### Human-in-the-Loop Workflow Example

```python
class HumanApprovalWorkflow:
    def __init__(self):
        self.pending_approvals = {}

        # Create workflow output topic for human interaction
        self.output_topic = InWorkflowOutputTopic(
            name="approval_output",
            paired_in_workflow_input_topic_name="approval_input"
        )

    def handle_workflow_output(self, event: OutputTopicEvent):
        """Handle workflow output events (requests sent to human)."""
        self.pending_approvals[event.event_id] = {
            "event": event,
            "status": "pending",
            "timestamp": event.timestamp
        }
        print(f"Approval request sent: {event.event_id}")

    async def request_approval(self, document: str) -> OutputTopicEvent:
        """Request human approval for a document."""
        approval_message = [Message(
            role="assistant",
            content=f"Please approve this document: {document}"
        )]

        # Publish to workflow output topic
        event = await self.output_topic.publish_data(
            invoke_context=InvokeContext(),
            publisher_name="approval_system",
            publisher_type="workflow",
            data=approval_message,
            consumed_events=[]
        )

        self.handle_workflow_output(event)
        return event

# Note: User responses are handled via the paired InWorkflowInputTopic
# See input_topics.md for complete workflow examples
```

## Best Practices

### Output Topic Design

1. **Generator Management**: Always wait for generator completion or implement timeouts
2. **Memory Management**: Monitor event queue size to prevent memory issues
3. **Error Handling**: Implement proper error handling for async operations
4. **Resource Cleanup**: Use reset() to properly clean up resources

### InWorkflowOutputTopic Patterns

1. **Topic Pairing**: Always specify the paired InWorkflowInputTopic name
2. **Event Publishing**: Use OutputTopicEvent for human-directed messages
3. **State Tracking**: Track pending requests for human responses
4. **Integration**: Coordinate with InWorkflowInputTopic for complete workflows

### Performance Optimization

1. **Queue Management**: Monitor and manage event queue sizes
2. **Generator Cleanup**: Properly cancel and clean up completed generators
3. **Event Batching**: Consider batching events for high-throughput scenarios
4. **Memory Monitoring**: Track memory usage for long-running streams

### Testing Strategies

```python
async def test_output_topic():
    """Test output topic functionality."""
    topic = OutputTopic(name="test_output")

    # Test basic publishing
    messages = [Message(role="assistant", content="test")]
    event = await topic.publish_data(
        invoke_context=InvokeContext(),
        publisher_name="test",
        publisher_type="test",
        data=messages,
        consumed_events=[]
    )

    assert event is not None
    assert len(topic.topic_events) == 1

    # Test generator addition
    async def test_generator():
        yield [Message(role="assistant", content="stream1")]
        yield [Message(role="assistant", content="stream2")]

    topic.add_generator(
        generator=test_generator(),
        data=[],
        invoke_context=InvokeContext(),
        publisher_name="test_gen",
        publisher_type="test"
    )

    # Collect events
    events = []
    async for event in topic.get_events():
        events.append(event)

    assert len(events) >= 2  # At least 2 streaming events

    # Clean up
    topic.reset()
    assert len(topic.active_generators) == 0

def test_workflow_output_topic():
    """Test workflow output topic functionality."""
    # Create workflow output topic
    output_topic = InWorkflowOutputTopic(
        name="test_output",
        paired_in_workflow_input_topic_name="test_input"
    )

    # Test publishing to workflow output
    messages = [Message(role="assistant", content="Please review")]
    output_event = output_topic.publish_data(
        invoke_context=InvokeContext(),
        publisher_name="test",
        publisher_type="test",
        data=messages,
        consumed_events=[]
    )

    assert output_event is not None
    assert output_event.topic_name == "test_output"
    assert len(output_topic.event_cache._records) == 1

    # Verify paired topic name is set
    assert output_topic.paired_in_workflow_input_topic_name == "test_input"
```

The output topic system provides powerful capabilities for handling agent outputs, streaming responses, and workflow interactions in Graphite applications, supporting both real-time and batch processing scenarios with comprehensive error handling and monitoring capabilities. The new InWorkflow topics enable seamless human-in-the-loop workflows with proper event coordination and state management.
