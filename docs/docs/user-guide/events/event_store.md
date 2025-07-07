# Event Store

The Graphite event store system provides persistent storage and retrieval capabilities for events within the event-driven architecture. It supports multiple storage backends including in-memory and PostgreSQL implementations, enabling flexible deployment options from development to production environments.

## Overview

The event store system is built around a common interface that supports:

- **Event Recording**: Store single events or batches of events
- **Event Retrieval**: Query events by ID, assistant request, or conversation
- **Multiple Backends**: In-memory for development, PostgreSQL for production
- **Event Reconstruction**: Deserialize stored events back to typed objects

## Base EventStore Interface

All event store implementations inherit from the base `EventStore` class, which defines the standard interface for event persistence.

### Core Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `record_event` | `(event: Event) -> None` | Record a single event to the store |
| `record_events` | `(events: List[Event]) -> None` | Record multiple events in batch |
| `clear_events` | `() -> None` | Clear all events from the store |
| `get_events` | `() -> List[Event]` | Retrieve all events from the store |
| `get_event` | `(event_id: str) -> Optional[Event]` | Get a specific event by ID |
| `get_agent_events` | `(assistant_request_id: str) -> List[Event]` | Get events for an assistant request |
| `get_conversation_events` | `(conversation_id: str) -> List[Event]` | Get events for a conversation |

### Event Reconstruction

The base class provides helper methods for converting stored data back to event objects:

| Method | Signature | Description |
|--------|-----------|-------------|
| `_create_event_from_dict` | `(event_dict: Dict[str, Any]) -> Optional[Event]` | Create event object from dictionary |
| `_get_event_class` | `(event_type: str) -> Optional[Type[Event]]` | Get event class for event type |

## In-Memory Event Store

The `EventStoreInMemory` provides a simple, memory-based storage solution ideal for development, testing, and lightweight applications.

### Features

- **Zero Dependencies**: No external database required
- **Fast Access**: Direct memory access for all operations
- **Simplicity**: Easy setup and configuration
- **Temporary Storage**: Data is lost when application restarts

### Usage

```python
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.events.tool_events.tool_invoke_event import ToolInvokeEvent

# Initialize the store
event_store = EventStoreInMemory()

# Record an event
event = ToolInvokeEvent(
    invoke_context=context,
    tool_name="OpenAI Tool",
    tool_type="LLMTool",
    input_data=[Message(role="user", content="Hello")]
)
event_store.record_event(event)

# Retrieve events
all_events = event_store.get_events()
specific_event = event_store.get_event(event.event_id)
request_events = event_store.get_agent_events("req_123")
```

### Implementation Details

```python
class EventStoreInMemory(EventStore):
    def __init__(self) -> None:
        self.events = []

    def record_event(self, event: Event) -> None:
        self.events.append(event)

    def get_events(self) -> List[Event]:
        return self.events.copy()

    def get_event(self, event_id: str) -> Optional[Event]:
        for event in self.events:
            if event.event_id == event_id:
                return event
        return None
```

## PostgreSQL Event Store

The `EventStorePostgres` provides a production-ready, persistent storage solution using PostgreSQL as the backend database.

### PostgreSQL Features

- **Persistent Storage**: Data survives application restarts
- **ACID Compliance**: Full transaction support
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
| `event_type` | `String` | Type of event |
| `event_context` | `JSONB` | Event context data |
| `data` | `JSON` | Event-specific data |
| `timestamp` | `DateTime` | Event creation timestamp |

### Setup and Configuration

```python
from grafi.common.event_stores.event_store_postgres import EventStorePostgres

# Initialize with database URL
db_url = "postgresql://user:password@localhost:5432/graphite_events"
event_store = EventStorePostgres(db_url)

# The database schema is automatically created
```

### Usage Examples

#### Recording Events

```python
# Record single event
event_store.record_event(event)

# Record multiple events (batch operation)
events = [event1, event2, event3]
event_store.record_events(events)
```

#### Querying Events

```python
# Get specific event
event = event_store.get_event("event_123")

# Get all events for an assistant request
request_events = event_store.get_agent_events("req_456")

# Get all events for a conversation
conversation_events = event_store.get_conversation_events("conv_789")
```

