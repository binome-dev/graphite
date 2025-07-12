# Configuring and Using Graphite's Event Store

Event stores are a powerful feature in the Graphite AI framework that enable persistent storage and retrieval of conversation events. This guide will walk you through setting up PostgreSQL as your event store backend and demonstrate how to leverage event storage for debugging, analytics, and conversation management.

## What is an Event Store?

An event store in Graphite captures and persists all events that occur during workflow execution, including:
- User messages and system responses
- Node executions and tool invocations
- Workflow state changes
- Error events and debugging information

This provides valuable insights into your AI application's behavior and enables features like conversation history, debugging, and analytics.

## Prerequisites

Before getting started, ensure you have:
- Docker and Docker Compose installed
- Python environment with Graphite AI framework installed
- OpenAI API key configured
- Basic understanding of PostgreSQL and event-driven architectures

## Setting Up PostgreSQL with Docker

First, let's set up a PostgreSQL database using Docker Compose. This provides a clean, isolated environment for your event store.

### Docker Compose Configuration

Create a `docker-compose.yaml` file in your project root:

```yamlversion: '3.8'

services:
  postgres:
    image: postgres:15
    container_name: postgres15
    environment:
      POSTGRES_DB: grafi_test_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - ./.pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
```



### Starting the Database

Launch your PostgreSQL container:

```bash
docker-compose up -d
```

The `-d` flag runs the container in detached mode, allowing it to run in the background.

## Configuring the Event Store

Now let's integrate the PostgreSQL event store with your Graphite workflow.

### Environment Setup

```python
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
```

### Event Store Initialization

We create a PostgreSQL event store instance with the connection URL matching your Docker container configuration, we then register the event store with Graphite's dependency injection container to obtain a reference to the registered event store for later use.

```python
from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.containers.container import container

postgres_event_store = EventStorePostgres(
    db_url="postgresql://postgres:postgres@localhost:5432/grafi_test_db",
)

container.register_event_store(postgres_event_store)
event_store = container.event_store
```



### Context and Message Setup

Generate unique identifiers for tracking this conversation and request, configure OpenAI credentials and settings and then create the invoke context with all necessary tracking IDs.

```python
import uuid
import os
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message

# Generate consistent IDs for the conversation
conversation_id = uuid.uuid4().hex
user_id = uuid.uuid4().hex
invoke_id = uuid.uuid4().hex
assistant_request_id = uuid.uuid4().hex

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is required")

model = os.getenv("OPENAI_MODEL", "gpt-4o")
system_message = os.getenv("OPENAI_SYSTEM_MESSAGE", "You are a helpful assistant.")

user_input = "What is the capital of the United Kingdom"

# Create invoke context with consistent IDs
invoke_context = InvokeContext(
    user_id=user_id,
    conversation_id=conversation_id,
    invoke_id=invoke_id,
    assistant_request_id=assistant_request_id,
)

message = Message(role="user", content=user_input)
```


## Building the Workflow

This is the same workflow as the [creating a simple workflow guide](creating-a-simple-workflow.md) .

```python
llm_node = (
    Node.builder()
    .name("OpenAINode")
    .subscribe(agent_input_topic)
    .tool(
        OpenAITool.builder()
        .name("OpenAITool")
        .api_key(api_key)
        .model(model)
        .system_message(system_message)
        .build()
    )
    .publish_to(agent_output_topic)
    .build()
)

workflow = (
    EventDrivenWorkflow.builder()
    .name("OpenAIEventDrivenWorkflow")
    .node(llm_node)
    .build()
)
```

This creates a standard Graphite workflow with an OpenAI node. The key difference is that with the event store configured, all events will be automatically persisted.

## Executing and Retrieving Events

Once you have built the workflow and invoked it we can get all the events from the previously configured `event_store` and print it out

```python
result = workflow.invoke(invoke_context, [message])

for output_message in result:
    print("Output message:", output_message.content)

# Retrieve stored events
events = event_store.get_conversation_events(conversation_id)

print(f"Events for conversation {conversation_id}:")
print(f"Events: {events}")
```



## Complete Example

Here's the complete `event_store.py` file that demonstrates the full integration:

