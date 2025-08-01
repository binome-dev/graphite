# Topic Event Cache

The TopicEventCache is a sophisticated in-memory caching system that provides Kafka-like functionality for managing topic events, consumer offsets, and reliable message processing in Graphite workflows. It acts as a miniature message broker within each topic, supporting concurrent producers and consumers with proper offset management.

## Overview

The TopicEventCache implements:

- **Event Storage**: Contiguous log of topic events with offset-based indexing
- **Consumer Tracking**: Per-consumer offset management (consumed and committed)
- **Async Operations**: Full async/await support with condition variables
- **Reliable Processing**: Separate consumed/committed offsets prevent duplicate processing
- **Backpressure**: Built-in flow control and timeout handling

## Architecture

### Core Components

```python
class TopicEventCache:
    def __init__(self, name: str = ""):
        self.name: str = name
        self._records: List[TopicEvent] = []  # contiguous log

        # Per-consumer cursors
        self._consumed: Dict[str, int] = defaultdict(int)      # next offset to read
        self._committed: Dict[str, int] = defaultdict(lambda: -1)  # last committed offset

        # For asynchronous operations
        self._cond: asyncio.Condition = asyncio.Condition()
```

### Offset Management

The cache maintains two types of offsets per consumer:

1. **Consumed Offset**: Tracks the next message to fetch (advanced immediately on fetch)
2. **Committed Offset**: Tracks messages that have been fully processed (advanced after processing)

This dual-offset system prevents duplicate message processing in concurrent environments.

## Core Methods

### Event Storage

#### put(event: TopicEvent) → TopicEvent
Synchronously append an event to the log.

```python
def put(self, event: TopicEvent) -> TopicEvent:
    self._records.append(event)
    return event
```

#### async a_put(event: TopicEvent) → TopicEvent
Asynchronously append an event and notify waiting consumers.

```python
async def a_put(self, event: TopicEvent) -> TopicEvent:
    async with self._cond:
        self._records.append(event)
        self._cond.notify_all()  # wake waiting consumers
        return event
```

### Event Consumption

#### can_consume(consumer_id: str) → bool
Check if a consumer has unread messages.

```python
def can_consume(self, consumer_id: str) -> bool:
    self._ensure_consumer(consumer_id)
    # Can consume if there are records beyond the consumed offset
    return self._consumed[consumer_id] < len(self._records)
```

#### fetch(consumer_id: str, offset: Optional[int] = None) → List[TopicEvent]
Synchronously fetch unread events and advance consumed offset.

```python
def fetch(self, consumer_id: str, offset: Optional[int] = None) -> List[TopicEvent]:
    """
    Fetch records newer than the consumer's consumed offset.
    Immediately advances consumed offset to prevent duplicate fetches.
    """
    self._ensure_consumer(consumer_id)

    if self.can_consume(consumer_id):
        start = self._consumed[consumer_id]
        if offset is not None:
            end = min(len(self._records), offset + 1)
            batch = self._records[start:end]
        else:
            batch = self._records[start:]

        # Advance consumed offset immediately to prevent duplicate fetches
        self._consumed[consumer_id] += len(batch)
        return batch

    return []
```

#### async a_fetch(consumer_id: str, offset: Optional[int] = None, timeout: Optional[float] = None) → List[TopicEvent]
Asynchronously fetch events with blocking and timeout support.

```python
async def a_fetch(
    self,
    consumer_id: str,
    offset: Optional[int] = None,
    timeout: Optional[float] = None,
) -> List[TopicEvent]:
    """
    Await fresh records newer than the consumer's consumed offset.
    Immediately advances consumed offset to prevent duplicate fetches.
    """
    self._ensure_consumer(consumer_id)

    async with self._cond:
        # Wait for data to become available
        while not self.can_consume(consumer_id):
            if timeout is None:
                await self._cond.wait()
            else:
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout)
                except asyncio.TimeoutError:
                    return []

        start = self._consumed[consumer_id]
        if offset is not None:
            end = min(len(self._records), offset + 1)
            batch = self._records[start:end]
        else:
            batch = self._records[start:]

        # Advance consumed offset immediately
        self._consumed[consumer_id] += len(batch)
        return batch
```

### Offset Commitment

#### commit_to(consumer_id: str, offset: int) → int
Synchronously commit processed messages up to the specified offset.

