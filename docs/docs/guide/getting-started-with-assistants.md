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

Let's examine how to transform our simple workflow into a powerful assistant. For this we will create an finance assistant that will provide us with financial information to make decisions.

### Global Configuration

```python
CONVERSATION_ID = uuid.uuid4().hex
```

Set `CONVERSATION_ID` to track conversation flow.
### Assistant Class Definition

```python
# main.py
from grafi.assistants.assistant import Assistant
from typing import Optional

from pydantic import Field

class FinanceAssistant(Assistant):
    """Assistant for handling financial queries and analysis using OpenAI."""

    name: str = Field(default="FinanceAssistant")
    type: str = Field(default="FinanceAssistant")
    api_key: Optional[str] = Field(default=os.getenv("OPENAI_API_KEY"))
    model: str = Field(default=os.getenv("OPENAI_MODEL", "gpt-4o"))
    system_message: str = Field(default=os.getenv("OPENAI_SYSTEM_MESSAGE"))

```

Create a class that defines the assistant class inheriting from Graphite's base `Assistant` class.
A good practice is to use Pydantic fields for configuration with environment variable defaults:
- `name` and `type`: Identify the assistant instance
- `api_key`: OpenAI API key with environment variable fallback
- `model`: OpenAI model selection with default
- `system_message`: Customizable system prompt


### Builder Class Implementation

```python
# main.py
from typing import Self
from grafi.assistants.assistant_base import AssistantBaseBuilder


class FinanceAssistantBuilder(AssistantBaseBuilder[FinanceAssistant]):
    """Concrete builder for FinanceAssistant."""

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

This class is used to set the fields from the `FinanceAssistant` the magic happens on the `builer` method up next.

### Builder Pattern Implementation

```python
class FinanceAssistant(Assistant):

    ...

    @classmethod
    def builder(cls) -> "FinanceAssistantBuilder":
        """Return a builder for FinanceAssistant."""
        return FinanceAssistantBuilder(cls)
```

Implement the builder pattern for fluent configuration of the assistant. This piece makes sure that when you call the builder() class methohd, instead of returning an instance of `FinanceAssistant` it will return an instance of `FinanceAssistantBuilder` which will configure the main assistant class's values.

### Workflow Construction

```python
from grafi.nodes.node import Node
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow



class FinanceAssistant(Assistant):

    ...

    def _construct_workflow(self) -> "FinanceAssistant":
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
            .name("FinanceWorkflow")
            .node(finance_llm_node)
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
Prepare input data and context for workflow execution:
- Creates a new `InvokeContext` if none is provided
- Uses the global conversation ID for session continuity
- Formats the user question as a `Message` object
- Returns both the input data and context

```python
from grafi.common.models.invoke_context import InvokeContext
from typing import Optional
from grafi.common.models.message import Message

class FinanceAssistant(Assistant):

    ...

    def get_input(self, question: str, invoke_context: Optional[InvokeContext] = None) -> tuple[list[Message], InvokeContext]:
        """Prepare input data and invoke context."""
        if invoke_context is None:
            logger.debug("Creating new InvokeContext with default conversation id for FinanceAssistant")
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



This function is not part of the framework, but rather a helper function used to process inputs. It is not necessary, you are free to handle input as you wish.

### Assistant Execution

```python
class FinanceAssistant(Assistant):

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


### Putting it all together

Now that we have created the class for the assistance, we have to instantiate it and provide the fields in order to call it. A direct implementation of an assistant is as follows.

```python
# main.py
def main():
    system_message = os.getenv("OPENAI_SYSTEM_MESSAGE")
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")

    builder = FinanceAssistant.builder()
    assistant = (
        builder
        .system_message(system_message)
        .model(model)
        .api_key(api_key)
        .build()
    )

    """Main function to run the assistant."""
    user_input = "What are the key factors to consider when choosing between a 401(k) and a Roth IRA?"
    result = assistant.run(user_input)
    print("Output message:", result)


if __name__ == "__main__":
    main()

```

A better approach would be to create a function that handles the creation of the agent so we can create multiple ones if needed.

```python
# main.py
def create_finance_assistant(
    system_message: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> FinanceAssistant:
    """Create a FinanceAssistant instance."""
    builder = FinanceAssistant.builder()

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
# These values are for readability, as these values are already being set from the environment variables from within the class

    assistant = create_finance_assistant(
        system_message,
        model,
        api_key
    )

    """Main function to run the assistant."""
    user_input = "What are the key factors to consider when choosing between a 401(k) and a Roth IRA?"
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
export OPENAI_SYSTEM_MESSAGE="You are a knowledgeable financial advisor assistant. Help users with financial planning, investment analysis, market insights, and general financial questions. Provide accurate, helpful advice while emphasizing the importance of professional financial consultation for major decisions."  # Optional
```

2. **Execute the script**:


<div class="bash"><pre>
<code><span style="color:#FF4689">python</span> main.py</code></pre></div>

3. **Expected output**:
```
Output message:
Financial advice: When choosing between a 401(k) and a Roth IRA, it's important to consider several key factors. Each has its unique advantages and may be better suited to different financial situations and goals. Here are some factors to consider:

1. **Tax Treatment**:
- **401(k)**: Contributions are typically made with pre-tax dollars, which can lower your current taxable income. However, withdrawals during retirement are taxed as ordinary income.
- **Roth IRA**: Contributions are made with after-tax dollars, meaning you pay taxes upfront. However, qualified withdrawals are tax-free, including the earnings.

2. **Income and Contribution Limits**:
- **401(k)**: As of 2023, the contribution limit is $22,500 annually, with an additional $7,500 catch-up contribution for those aged 50 and over. There are no income limits for 401(k) eligibility.
- **Roth IRA**: The contribution limit is $6,500 annually, with a $1,000 catch-up contribution for those aged 50 and over. Contributions are restricted for high earners. For example, for 2023, contributions phase out for single filers with MAGI (Modified Adjusted Gross Income) between $138,000 and $153,000.
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
stock_assistant = create_finance_assistant(
    system_message="You are a stock specialist,  you will process all contexst data and give out the best stock picks for a given date",
    model="gpt-4o"
)

currency_assistant = create_finance_assistant(
    system_message="You are a currency specialist, you will analyze all contexts and data to get the best currency trades possible",
    model="gpt-3.5-turbo"
)
```

### Using the Builder Pattern

```python
custom_assistant = (
    FinanceAssistant.builder()
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
response1 = stock_assistant.run("Give me the best stock today to buy for a 10% gain in 2025", context)
response2 = currency_assistant.run("The lyra crashed, what's the best currency to exchange to?", context)
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


## Next Steps

With assistants implemented, you can:

1. **Build Complex Workflows**: Create multi-node workflows within assistants
2. **Implement Custom Tools**: Add specialized tools for specific use cases
3. **Add Conversation Memory**: Implement persistent conversation storage
4. **Create Assistant Hierarchies**: Build networks of cooperating assistants
5. **Add Monitoring**: Implement comprehensive logging and metrics
6. **Use Grafi-Dev**: Graphite's internal workflow UI

The assistant pattern provides a solid foundation for building production-ready AI applications that are maintainable, testable, and scalable.
