# Event Store

The Graphite event store system provides persistent storage and retrieval capabilities for events within the event-driven architecture. It supports multiple storage backends including in-memory and PostgreSQL implementations, enabling flexible deployment options from development to production environments.

## Overview

The event store system is built around a common interface that supports:

- **Event Recording**: Store single events or batches of events
- **Event Retrieval**: Query events by ID, assistant request, conversation, or topic
- **Multiple Backends**: In-memory for development, PostgreSQL for production
- **Event Reconstruction**: Decode stored events back to typed objects, failing loudly on any it cannot read

## Base EventStore Interface

All event store implementations inherit from the base `EventStore` class, which defines the standard interface for event persistence. Its methods are async.

### Core Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `record_event` | `(event: Event) -> None` | Record a single event to the store |
| `record_events` | `(events: Sequence[Event]) -> None` | Record a batch atomically: all of its events, or none |
| `clear_events` | `() -> None` | Clear all events from the store |
| `get_events` | `() -> List[Event]` | Retrieve all events from the store |
| `get_event` | `(event_id: str) -> Optional[Event]` | Get a specific event by ID |
| `get_agent_events` | `(assistant_request_id: str) -> List[Event]` | Get events for an assistant request |
| `get_conversation_events` | `(conversation_id: str) -> List[Event]` | Get events for a conversation |
| `get_topic_events` | `(name: str, offsets: List[int]) -> List[Event]` | Get the publications to a topic at the given offsets |
| `aclose` | `() -> None` | Release what the store holds, such as a connection pool |

A workflow stores the consumptions and publications of the steps that finish
together with one `record_events()` call, and resumes a request from those
records. A custom store must therefore write each batch atomically (for example
in one transaction): a batch only partly written leaves a step half stored.
Recovery may not detect it, and the resumed request then skips that step (its
output lost) or runs it again (its output delivered twice); if the write left a
gap in a topic's positions, every resume fails with `WorkflowError`. Both
built-in stores also skip an event whose `event_id` is already stored.

### Event Reconstruction

