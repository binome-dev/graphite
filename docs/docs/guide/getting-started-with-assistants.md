# Creating AI Assistants with Graphite AI Framework

Building on the foundational concepts from creating simple workflows, this guide demonstrates how to wrap your workflows in Graphite's Assistant framework. Assistants provide a higher-level abstraction that encapsulates workflow logic, making it easier to create reusable, maintainable AI components.

## Overview

This guide will show you how to:
- Convert a simple workflow into a reusable assistant
- Implement the Assistant pattern with builder design
- Create flexible, configurable AI assistants
- Handle different types of user interactions
- Build production-ready AI components

## Prerequisites

Before getting started, make sure you have:
- Completed the [Simple Workflow Guide](creating-a-simple-workflow.md)
- Python environment with Graphite AI framework installed
- OpenAI API key configured
- Understanding of Python classes and inheritance

## Comparison: Workflow vs Assistant

| Aspect | Simple Workflow | Assistant |
|--------|----------------|-----------|
| **Reusability** | Limited | High |
| **Configuration** | Hardcoded | Flexible |
| **Conversation Management** | Manual | Built-in |
| **Error Handling** | Basic | Comprehensive |
| **Type Safety** | Limited | Full |
| **Testing** | Complex | Simple |

## From Workflow to Assistant

In the simple workflow guide, we created a basic event-driven workflow. While functional, this approach has limitations:
- No reusability across different contexts
- Hardcoded configuration values
- Limited conversation management
- No encapsulation of business logic

Assistants solve these problems by providing a structured, object-oriented approach to workflow management.

## Code Walkthrough

Let's examine how to transform our simple workflow into a powerful assistant. For this we will create an alert assistant that will assist us later to handle alerts from other services.

<!-- ### 1. Import Dependencies

```python linenums="1"
import os
import uuid
from typing import Self

from loguru import logger
from pydantic import Field

from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
```

**Lines 1-8**: Import standard Python libraries for type hints, logging, and data validation.

**Lines 10-17**: Import Graphite framework components for assistants, models, topics, nodes, tools, and workflows.



**Line 19**: Define a global conversation ID for maintaining context across assistant interactions. -->

### Global Configuration

```python linenums="19"
CONVERSATION_ID = uuid.uuid4().hex
```

Set `CONVERSATION_ID` to track conversation flow.
### Assistant Class Definition

```python
# main.py
from grafi.assistants.assistant import Assistant
from typing import Optional

from pydantic import Field

class GraphiteAlertsAssistant(Assistant):
    """Assistant for handling graphite alerts using OpenAI."""
    
    name: str = Field(default="GraphiteAlertsAssistant")
    type: str = Field(default="GraphiteAlertsAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default=os.getenv("OPENAI_MODEL", "gpt-4o"))
    system_message: str = Field(default=os.getenv("OPENAI_SYSTEM_MESSAGE", "You are a helpful assistant for handling graphite alerts."))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
```

Create a class that defines the assistant class inheriting from Graphite's base `Assistant` class.
A good practice is to use Pydantic fields for configuration with environment variable defaults:
- `name` and `type`: Identify the assistant instance
- `api_key`: OpenAI API key with environment variable fallback
- `model`: OpenAI model selection with default
- `system_message`: Customizable system prompt

Even though we have default values it's good practice to allow users to override the values. You should use a separate file for this class, but for simplicity's sake we will keep it all on the `main.py` file.

### Builder Class Implementation

```python 
# main.py
class GraphiteAlertsAssistantBuilder(AssistantBaseBuilder[GraphiteAlertsAssistant]):
    """Concrete builder for GraphiteAlertsAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def system_message(self, system_message: str) -> Self:
        self.kwargs["system_message"] = system_message
        return self
```

 Implement the builder pattern for fluent configuration:
- Extends the base assistant builder
- Provides methods for setting API key, model, and system message
- Returns `self` for method chaining

This class is used to set the fields from the `GraphiteAlertsAssistant` the magic happens on the `builer` method up next.

### Builder Pattern Implementation

```python 
class GraphiteAlertsAssistant(Assistant):

    ...

    @classmethod
    def builder(cls) -> "GraphiteAlertsAssistantBuilder":
        """Return a builder for GraphiteAlertsAssistant."""
        return GraphiteAlertsAssistantBuilder(cls)
```

Implement the builder pattern for fluent configuration of the assistant. This piece makes sure that when you call the builder() class methohd, instead of returning an instance of `GraphiteAlertsAssistant` it will return an inner class called `GraphiteAlertsAssistantBuilder` that will configure the assistant.

### Workflow Construction

