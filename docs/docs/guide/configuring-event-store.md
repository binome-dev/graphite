# Configuring and Using Graphite's Event Store

Event stores are a powerful feature in the Graphite AI framework that enable persistent storage and retrieval of conversation events. This guide will walk you through setting up PostgreSQL as your event store backend and demonstrate how to leverage event storage for debugging, analytics, and conversation management.

## What is an Event Store?

An event store in Graphite captures and persists  pub/sub events that occur during workflow execution, including:
- User messages and system responses
- Node executions and tool invocations
- Pub/Sub events from Topics and Workflows
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


create `.pgdata` directory that will act as the volume for your database

<div class="bash"><pre>
<code><span style="color:#FF4689">mkdir</span> .pgdata</code></pre>
</div>

Create a `docker-compose.yaml` file in your project root:

```yaml
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

<div class="bash"><pre>
<code><span style="color:#FF4689">docker compose</span> up -d</code></pre></div>


The `-d` flag runs the container in detached mode, allowing it to run in the background.

## Configuring the Event Store

Now let's integrate the PostgreSQL event store with your Graphite workflow. You need to have followed the [quickstart](../getting-started/quickstart.md)  to create a `uv` project with grafite installed.

You will have to add `sqlalchemy` and `psycopg2` dependencies to it since we will be using postgres as the event store.

<div class="bash"><pre>
<code><span style="color:#FF4689">uv</span> add sqlalchemy psycopg2</code></pre></div>


### Context and Message Setup

Generate unique identifiers for tracking this conversation and request, configure OpenAI credentials and settings and then create the invoke context with all necessary tracking IDs.



```python
import os
import uuid

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is required")

model = os.getenv("OPENAI_MODEL", "gpt-4o")
system_message = os.getenv("OPENAI_SYSTEM_MESSAGE", "You are a helpful assistant.")

invoke_context = InvokeContext(
    user_id=uuid.uuid4().hex,
    conversation_id=uuid.uuid4().hex,
    invoke_id=uuid.uuid4().hex,
    assistant_request_id=uuid.uuid4().hex
)
user_input = "What is the capital of the United Kingdom"

message = Message(
    role="user", 
    content=user_input
)

```

Nothing fancy here, just initialization of context and setting up of variables.


### Event Store Initialization

We create a PostgreSQL event store instance with the connection URL matching your Docker container configuration, we then register the event store with Graphite's dependency injection container to obtain a reference to the registered event store for later use.

```python
from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.containers.container import container

postgres_event_store = EventStorePostgres(
    # must match what is in docker-compose.yaml
    db_url="postgresql://postgres:postgres@localhost:5432/grafi_test_db", 
)

container.register_event_store(postgres_event_store)
event_store = container.event_store
```

## Running the agent and Retrieving Events

Graphite has a built in react agent that can be used out of the box for your needs, we will use it for the simple use case of passing in input and retrieving the output from OpenAI.

```python
from grafi.agents.react_agent import create_react_agent

react_agent = create_react_agent()

result = react_agent.run(user_input, invoke_context)

print("Output from React Agent:", result)


events = event_store.get_conversation_events(conversation_id)

print(f"Events for conversation {conversation_id}:")

print(f"Events: {events} ")

```

The key difference is that with the event store configured, all events will be automatically persisted.

Once you have built the workflow and invoked it we can get all the events from the previously configured `event_store` and print it out.




## Complete Example

Here's the complete `event_store.py` file that demonstrates the full integration:

```python
# event_store.py
 
import os
import uuid

from grafi.agents.react_agent import create_react_agent
from grafi.common.containers.container import container
from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message

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


react_agent = create_react_agent()

result = react_agent.run(user_input, invoke_context)


for output_message in result:
    print("Output message:", output_message)

events = event_store.get_conversation_events(conversation_id)

print(f"Events for conversation {conversation_id}:")
print(f"Events: {events} ")

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

<div class="python"><pre>
<code>
2025-07-12 17:38:55.566 | WARNING  | grafi.tools.function_calls.function_call_tool:__init_subclass__:86 - GoogleSearchTool: no method decorated with @llm_function found.
2025-07-12 17:38:55.895 | DEBUG    | grafi.common.instrumentations.tracing:is_local_endpoint_available:30 - Endpoint check failed: [Errno 111] Connection refused
2025-07-12 17:38:55.895 | DEBUG    | grafi.common.instrumentations.tracing:setup_tracing:117 - OTLP endpoint is not available. Using InMemorySpanExporter.
2025-07-12 17:38:55.905 | INFO     | grafi.common.topics.topic:publish_data:64 - [agent_input_topic] Message published with event_id: 1da4f45008264dc98fd63dc154dcaa6e
2025-07-12 17:38:55.912 | DEBUG    | grafi.nodes.node:invoke:49 - Executing Node with inputs: [ConsumeFromTopicEvent(event_id='8dd13f159fbc40b29ca030501f4d2859', event_version='1.0', invoke_context=InvokeContext(conversation_id='9051491ca7a84b71a3f3e9d790b79e4f', invoke_id='6e56da25ca824bf4a8d454a731b6f336', assistant_request_id='0e0317d25c9b40e4a76a130bbbb7bc43', user_id='9e396be8f8c442bc9269a31a9b3f69a2'), event_type=<EventType.CONSUME_FROM_TOPIC: 'ConsumeFromTopic'>, timestamp=datetime.datetime(2025, 7, 12, 16, 38, 55, 909090, tzinfo=datetime.timezone.utc), topic_name='agent_input_topic', offset=0, data=[Message(name=None, message_id='ae2638fa5f3047fbbfb43dbd1545e6d2', timestamp=1752338335885634346, content='What is the capital of the United Kingdom', refusal=None, annotations=None, audio=None, role='user', tool_call_id=None, tools=None, function_call=None, tool_calls=None, is_streaming=False)], consumer_name='OpenAIInputNode', consumer_type='OpenAIInputNode')]
2025-07-12 17:38:57.400 | INFO     | grafi.common.topics.topic:publish_data:69 - [function_call_topic] Message NOT published (condition not met)
2025-07-12 17:38:57.400 | INFO     | grafi.common.topics.output_topic:publish_data:91 - [agent_output_topic] Message published with event_id: d83d3339fbd94d6e983fc51965177891
<span style="color:#FF4689">Output from React Agent:</span>  The capital of the United Kingdom is London.
<span style="color:#FF4689">Events for conversation: </span> 9051491ca7a84b71a3f3e9d790b79e4f:
<span style="color:#FF4689">Events: </span>[AssistantInvokeEvent(event_id='7d97059ad3404c74be582ed4d01e365e', event_version='1.0', invoke_context=InvokeContext(conversation_id='9051491ca7a84b71a3f3e9d790b79e4f', invoke_id='6e56da25ca824bf4a8d454a731b6f336', assistant_request_id='0e0317d25c9b40e4a76a130bbbb7bc43', user_id='9e396be8f8c442bc9269a31a9b3f69a2'), event_type=<EventType.ASSISTANT_INVOKE: 'AssistantInvoke'>, timestamp=datetime.datetime(2025, 7, 12, 16, 38, 55, 885710), assistant_id='de51912ecc6c44ce803a0cd5eb358ba5', assistant_name='ReActAgent', assistant_type='ReActAgent', input_data=[Message(name=None, message_id='ae2638fa5f3047fbbfb43dbd1545e6d2', timestamp=1752338335885634346, content='What is the capital of the United Kingdom', refusal=None, annotations=No```</code></pre></div>
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
- **Session Continuity**: Maintain history across multiple interactions
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
- Ensure PostgreSQL container is running: `docker compose ps`
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