```python
import os
import uuid

from grafi.common.containers.container import container
from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

postgres_event_store = EventStorePostgres(
    db_url="postgresql://postgres:postgres@localhost:5432/grafi_test_db",
)

container.register_event_store(postgres_event_store)
event_store = container.event_store

# Generate consistent IDs for the conversation
conversation_id = uuid.uuid4().hex
user_id = uuid.uuid4().hex
invoke_id = uuid.uuid4().hex
assistant_request_id = uuid.uuid4().hex

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is required")

model = os.getenv("OPENAI_MODEL", "gpt-4o")
system_message = os.getenv("OPENAI_SYSTEM_MESSAGE", "You are a helpful assistant.")

user_input = "What is the capital of the United Kingdom"

# Create invoke context with consistent IDs
invoke_context = InvokeContext(
    user_id=user_id,
    conversation_id=conversation_id,
    invoke_id=invoke_id,
    assistant_request_id=assistant_request_id,
)

message = Message(role="user", content=user_input)

llm_node = (
    Node.builder()
    .name("OpenAINode")
    .subscribe(agent_input_topic)
    .tool(
        OpenAITool.builder()
        .name("OpenAITool")
        .api_key(api_key)
        .model(model)
        .system_message(system_message)
        .build()
    )
    .publish_to(agent_output_topic)
    .build()
)

workflow = (
    EventDrivenWorkflow.builder()
    .name("OpenAIEventDrivenWorkflow")
    .node(llm_node)
    .build()
)

result = workflow.invoke(invoke_context, [message])

for output_message in result:
    print("Output message:", output_message.content)

events = event_store.get_conversation_events(conversation_id)

print(f"Events for conversation {conversation_id}:")
print(f"Events: {events}")
```

## Running the Example

1. **Start the PostgreSQL container**:
   ```bash
   docker-compose up -d
   ```

2. **Set up environment variables**:
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   export OPENAI_MODEL="gpt-4o"  # Optional
   export OPENAI_SYSTEM_MESSAGE="You are a helpful assistant."  # Optional
   ```

3. **Execute the script**:
   ```bash
   python event_store.py
   ```

4. **Expected output**:
   ```
   Output message: The capital of the United Kingdom is London.
   Events for conversation 1a2b3c4d5e6f7g8h9i0j:
   Events: [Event objects with full conversation history]
   ```

You can view the events in your postgres database as well now

![Event Store Database](../img//event_store.png)

## Key Benefits

### Debugging and Monitoring
- **Event Tracing**: Track the complete flow of events through your workflow
- **Error Analysis**: Identify where failures occur and why
- **Performance Monitoring**: Analyze timing and resource usage

### Conversation Management
- **History Retrieval**: Access complete conversation history for context
- **Session Continuity**: Maintain state across multiple interactions
- **User Analytics**: Understand user behavior patterns

### Compliance and Auditing
- **Audit Trail**: Complete record of all interactions
- **Data Governance**: Centralized event storage for compliance
- **Troubleshooting**: Detailed logs for issue resolution


## Best Practices

1. **Use Meaningful IDs**: Generate consistent, traceable identifiers for conversations and users
2. **Environment Configuration**: Keep database credentials in environment variables
3. **Connection Pooling**: Use connection pooling for production deployments
4. **Event Cleanup**: Implement retention policies for old events
5. **Monitoring**: Set up alerts for event store health and performance

## Troubleshooting

### Common Issues

**Database Connection Errors**:
- Ensure PostgreSQL container is running: `docker-compose ps`
- Check connection string matches container configuration
- Verify port 5432 is available

**Event Store Registration**:
- Ensure event store is registered before workflow execution
- Check container dependencies are properly configured

**Performance Issues**:
- Monitor database disk usage in `.pgdata` directory
- Consider indexing strategies for large event volumes
- Implement event archiving for long-term storage

## Next Steps

With event storage configured, you can:
- Build conversation history features
- Implement advanced analytics and reporting
- Create debugging and monitoring dashboards
- Develop event-driven triggers and automation

The event store provides the foundation for building sophisticated, production-ready AI applications with full observability and auditability.