```python linenums="41"
class GraphiteAlertsAssistant(Assistant):

    ...

    def _construct_workflow(self) -> "GraphiteAlertsAssistant":
        """Construct the workflow for the assistant."""
        llm_node = (
            Node.builder()
            .name("OpenAINode")
            .subscribe(agent_input_topic)
            .tool(
                OpenAITool.builder()
                .name("OpenAITool")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.system_message)
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("GraphiteAlertsWorkflow")
            .node(llm_node)
            .build()
        )

        return self
```

Here we implement the `_construct_workflow` method to create the internal workflow using the same pattern as the simple workflow guide, but now encapsulated within the assistant class. This method:
- Creates an OpenAI node with instance-specific configuration.
- Builds the event-driven workflow.
- Stores the workflow as an instance variable.

All the same principles that the simple workflow used apply here.

### Input Preparation

```python 
from grafi.common.models.invoke_context import InvokeContext
from typing import Optional
from grafi.common.models.message import Message

class GraphiteAlertsAssistant(Assistant):

    ...

    def get_input(self, question: str, invoke_context: Optional[InvokeContext] = None) -> tuple[list[Message], InvokeContext]:
        """Prepare input data and invoke context."""
        if invoke_context is None:
            logger.debug("Creating new InvokeContext with default conversation id for GraphiteAlertsAssistant")
            invoke_context = InvokeContext(
                user_id=uuid.uuid4().hex,
                conversation_id=CONVERSATION_ID,
                invoke_id=uuid.uuid4().hex,
                assistant_request_id=uuid.uuid4().hex,
            )

        input_data = [
            Message(
                role="user",
                content=question,
            )
        ]

        return input_data, invoke_context
```

Prepare input data and context for workflow execution:
- Creates a new `InvokeContext` if none is provided
- Uses the global conversation ID for session continuity
- Formats the user question as a `Message` object
- Returns both the input data and context

This function is not part of the framework, but rather a helper function used to process inputs. It is not necessary, you are free to handle input as you wish.

### Assistant Execution

```python
class GraphiteAlertsAssistant(Assistant):

    ...
    def run(self, question: str, invoke_context: Optional[InvokeContext] = None) -> str:
        """Run the assistant with a question and return the response."""
        # Call helper function get_input()
        input_data, invoke_context = self.get_input(question, invoke_context)
        # This is the line that invokes the workflow
        output = super().invoke(invoke_context, input_data)
        
        # Handle different content types
        if output and len(output) > 0:
            content = output[0].content
            if isinstance(content, str):
                return content
            elif content is not None:
                return str(content)
        
        return "No response generated"
```

Main execution method that:
- Prepares input data and context
- Invokes the parent class's workflow execution `invoke()` method
- Handles different response content types
- Returns a clean string response



<!-- ### 7. Factory Function

```python
def create_graphite_alerts_assistant(
    system_message: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> GraphiteAlertsAssistant:
    """Create a GraphiteAlertsAssistant instance."""
    builder = GraphiteAlertsAssistant.builder()

    if system_message:
        builder.system_message(system_message)
    if model:
        builder.model(model)
    if api_key:
        builder.api_key(api_key)
    
    return builder.build()
```

**Lines 122-137**: Convenience factory function for creating assistant instances:
- Provides optional parameters for configuration
- Uses the builder pattern internally
- Returns a configured assistant instance

### 10. Global Assistant Instance

```python linenums="140"
# Create the global assistant instance
assistant = create_graphite_alerts_assistant()
```

**Lines 139-140**: Create a global assistant instance for easy access throughout the application. -->

<!-- ### 11. Testing and Execution

```python linenums="143"
def test_assistant():
    """Test the assistant with different questions."""
    print("Testing GraphiteAlertsAssistant...\n")
    
    # Test with different questions
    questions = [
        "What is the capital of France?",
        "How do you handle graphite alerts?",
        "What is 2 + 2?",
    ]
    
    for question in questions:
        print(f"Question: {question}")
        response = assistant.run(question)
        print(f"Response: {response}\n")


def main():
    """Main function to run the assistant."""
    user_input = "What is the capital of the United Kingdom"
    result = assistant.run(user_input)
    print("Output message:", result)
    
    # Uncomment to test multiple questions
    # test_assistant()


if __name__ == "__main__":
    main()
```

**Lines 143-171**: Provide testing and execution functions:
- `test_assistant()`: Tests the assistant with multiple questions
- `main()`: Simple execution example
- Standard Python entry point -->

### Putting it all together

Now that we have created the class for the assistance, we have to instantiate it and provide the fields in order to call it. A direct implementation of an assistant is as follows.

