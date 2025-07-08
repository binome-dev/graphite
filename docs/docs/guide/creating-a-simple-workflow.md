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

### 1. Import Statements

```python
import os

from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
```

**Line 1**: We import the `os` module to access environment variables.

**Lines 3-4**: Import predefined topics that handle agent communication:
- `agent_output_topic`: Where the agent publishes its responses
- `agent_input_topic`: Where the agent receives user input

**Line 5**: Import the `Node` class, which represents a processing unit in the workflow.

**Line 6**: Import `OpenAITool`, a specialized tool for integrating with OpenAI's API.

**Line 7**: Import `EventDrivenWorkflow`, which orchestrates the entire AI workflow using events.

**Lines 8-9**: Import data models:
- `InvokeContext`: Contains metadata about the current invocation
- `Message`: Represents a single message in the conversation

### 2. Environment Configuration

```python
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is required")

model = os.getenv("OPENAI_MODEL", "gpt-4o")
system_message = os.getenv("OPENAI_SYSTEM_MESSAGE", "You are a helpful assistant.")
```

**Line 11**: Retrieve the OpenAI API key from environment variables.

**Lines 12-13**: Validate that the API key exists, raising an error if it's missing.

**Line 15**: Get the model name from environment variables, defaulting to "gpt-4o" if not specified.

**Line 16**: Set the system message that defines the AI's behavior, with a default helpful assistant prompt.

### 3. Main Function Setup

```python
def main():
    user_input = "What is the capital of the United Kingdom"

    invoke_context = InvokeContext(
        user_id="user123",
        conversation_id="conversation456",
        invoke_id="invoke789",
        assistant_request_id="request101112"
    )

    message = Message(
        role="user",
        content=user_input
    )
```

**Line 19**: Define the main function that orchestrates the entire workflow.

**Line 20**: Set up a sample user question about the UK's capital.

**Lines 22-27**: Create an `InvokeContext` object containing:
- `user_id`: Identifies the user making the request
- `conversation_id`: Groups related messages in a conversation
- `invoke_id`: Unique identifier for this specific invocation
- `assistant_request_id`: Tracks the specific request

**Lines 29-32**: Create a `Message` object representing the user's input:
- `role`: Specifies this is a "user" message
- `content`: Contains the actual question text

### 4. Node Creation

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
```

**Lines 35-47**: Create an AI node using the builder pattern:

**Line 36**: Start building a new Node instance.

**Line 37**: Name the node "OpenAINode" for identification.

**Line 38**: Subscribe to the input topic to receive user messages.

**Lines 39-45**: Configure the OpenAI tool:
- **Line 40**: Start building the OpenAI tool
- **Line 41**: Name the tool "OpenAITool"
- **Line 42**: Set the API key for authentication
- **Line 43**: Specify which model to use
- **Line 44**: Set the system message that defines AI behavior
- **Line 45**: Build the tool instance

**Line 46**: Configure the node to publish responses to the output topic.

**Line 47**: Build the final node instance.

### 5. Workflow Creation

```python
workflow = (
    EventDrivenWorkflow.builder()
    .name("OpenAIEventDrivenWorkflow")
    .node(llm_node)
    .build()
)
```

**Lines 49-54**: Create an event-driven workflow:

**Line 50**: Start building the workflow.

**Line 51**: Name the workflow for identification.

**Line 52**: Add the previously created LLM node to the workflow.

**Line 53**: Build the workflow instance.

### 6. Workflow Execution

```python
result = workflow.invoke(
    invoke_context,
    [message]
)

for output_message in result:
    print("Output message:", output_message.content)
```

**Lines 57-60**: Execute the workflow:
- **Line 57**: Call the workflow's invoke method
- **Line 58**: Pass the context containing metadata
- **Line 59**: Pass a list containing the user's message

**Lines 62-63**: Process the results:
- **Line 62**: Iterate through each response message
- **Line 63**: Print the content of each response

### 7. Entry Point

```python
if __name__ == "__main__":
    main()
```

**Lines 67-68**: Standard Python entry point that runs the main function when the script is executed directly.

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
   python your_script.py
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