A store does not know the event classes: it encodes and decodes events through an `EventCodec` (see [Serialization and Deserialization](events.md#serialization-and-deserialization)).

| Attribute or Method | Signature | Description |
|---------------------|-----------|-------------|
| `codec` | `EventCodec` | The store's codec: `default_event_codec` unless another is given. A store writes `codec.encode(event)` and reads with `codec.decode(data)`, which raises `EventSerializationError` for an event it cannot read |

`default_event_codec` is shared by every store in the process, so `default_event_codec.register(...)` affects them all. For a registry of its own, a store subclass assigns `self.codec = EventCodec({...})` in its constructor.

## In-Memory Event Store

The `EventStoreInMemory` provides a simple, memory-based storage solution ideal for development, testing, and lightweight applications.

### Features

- **Zero Dependencies**: No external database required
- **Fast Access**: Direct memory access for all operations
- **Simplicity**: Easy setup and configuration
- **Temporary Storage**: Data is lost when application restarts
- **Strict Mode**: Optionally keeps events as a durable store does, for tests

### Usage

```python
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.events.component_events import ToolInvokeEvent
from grafi.common.models.message import Message

# Initialize the store
event_store = EventStoreInMemory()

# Record an event
event = ToolInvokeEvent(
    invoke_context=context,
    name="OpenAITool",
    type="OpenAITool",
    input_data=[Message(role="user", content="Hello")],
)
await event_store.record_event(event)

# Retrieve events
all_events = await event_store.get_events()
specific_event = await event_store.get_event(event.event_id)
request_events = await event_store.get_agent_events("req_123")
```

### Strict Mode

By default the store keeps the event objects it is given. With `strict=True`, it encodes each event to JSON text and decodes it back before storing it, as a durable store would:

```python
event_store = EventStoreInMemory(strict=True)
```

An event that a durable store could not record, or not read back as it was, then fails here too, with `EventSerializationError`, and nothing of its batch is stored. The store keeps the decoded copy, equal to the event recorded but not the same object. grafi's own tests run with a strict store (see `tests/conftest.py`); use one in yours.

### Implementation Details

```python
class EventStoreInMemory(EventStore):
    def __init__(self, *, strict: bool = False) -> None:
        self.events = []
        self._event_ids = set()
        self.strict = strict

    async def record_event(self, event: Event) -> None:
        await self.record_events([event])

    async def record_events(self, events: Sequence[Event]) -> None:
        if self.strict:  # All encoded first, so a batch is all or nothing.
            events = [self._stored(event) for event in events]
        for event in events:
            if event.event_id in self._event_ids:
                continue
            self._event_ids.add(event.event_id)
            self.events.append(event)

    def _stored(self, event: Event) -> Event:
        """``event`` as a durable store gives it back."""
        return self.codec.decode(json.loads(json.dumps(self.codec.encode(event))))
```

## PostgreSQL Event Store

The `EventStorePostgres` provides a production-ready, persistent storage solution using PostgreSQL as the backend database.

### PostgreSQL Features

- **Persistent Storage**: Data survives application restarts
- **ACID Compliance**: Each `record_events()` batch is written in one transaction
- **Scalability**: Handles large volumes of events
- **Advanced Querying**: SQL-based filtering and aggregation
- **JSON Support**: Native JSONB storage for event data

### Database Schema

The PostgreSQL implementation uses a single `events` table:

| Column | Type | Description |
|--------|------|-------------|
| `id` | `Integer` | Auto-increment primary key |
| `event_id` | `String` | Unique event identifier (indexed) |
| `conversation_id` | `String` | Conversation identifier (indexed) |
| `assistant_request_id` | `String` | Assistant request identifier (indexed) |
| `event_type` | `String` | Type of event, such as `"PublishToTopic"` (indexed) |
| `event_version` | `String` | Version of `event_data`: `"2"`, or `"1.0"` in rows written before |
| `event_data` | `JSONB` | The event's JSON form |
| `timestamp` | `DateTime` | Event creation time, naive, in UTC |

### Setup and Configuration

Install the driver with `pip install 'grafi[postgres]'`.

```python
from grafi.common.event_stores.event_store_postgres import EventStorePostgres

# Initialize with database URL; this does no I/O
db_url = "postgresql://user:password@localhost:5432/graphite_events"
event_store = EventStorePostgres(db_url)

# Optional: create the table now, to fail fast if the database is unreachable
await event_store.initialize()

# At shutdown, close the connection pool
await event_store.aclose()
```

The first use creates the `events` table if `initialize()` has not. `pool_size`, `max_overflow` and `pool_timeout` configure the connection pool.

### Usage Examples

#### Recording Events

```python
# Record single event
await event_store.record_event(event)

# Record multiple events (batch operation)
events = [event1, event2, event3]
await event_store.record_events(events)
```

#### Querying Events

```python
# Get specific event
event = await event_store.get_event("event_123")

# Get all events for an assistant request
request_events = await event_store.get_agent_events("req_456")

# Get all events for a conversation
conversation_events = await event_store.get_conversation_events("conv_789")
```

The lists are in timestamp order, then in the order the rows were written.

### Error Handling

The PostgreSQL store raises two errors, each with its cause chained:

- `EventSerializationError`: an event cannot be encoded (`record_events` encodes the whole batch before writing, so nothing is written), or a row read cannot be decoded.
- `EventPersistenceError`: the database fails, to connect, create the table, write (the transaction is rolled back) or query.

```python
from grafi.common.exceptions import EventPersistenceError
from grafi.common.exceptions import EventSerializationError

try:
    await event_store.record_events(events)
except EventSerializationError:
    ...  # An event cannot be saved as JSON; nothing was written.
except EventPersistenceError:
    ...  # The database failed; nothing was written.
```

## Event Serialization and Deserialization

The event store system handles conversion between event objects and storage formats through its codec.

### Serialization Process

1. **Encoding**: Each event is encoded with `self.codec.encode(event)`, its JSON form
2. **Column Extraction**: Key fields are copied to their columns for indexing
3. **JSON Storage**: The JSON form is stored in `event_data`

`record_event` writes through `record_events`. A row, as the values written:

```python
{
    "event_id": "evt_123",
    "conversation_id": "conv_1",
    "assistant_request_id": "req_456",
    "event_type": "ToolInvoke",
    "event_version": "2",
    "event_data": {
        "event_id": "evt_123",
        "event_version": 2,
        "invoke_context": {...},
        "event_type": "ToolInvoke",
        "timestamp": "2025-07-01T10:30:00Z",
        "id": "tool_1",
        "name": "OpenAITool",
        "type": "OpenAITool",
        "input_data": [...],
    },
    "timestamp": datetime(2025, 7, 1, 10, 30),  # Naive, in UTC.
}
```

An event's timestamp is converted to UTC and stored without its time zone; a naive timestamp is taken to be UTC already.

### Deserialization Process

1. **Type Resolution**: The `event_type` in `event_data` chooses the class registered with the codec
2. **Upgrade**: An event of version `"1.0"` is upgraded to version 2
3. **Validation**: The class validates the event; any failure raises `EventSerializationError`

Rows written before version 2 hold `event_data` in the version 1 form, with the topic's or component's fields under `event_context`. They are read as they are, never rewritten: decoding upgrades them, and `get_topic_events` finds a topic event's `name` and `offset` in either form.

## Supported Event Types

The event store supports all event types defined in the Graphite events system:

### Component Events

- **Node Events**: `NODE_INVOKE`, `NODE_RESPOND`, `NODE_FAILED`
- **Tool Events**: `TOOL_INVOKE`, `TOOL_RESPOND`, `TOOL_FAILED`
- **Workflow Events**: `WORKFLOW_INVOKE`, `WORKFLOW_RESPOND`, `WORKFLOW_FAILED`
- **Assistant Events**: `ASSISTANT_INVOKE`, `ASSISTANT_RESPOND`, `ASSISTANT_FAILED`

### Topic Events

- **Basic Events**: `TOPIC_EVENT`
- **Communication Events**: `PUBLISH_TO_TOPIC`, `CONSUME_FROM_TOPIC`

Any other type is read once its class is registered with the store's codec (see [Custom Event Types](events.md#custom-event-types)); until then, reading it raises `EventSerializationError`.

## Integration Patterns

### Event-Driven Architecture

```python
class MyWorkflow:
    def __init__(self, event_store: EventStore):
        self.event_store = event_store

    async def process_request(self, request):
        # Record start event
        start_event = WorkflowInvokeEvent(...)
        await self.event_store.record_event(start_event)

        try:
            # Process request
            result = self.do_work(request)

            # Record success event
            success_event = WorkflowRespondEvent(...)
            await self.event_store.record_event(success_event)

            return result
        except Exception as e:
            # Record failure event
            failure_event = WorkflowFailedEvent(...)
            await self.event_store.record_event(failure_event)
            raise
```

### Event Sourcing

```python
async def rebuild_conversation_state(conversation_id: str, event_store: EventStore):
    """Rebuild conversation state from events."""
    events = await event_store.get_conversation_events(conversation_id)

    state = ConversationState()
    for event in sorted(events, key=lambda e: e.timestamp):
        state.apply_event(event)

    return state
```

### Observability and Monitoring

```python
async def monitor_assistant_performance(assistant_request_id: str, event_store: EventStore):
    """Monitor assistant performance using events."""
    events = await event_store.get_agent_events(assistant_request_id)

    invoke_events = [e for e in events if isinstance(e, AssistantInvokeEvent)]
    respond_events = [e for e in events if isinstance(e, AssistantRespondEvent)]
    failed_events = [e for e in events if isinstance(e, AssistantFailedEvent)]

    return {
        "total_requests": len(invoke_events),
        "successful_responses": len(respond_events),
        "failures": len(failed_events),
        "success_rate": len(respond_events) / len(invoke_events) if invoke_events else 0
    }
```

## Configuration and Deployment

### Development Configuration

```python
# Use in-memory store for development
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory

event_store = EventStoreInMemory()
```

### Production Configuration

```python
# Use PostgreSQL for production
from grafi.common.event_stores.event_store_postgres import EventStorePostgres
import os

db_url = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/events")
event_store = EventStorePostgres(db_url)
```

### Environment-Based Selection

```python
def create_event_store() -> EventStore:
    """Create event store based on environment."""
    env = os.getenv("ENVIRONMENT", "development")

    if env == "production":
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL required for production")
        return EventStorePostgres(db_url)
    else:
        return EventStoreInMemory()
```

## Best Practices

### Event Store Selection

1. **Development**: Use `EventStoreInMemory` for rapid development and testing
2. **Testing**: Use `EventStoreInMemory(strict=True)` for unit tests and integration tests
3. **Production**: Use `EventStorePostgres` for persistent, scalable storage
4. **CI/CD**: Use `EventStoreInMemory(strict=True)` for continuous integration pipelines

### Performance Optimization

1. **Batch Operations**: Use `record_events()` for multiple events
2. **Indexing**: Leverage database indexes for common query patterns
3. **Connection Pooling**: Configure `pool_size`, `max_overflow` and `pool_timeout`
4. **Query Optimization**: Use specific queries rather than retrieving all events

### Error Handling Best Practices

1. **Transaction Management**: Use database transactions for consistency
2. **Retry Logic**: Retry an `EventPersistenceError` from a transient failure; an `EventSerializationError` will fail again
3. **Logging**: Log all event store operations for debugging
4. **Fail Loudly**: Do not skip an event a store cannot read: a workflow recovers from the store's record

### Data Management

1. **Archival**: Implement event archival for old events
2. **Partitioning**: Use database partitioning for large event volumes
3. **Backup**: Regular backup of event data
4. **Monitoring**: Monitor event store performance and capacity

## Security Considerations

### Data Protection

- **Encryption**: Encrypt sensitive event data
- **Access Control**: Implement proper database access controls
- **Audit Logging**: Log access to event data
- **Data Retention**: Implement appropriate data retention policies

### Privacy Compliance

- **Personal Data**: Handle personal data in events according to privacy regulations
- **Data Anonymization**: Consider anonymizing events for analytics
- **Right to be Forgotten**: Implement event deletion capabilities

## Troubleshooting

### Common Issues

1. **Connection Failures**: Check database connectivity and credentials
2. **Schema Errors**: Ensure database schema is properly created
3. **Serialization Errors**: An `EventSerializationError` names the event and its cause: a value JSON cannot hold; an event of a class its type does not decode as, such as an unregistered one; or a stored event from a newer grafi
4. **Performance Issues**: Monitor query performance and optimize indexes

### Debugging

```python
import logging

logger = logging.getLogger(__name__)

# Enable SQLAlchemy logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

# Monitor event store operations
logger.info(f"Recording event: {event.event_type}")
await event_store.record_event(event)
logger.info(f"Event recorded successfully: {event.event_id}")
```

The event store system provides a robust foundation for event persistence in Graphite's event-driven architecture, supporting both development flexibility and production scalability requirements.