```python
def commit_to(self, consumer_id: str, offset: int) -> int:
    """
    Marks everything up to `offset` as processed/durable
    for this consumer.
    """
    self._ensure_consumer(consumer_id)
    # Only commit if offset is greater than current committed
    if offset > self._committed[consumer_id]:
        self._committed[consumer_id] = offset
    return self._committed[consumer_id]
```

#### async a_commit_to(consumer_id: str, offset: int) → None
Asynchronously commit processed messages.

```python
async def a_commit_to(self, consumer_id: str, offset: int) -> None:
    """Commit all offsets up to and including the specified offset."""
    async with self._cond:
        self._ensure_consumer(consumer_id)
        if offset > self._committed[consumer_id]:
            self._committed[consumer_id] = offset
```

## Usage Patterns

### Basic Producer-Consumer

```python
# Producer
cache = TopicEventCache("my_topic")
event = PublishToTopicEvent(...)
cache.put(event)

# Consumer
consumer_id = "consumer_1"
if cache.can_consume(consumer_id):
    events = cache.fetch(consumer_id)

    # Process events
    for event in events:
        process_event(event)

    # Commit after successful processing
    if events:
        last_offset = events[-1].offset
        cache.commit_to(consumer_id, last_offset)
```

### Async Producer-Consumer

```python
async def producer():
    cache = TopicEventCache("async_topic")
    for i in range(10):
        event = create_event(i)
        await cache.a_put(event)
        await asyncio.sleep(0.1)

async def consumer():
    cache = TopicEventCache("async_topic")
    consumer_id = "async_consumer"

    while True:
        # Fetch with timeout
        events = await cache.a_fetch(consumer_id, timeout=1.0)
        if not events:
            break  # Timeout occurred

        # Process events
        for event in events:
            await process_event_async(event)

        # Commit after processing
        if events:
            last_offset = events[-1].offset
            await cache.a_commit_to(consumer_id, last_offset)
```

### Multiple Consumers

```python
cache = TopicEventCache("shared_topic")

# Each consumer tracks its own offsets
consumers = ["consumer_1", "consumer_2", "consumer_3"]

for consumer_id in consumers:
    if cache.can_consume(consumer_id):
        events = cache.fetch(consumer_id)
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
    cache = TopicEventCache("robust_topic")
    consumer_id = "robust_consumer"

    try:
        events = await cache.a_fetch(consumer_id, timeout=5.0)
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
            await cache.a_commit_to(consumer_id, last_offset)

    except asyncio.TimeoutError:
        logger.info("No events available within timeout")
    except Exception as e:
        logger.error(f"Consumer error: {e}")
```

### Performance Optimization

1. **Batch Processing**: Process multiple events in batches when possible
2. **Timeout Management**: Use appropriate timeouts to prevent indefinite blocking
3. **Memory Management**: Monitor cache size for long-running topics
4. **Consumer Cleanup**: Reset consumers that are no longer needed

### Testing

```python
async def test_cache_behavior():
    cache = TopicEventCache("test_topic")

    # Test basic put/fetch
    event = create_test_event()
    await cache.a_put(event)

    consumer_id = "test_consumer"
    assert cache.can_consume(consumer_id)

    events = await cache.a_fetch(consumer_id)
    assert len(events) == 1
    assert events[0] == event

    # Test duplicate fetch prevention
    events2 = await cache.a_fetch(consumer_id)
    assert len(events2) == 0  # Should be empty due to consumed offset

    # Test commit and reset
    await cache.a_commit_to(consumer_id, 0)

    cache.reset()
    assert len(cache._records) == 0
    assert cache._consumed[consumer_id] == 0
    assert cache._committed[consumer_id] == -1
```

## Integration with Topics

The TopicEventCache is used internally by all TopicBase implementations:

```python
class TopicBase(BaseModel):
    event_cache: TopicEventCache = Field(default_factory=TopicEventCache)

    def can_consume(self, consumer_name: str) -> bool:
        return self.event_cache.can_consume(consumer_name)

    async def a_consume(self, consumer_name: str, timeout: Optional[float] = None) -> List[TopicEvent]:
        return await self.event_cache.a_fetch(consumer_name, timeout=timeout)

    async def a_commit(self, consumer_name: str, offset: int) -> None:
        await self.event_cache.a_commit_to(consumer_name, offset)
```

This provides a consistent, reliable messaging substrate for all topic types in Graphite workflows, ensuring proper event ordering, delivery guarantees, and offset management across the entire system.