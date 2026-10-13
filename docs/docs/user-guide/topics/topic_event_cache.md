# Topic Event Cache

Topic queues store workflow events and track a separate read cursor and committed
offset for each consumer. `TopicEventQueue` defines the interface;
`InMemTopicEventQueue` provides the default in-memory implementation.

## Overview

The in-memory queue provides:

- **Event Storage**: Contiguous log of topic events with offset-based indexing
- **Consumer Tracking**: Per-consumer offset management (consumed and committed)
- **Async Operations**: Full async/await support with condition variables
- **Delivery Tracking**: Separate read and committed offsets
- **Bounded waits**: Optional read timeouts

The log is retained for the lifetime of the queue. It is unbounded and does not
provide backpressure or durable storage.

## Architecture

### Core Components

`TopicEventQueue` is the abstract queue interface. The default implementation,
`InMemTopicEventQueue()`, stores an append-only event log and maintains consumed
and committed offsets separately for each consumer. An asyncio condition protects
queue operations and wakes readers when events arrive. Consumer cursors are
initialized automatically.

### Offset Management

The cache maintains two types of offsets per consumer:

1. **Consumed Offset**: Tracks the next message to fetch (advanced immediately on fetch)
2. **Committed Offset**: Tracks messages that have been fully processed (advanced after processing)

Fetching advances the read cursor; committing records successful processing.
A failed workflow run recovers uncommitted publications from the event store
into fresh queues. Reusing a failed queue does not automatically rewind reads.

## Core Methods

### Event Storage and Consumption

All queue operations are asynchronous:

- `await cache.put(event)` appends an event, assigns its offset, and wakes readers.
- `await cache.can_consume(consumer_id)` checks for unread records.
- `await cache.unconsumed_count(consumer_id)` counts unread records.

#### async fetch(consumer_id: str, offset: Optional[int] = None, timeout: Optional[float] = None) → List[TopicEvent]
Asynchronously fetch events with blocking and timeout support.

`timeout=None` waits indefinitely, `timeout=0` returns immediately, and a positive
timeout bounds the entire wait in seconds. Cancellation propagates and leaves
the read cursor unchanged. An empty result means the wait timed out, a nonblocking
read found nothing, or no unread events fall within the requested offset range.

### Offset Commitment

`await cache.commit_to(consumer_id, offset)` commits through the given offset and
returns the highest committed offset. Committing an older offset never rewinds
the cursor. `await cache.restore_consumer(consumer_id, committed_offset)` restores
both cursors during recovery without fetching records.

## Usage Patterns

These snippets run inside async functions. Supply the application-specific event
creation and processing helpers shown in the examples.

### Basic Producer-Consumer

```python
# Producer
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue

cache = InMemTopicEventQueue()
event = PublishToTopicEvent(...)
await cache.put(event)

# Consumer
consumer_id = "consumer_1"
if await cache.can_consume(consumer_id):
    events = await cache.fetch(consumer_id, timeout=0)

    # Process events
    for event in events:
        process_event(event)

    # Commit after successful processing
    if events:
        last_offset = events[-1].offset
        await cache.commit_to(consumer_id, last_offset)
```

### Async Producer-Consumer

Pass the same queue instance to both functions so they share the event log.

```python
async def producer(cache: InMemTopicEventQueue):
    for i in range(10):
        event = create_event(i)
        await cache.put(event)
        await asyncio.sleep(0.1)

async def consumer(cache: InMemTopicEventQueue):
    consumer_id = "async_consumer"

    while True:
        # Fetch with timeout
        events = await cache.fetch(consumer_id, timeout=1.0)
        if not events:
            break  # Timeout occurred

        # Process events
        for event in events:
            await process_event_async(event)

        # Commit after processing
        if events:
            last_offset = events[-1].offset
            await cache.commit_to(consumer_id, last_offset)
```

### Multiple Consumers

```python
cache = InMemTopicEventQueue()

# Each consumer tracks its own offsets
consumers = ["consumer_1", "consumer_2", "consumer_3"]

for consumer_id in consumers:
    if await cache.can_consume(consumer_id):
        events = await cache.fetch(consumer_id, timeout=0)
        # Each consumer gets its own view of unprocessed events
```

## Best Practices

### Offset Management

1. **Immediate Consumption Tracking**: The consumed offset is advanced immediately on fetch to prevent duplicate fetches
2. **Commit After Processing**: Only commit offsets after successful event processing
3. **Batch Commits**: Commit the highest offset in a batch for efficiency

### Error Handling

```python
async def robust_consumer():
    cache = InMemTopicEventQueue()
    consumer_id = "robust_consumer"

    try:
        events = await cache.fetch(consumer_id, timeout=5.0)
        if not events:
            return  # No events or timeout

        processed_events = []
        for event in events:
            try:
                await process_event(event)
                processed_events.append(event)
            except Exception as e:
                logger.error(f"Failed to process event {event.offset}: {e}")
                # Decide whether to skip or retry
                break

        # Only commit successfully processed events
        if processed_events:
            last_offset = processed_events[-1].offset
            await cache.commit_to(consumer_id, last_offset)

    except Exception as e:
        logger.error(f"Consumer error: {e}")
```

### Performance Optimization

1. **Batch Processing**: Process multiple events in batches when possible
2. **Timeout Management**: Use appropriate timeouts to prevent indefinite blocking
3. **Memory Management**: Monitor cache size for long-running topics
4. **Queue Reset**: `await cache.reset()` clears the entire queue and all consumer
   cursors; use it only after readers have stopped

### Testing

```python
async def test_cache_behavior():
    cache = InMemTopicEventQueue()

    # Test basic put/fetch
    event = create_test_event()
    await cache.put(event)

    consumer_id = "test_consumer"
    assert await cache.can_consume(consumer_id)

    events = await cache.fetch(consumer_id)
    assert len(events) == 1
    assert events[0] == event

    # Test duplicate fetch prevention
    events2 = await cache.fetch(consumer_id, timeout=0)
    assert len(events2) == 0  # Should be empty due to consumed offset

    # Test commit and reset
    await cache.commit_to(consumer_id, 0)

    await cache.reset()
    assert await cache.fetch(consumer_id, timeout=0) == []
    assert await cache.commit_to(consumer_id, -1) == -1
```

## Integration with Topics

Topics delegate queue operations through their `event_queue`. For example:

```python
from grafi.topics.topic_impl.topic import Topic

async def read_available(topic: Topic, consumer_name: str):
    events = await topic.consume(consumer_name, timeout=0)
    # Process the events before committing their highest offset.
    for event in events:
        await process_event_async(event)
    if events:
        await topic.commit(consumer_name, events[-1].offset)
    return events
```
