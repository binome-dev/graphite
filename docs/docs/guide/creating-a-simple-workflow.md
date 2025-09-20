# Building Your First AI Agent with Graphite AI Framework

The Graphite AI framework provides a powerful, event-driven approach to building AI agents and workflows. In this tutorial, we'll walk through a complete example that demonstrates how to create a simple AI assistant using OpenAI's GPT models.

## Overview

This tutorial will show you how to:
- Set up environment variables for API configuration
- Create an AI node using OpenAI's tools
- Build an event-driven workflow
- Handle user input and process responses

## Prerequisites

Before getting started, make sure you have:
- Python environment with Graphite AI framework installed
- OpenAI API key
- Basic understanding of Python and AI concepts

## Code Walkthrough

Let's examine the complete code and break it down line by line:


### 1. Environment Configuration

Configure your code to read `OPENAI_API_KEY` from your environment, as well as `OPENAI_MODEL` and `OPENAI_SYSTEM_MESSAGE`. You can modify the default values if you prefer not to set environment variables, although it is recommended to set `OPENAI_API_KEY` as an environment variable for security.

```python
import os
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is required")

model = os.getenv("OPENAI_MODEL", "gpt-4o")
system_message = os.getenv("OPENAI_SYSTEM_MESSAGE", "You are a helpful assistant.")
```


### 2. Main Function Setup

The main function orchestrates the entire workflow. We start by defining a sample user question about the UK's capital, then create the necessary context and message objects.

```python linenums="9"
import uuid
from grafi.common.models.message import Message
from grafi.common.models.invoke_context import InvokeContext

def main():
    user_input = "What is the capital of the United Kingdom"

    invoke_context = InvokeContext(
        user_id=uuid.uuid4().hex,
        conversation_id=uuid.uuid4().hex,
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )

    message = Message(
        role="user",
        content=user_input
    )
```


The `InvokeContext` maintains the workflow state and tracking information across different operations in the system. It provides essential context for conversation management and request tracing.



- `user_id`: Optional user identifier, defaults to empty string.
- `conversation_id`: Unique identifier for a conversation between user and assistant.
- `invoke_id`: Unique identifier for each conversation invoke - an invoke can involve multiple agents.
- `assistant_request_id`: Created when an agent receives a request from the user.

The `Message` object represents the user's input:
- `role`: Specifies this is a "user" message
- `content`: Contains the actual question text

### 3. Node Creation

Nodes are first-class citizens in Graphite - all functionality must be wrapped in a node. Since we want to query OpenAI for the capital of the United Kingdom, we create a Node using the builder pattern.

The node subscribes to the `agent_input_topic` (the root topic in Graphite), uses the `OpenAITool` to query OpenAI's endpoint with the required configuration (`api_key`, `model`, and `system_message`), and publishes results to the `agent_output_topic` (the final topic in any Graphite workflow).

```python linenums="27"
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.input_topic import InputTopic
from grafi.topics.output_topic import OutputTopic


agent_input_topic = InputTopic(name="agent_input_topic")
agent_output_topic = OutputTopic(name="agent_output_topic")

llm_node = (
    Node.builder()
    .name("LLMNode")
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
```


### 4. Workflow Creation

Now that we have created a node with its input (subscribe) and output (publish_to) configuration, we must bind it to a workflow. We use Graphite's `EventDrivenWorkflow` with the builder pattern to attach the node.

```python linenums="46"
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

workflow = (
    EventDrivenWorkflow.builder()
    .name("OpenAIEventDrivenWorkflow")
    .node(llm_node)
    .build()
)
```


### 5. Workflow Execution

With the `EventDrivenWorkflow` object created, we can invoke it by passing our `invoke_context` and a `List[Message]`. The workflow will execute and return the results, which we can then print. Save this complete code as `main.py`.

```python linenums="54"
async for result in workflow.invoke(
    invoke_context,
    [message]
):
    for output_message in result:
        print("Output message:", output_message.content)
```

### 6. Entry Point

Finally, add the standard Python entry point to run the main function when the script is executed directly.

```python linenums="62"
if __name__ == "__main__":
    main()
```

## Running the Code

To run this example:

1. **Set up environment variables**:
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   export OPENAI_MODEL="gpt-4o"  # Optional
   export OPENAI_SYSTEM_MESSAGE="You are a helpful assistant."  # Optional
   ```

2. **Execute the script**:
   ```bash
   python main.py
   ```

3. **Expected output**:
   ```
   Output message: The capital of the United Kingdom is London.
   ```

## Key Concepts

### Event-Driven Architecture
The Graphite AI framework uses an event-driven approach where:
- Nodes subscribe to topics to receive messages
- Nodes publish responses to output topics
- Workflows orchestrate the flow of events between nodes

### Builder Pattern
The framework extensively uses the builder pattern, allowing for:
- Fluent, readable configuration
- Step-by-step construction of complex objects
- Flexible parameter setting

### Context Management
The `InvokeContext` provides crucial metadata for:
- Tracking user sessions
- Managing conversation state
- Debugging and logging

## Next Steps

This example demonstrates the basics of the Graphite AI framework. You can extend this by:
- Adding multiple nodes for complex workflows
- Implementing custom tools and integrations
- Building more sophisticated conversation management
- Adding error handling and logging

The framework's event-driven nature makes it easy to create scalable, maintainable AI applications that can grow with your needs.