### Error Handling

The PostgreSQL store includes comprehensive error handling:

```python
def record_event(self, event: Event) -> None:
    session = self.Session()
    try:
        # Convert and store event
        model = EventModel(...)
        session.add(model)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to record event: {e}")
        raise e
    finally:
        session.close()
```

## Event Serialization and Deserialization

The event store system handles automatic conversion between event objects and storage formats.

### Serialization Process

1. **Event to Dictionary**: Events are converted to dictionaries using `event.to_dict()`
2. **Context Extraction**: Key fields are extracted for indexing
3. **JSON Storage**: Event data is stored as JSON/JSONB

```python
event_dict = event.to_dict()
# Produces:
{
    "event_id": "evt_123",
    "assistant_request_id": "req_456",
    "event_type": "ToolInvoke",
    "event_context": {...},
    "data": {...},
    "timestamp": "2025-07-01T10:30:00Z"
}
```

### Deserialization Process

1. **Type Resolution**: Event type determines the target class
2. **Class Loading**: Appropriate event class is loaded
3. **Object Creation**: Event object is reconstructed using `from_dict()`

```python
def _get_event_class(self, event_type: str) -> Optional[Type[Event]]:
    event_classes = {
        EventType.TOOL_INVOKE.value: ToolInvokeEvent,
        EventType.TOOL_RESPOND.value: ToolRespondEvent,
        EventType.ASSISTANT_INVOKE.value: AssistantInvokeEvent,
        # ... all supported event types
    }
    return event_classes.get(event_type)
```

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
- **Output Events**: `OUTPUT_TOPIC`

## Integration Patterns

### Event-Driven Architecture

```python
class MyWorkflow:
    def __init__(self, event_store: EventStore):
        self.event_store = event_store

    def process_request(self, request):
        # Record start event
        start_event = WorkflowInvokeEvent(...)
        self.event_store.record_event(start_event)

        try:
            # Process request
            result = self.do_work(request)

            # Record success event
            success_event = WorkflowRespondEvent(...)
            self.event_store.record_event(success_event)

            return result
        except Exception as e:
            # Record failure event
            failure_event = WorkflowFailedEvent(...)
            self.event_store.record_event(failure_event)
            raise
```

### Event Sourcing

```python
def rebuild_conversation_state(conversation_id: str, event_store: EventStore):
    """Rebuild conversation state from events."""
    events = event_store.get_conversation_events(conversation_id)

    state = ConversationState()
    for event in sorted(events, key=lambda e: e.timestamp):
        state.apply_event(event)

    return state
```

### Observability and Monitoring

```python
def monitor_assistant_performance(assistant_request_id: str, event_store: EventStore):
    """Monitor assistant performance using events."""
    events = event_store.get_agent_events(assistant_request_id)

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
2. **Testing**: Use `EventStoreInMemory` for unit tests and integration tests
3. **Production**: Use `EventStorePostgres` for persistent, scalable storage
4. **CI/CD**: Use `EventStoreInMemory` for continuous integration pipelines

### Performance Optimization

1. **Batch Operations**: Use `record_events()` for multiple events
2. **Indexing**: Leverage database indexes for common query patterns
3. **Connection Pooling**: Configure SQLAlchemy connection pooling
4. **Query Optimization**: Use specific queries rather than retrieving all events

### Error Handling Best Practices

1. **Transaction Management**: Use database transactions for consistency
2. **Retry Logic**: Implement retry mechanisms for transient failures
3. **Logging**: Log all event store operations for debugging
4. **Graceful Degradation**: Handle event store failures gracefully

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
3. **Serialization Errors**: Verify event objects implement required methods
4. **Performance Issues**: Monitor query performance and optimize indexes

### Debugging

```python
import logging

# Enable SQLAlchemy logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

# Monitor event store operations
logger.info(f"Recording event: {event.event_type}")
event_store.record_event(event)
logger.info(f"Event recorded successfully: {event.event_id}")
```

The event store system provides a robust foundation for event persistence in Graphite's event-driven architecture, supporting both development flexibility and production scalability requirements.