```python
# main.py
def main():
    builder = GraphiteAlertsAssistant.builder()
    assistant = (
        builder
        .system_message("You are a helpful assistant for handling graphite alerts.")
        .model("gpt-4o")
        .api_key(os.getenv("OPENAI_API_KEY"))
        .build()
    )

    """Main function to run the assistant."""
    user_input = "What is the capital of the United Kingdom"
    result = assistant.run(user_input)
    print("Output message:", result)


if __name__ == "__main__":
    main()

```

A better approach would be to create a function that handles the creation of the agent so we can create multiple ones if needed.

```python
# main.py
def create_graphite_alerts_assistant(
    system_message: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> GraphiteAlertsAssistant:
    """Create a GraphiteAlertsAssistant instance."""
    builder = GraphiteAlertsAssistant.builder()

    if system_message:
        builder.system_message(system_message)
    if model:
        builder.model(model)
    if api_key:
        builder.api_key(api_key)
    
    return builder.build()

def main():

    system_message = os.getenv("OPENAI_SYSTEM_MESSAGE")
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    assistant = create_graphite_alerts_assistant(
        system_message,
        model,
        api_key
    ) 
   
    """Main function to run the assistant."""
    user_input = "What is the capital of the United Kingdom"
    result = assistant.run(user_input)
    print("Output message:", result)


if __name__ == "__main__":
    main()
```



## Running the Assistant

To run this assistant example:

1. **Set up environment variables**:
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   export OPENAI_MODEL="gpt-4o"  # Optional
   export OPENAI_SYSTEM_MESSAGE="You are a helpful assistant for handling graphite alerts."  # Optional
   ```

2. **Execute the script**:
   ```bash
   python main.py
   ```

3. **Expected output**:
   ```
   Output message: The capital of the United Kingdom is London.
   ```

## Key Benefits of the Assistant Pattern

### 1. **Encapsulation and Reusability**
- Workflow logic is encapsulated within the assistant class
- Easy to reuse across different applications
- Configuration is centralized and manageable

### 2. **Flexible Configuration**
- Environment variable support with defaults
- Builder pattern for fluent configuration
- Type-safe configuration with Pydantic

### 3. **Conversation Management**
- Built-in conversation ID management
- Context preservation across interactions
- Simplified input/output handling

### 4. **Production Readiness**
- Proper error handling and validation
- Logging integration
- Type hints for better IDE support

## Advanced Usage Examples

### Creating Multiple Assistant Instances

```python
# Create specialized assistants for different use cases
support_assistant = create_graphite_alerts_assistant(
    system_message="You are a technical support specialist.",
    model="gpt-4o"
)

sales_assistant = create_graphite_alerts_assistant(
    system_message="You are a sales representative.",
    model="gpt-3.5-turbo"
)
```

### Using the Builder Pattern

```python
custom_assistant = (
    GraphiteAlertsAssistant.builder()
    .api_key("your-api-key")
    .model("gpt-4o")
    .system_message("You are a custom assistant.")
    .build()
)
```

### Conversation Context Management

```python
# Create a conversation context
context = InvokeContext(
    user_id="user123",
    conversation_id="conv456",
    invoke_id=uuid.uuid4().hex,
    assistant_request_id=uuid.uuid4().hex,
)

# Use the same context across multiple interactions
response1 = assistant.run("Hello, how are you?", context)
response2 = assistant.run("What did I just ask?", context)
```



## Best Practices

### 1. **Configuration Management**
- Use environment variables for sensitive data
- Provide sensible defaults
- Validate configuration in the constructor

### 2. **Error Handling**
- Implement proper error handling in the `run` method
- Use logging for debugging and monitoring
- Provide meaningful error messages

### 3. **Type Safety**
- Use Pydantic for configuration validation
- Implement proper type hints
- Use generic types for builder patterns

### 4. **Testing**
- Create comprehensive test suites
- Test different conversation scenarios
- Mock external dependencies

## Common Patterns

### Singleton Pattern
```python
class SingletonAssistant:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = create_graphite_alerts_assistant()
        return cls._instance
```

### Factory Pattern
```python
class AssistantFactory:
    @staticmethod
    def create_assistant(assistant_type: str) -> Assistant:
        if assistant_type == "alerts":
            return create_graphite_alerts_assistant()
        elif assistant_type == "support":
            return create_support_assistant()
        else:
            raise ValueError(f"Unknown assistant type: {assistant_type}")
```

## Next Steps

With assistants implemented, you can:

1. **Build Complex Workflows**: Create multi-node workflows within assistants
2. **Implement Custom Tools**: Add specialized tools for specific use cases
3. **Add Conversation Memory**: Implement persistent conversation storage
4. **Create Assistant Hierarchies**: Build networks of cooperating assistants
5. **Add Monitoring**: Implement comprehensive logging and metrics

The assistant pattern provides a solid foundation for building production-ready AI applications that are maintainable, testable, and scalable.
