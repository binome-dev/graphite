# Output Topics

The Graphite output topic system provides specialized topic implementations for handling output events and human interactions. These topics support both synchronous and asynchronous message processing, streaming capabilities, and human-in-the-loop workflows.

## Overview

The output topic system includes:

- **OutputTopic**: Handles agent output with async generator support and streaming
- **HumanRequestTopic**: Manages human interactions and user input appending
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

### HumanRequestTopic

A specialized topic for managing human interactions and user input.

#### HumanRequestTopic Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Topic name (defaults to "human_request_topic") |
| `publish_to_human_event_handler` | `Optional[Callable[[OutputTopicEvent], None]]` | Handler for human-directed events |
| `publish_event_handler` | `Optional[Callable[[PublishToTopicEvent], None]]` | Handler for regular publish events |

*Inherits all fields from `TopicBase`: `condition`, `consumption_offsets`, `topic_events`*

#### HumanRequestTopic Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `builder` | `() -> HumanRequestTopicBuilder` | Class method returning builder instance |
| `publish_data` | `(invoke_context, publisher_name, publisher_type, data, consumed_events) -> OutputTopicEvent` | Publish messages to human |
| `append_user_input` | `(user_input_event, data) -> PublishToTopicEvent` | Append user input to conversation |
| `can_append_user_input` | `(consumer_name, event) -> bool` | Check if user input can be appended |

### Builders

#### OutputTopicBuilder

Enhanced builder for OutputTopic instances.

| Method | Signature | Description |
|--------|-----------|-------------|
| `publish_event_handler` | `(handler: Callable[[OutputTopicEvent], None]) -> Self` | Set event handler for publish operations |

#### HumanRequestTopicBuilder

Enhanced builder for HumanRequestTopic instances.

| Method | Signature | Description |
|--------|-----------|-------------|
| `publish_event_handler` | `(handler: Callable[[PublishToTopicEvent], None]) -> Self` | Set event handler for publish operations |
| `publish_to_human_event_handler` | `(handler: Callable[[OutputTopicEvent], None]) -> Self` | Set handler for human-directed events |

## Reserved Topics

The system includes pre-configured topic instances:

```python
AGENT_OUTPUT_TOPIC = "agent_output_topic"
HUMAN_REQUEST_TOPIC = "human_request_topic"

# Pre-configured instances
agent_output_topic = OutputTopic(name=AGENT_OUTPUT_TOPIC)
human_request_topic = HumanRequestTopic(name=HUMAN_REQUEST_TOPIC)
```

These are automatically added to the `AGENT_RESERVED_TOPICS` list.

## OutputTopic Usage

### Basic Output Publishing

```python
from grafi.common.topics.output_topic import OutputTopic, agent_output_topic
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

## HumanRequestTopic Usage

### Publishing to Human

```python
from grafi.common.topics.human_request_topic import HumanRequestTopic, human_request_topic
from grafi.common.models.message import Message

# Create message for human
human_message = [Message(role="assistant", content="Please review this document.")]

# Publish to human request topic
event = human_request_topic.publish_data(
    invoke_context=context,
    publisher_name="document_reviewer",
    publisher_type="agent",
    data=human_message,
    consumed_events=[]
)

print(f"Sent request to human: {event.event_id}")
```

### Appending User Input

```python
# Simulate user response
user_response = [Message(role="user", content="The document looks good!")]

# Check if input can be appended
if human_request_topic.can_append_user_input("user_session", event):
    # Append user input to the conversation
    user_event = human_request_topic.append_user_input(
        user_input_event=event,
        data=user_response
    )
    print(f"User input appended: {user_event.event_id}")
else:
    print("Cannot append user input at this time")
```

### Human-in-the-Loop Workflow

```python
class HumanApprovalWorkflow:
    def __init__(self):
        self.pending_approvals = {}

        # Set up event handlers
        human_request_topic.publish_to_human_event_handler = self.handle_human_request
        human_request_topic.publish_event_handler = self.handle_user_response

    def handle_human_request(self, event: OutputTopicEvent):
        """Handle requests sent to human."""
        self.pending_approvals[event.event_id] = {
            "event": event,
            "status": "pending",
            "timestamp": event.timestamp
        }
        print(f"Approval request sent: {event.event_id}")

    def handle_user_response(self, event: PublishToTopicEvent):
        """Handle user responses."""
        # Find the original request
        for approval_id, approval in self.pending_approvals.items():
            if event.invoke_context == approval["event"].invoke_context:
                approval["status"] = "responded"
                approval["response"] = event
                print(f"User responded to: {approval_id}")
                break

    async def request_approval(self, document: str) -> bool:
        """Request human approval for a document."""
        approval_message = [Message(
            role="assistant",
            content=f"Please approve this document: {document}"
        )]

        event = human_request_topic.publish_data(
            invoke_context=InvokeContext(),
            publisher_name="approval_system",
            publisher_type="workflow",
            data=approval_message,
            consumed_events=[]
        )

        # Wait for response (simplified)
        while True:
            approval = self.pending_approvals.get(event.event_id)
            if approval and approval["status"] == "responded":
                response_content = approval["response"].data[0].content
                return "approve" in response_content.lower()

            await asyncio.sleep(1)  # Poll for response
```

## Best Practices

### Output Topic Design

1. **Generator Management**: Always wait for generator completion or implement timeouts
2. **Memory Management**: Monitor event queue size to prevent memory issues
3. **Error Handling**: Implement proper error handling for async operations
4. **Resource Cleanup**: Use reset() to properly clean up resources

### Human Request Patterns

1. **Input Validation**: Always validate user input before appending
2. **Session Management**: Use proper session tracking for multi-user scenarios
3. **Timeout Handling**: Implement timeouts for human responses
4. **State Tracking**: Track conversation state for complex workflows

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
    event = topic.publish_data(
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

def test_human_request_topic():
    """Test human request topic functionality."""
    topic = HumanRequestTopic(name="test_human")

    # Test publishing to human
    messages = [Message(role="assistant", content="Please help")]
    event = topic.publish_data(
        invoke_context=InvokeContext(),
        publisher_name="test",
        publisher_type="test",
        data=messages,
        consumed_events=[]
    )

    assert event is not None

    # Test user input appending
    user_input = [Message(role="user", content="Sure, I'll help")]

    assert topic.can_append_user_input("user1", event)

    user_event = topic.append_user_input(
        user_input_event=event,
        data=user_input
    )

    assert user_event is not None
    assert len(topic.topic_events) == 2
```

The output topic system provides powerful capabilities for handling agent outputs, streaming responses, and human interactions in Graphite applications, supporting both real-time and batch processing scenarios with comprehensive error handling and monitoring capabilities.
