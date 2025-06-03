# Getting Started with Graphite: The Hello, World! Assistant

[Graphite](https://github.com/binome-dev/graphite) is a powerful event-driven AI agent framework built for modularity, observability, and seamless composition of AI workflows. This comprehensive guide will walk you through creating your first ReAct (Reasoning and Acting) agent using the `grafi` package. In this tutorial, we'll build a function-calling assistant that demonstrates how to integrate language models with google search function within the Graphite framework, showcasing the core concepts of event-driven AI agent development.

---

## Prerequisites

Make sure the following are installed:

* Python **3.11 or 3.12** (required by the `grafi` package)
* [Poetry](https://python-poetry.org/docs/#installation)
* Git

> ⚠️ **Important:** `grafi` requires Python >=3.11 and <3.13. Python 3.13+ is not yet supported.

---

## 1. Create a New Project Directory

```bash
mkdir graphite-react
cd graphite-react
```

---

## 2. Initialize a Poetry Project

This will create the `pyproject.toml` file that Poetry needs. Be sure to specify a compatible Python version:

```bash
poetry init --name graphite-react -n
```

Then open `pyproject.toml` and ensure it includes:

```toml
[tool.poetry.dependencies]
grafi = "^0.0.12"
python = ">=3.11,<3.13"
```

Now install the dependencies:

```bash
poetry install --no-root
```

This will automatically create a virtual environment and install `grafi` with the appropriate Python version.

> 💡 You can also create the virtual environment with the correct Python version explicitly:
>
> ```bash
> poetry env use python3.12
> ```

---

## 3. Create ReAct Assistant

In graphite an assistant is a specialized node that can handle events and perform actions based on the input it receives. We will create a simple assistant that uses OpenAI's language model to process input, make function calls, and generate responses.

Create a file named `react_assistant.py` and add the code like following:

### Class `ReactAssistant`
```python
# react assistant.py
import os
import uuid
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.impl.llm_function_call_node import LLMFunctionCallNode
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.impl.google_search_tool import GoogleSearchTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm_response_command import LLMResponseCommand
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


AGENT_SYSTEM_MESSAGE = """
You are a helpful and knowledgeable agent. To achieve your goal of answering complex questions
correctly, you have access to the search tool.

To answer questions, you'll need to go through multiple steps involving step-by-step thinking and
selecting search tool if necessary.

Response in a concise and clear manner, ensuring that your answers are accurate and relevant to the user's query.
"""


class ReactAssistant(Assistant):

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="ReactAssistant")
    type: str = Field(default="ReactAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    system_prompt: Optional[str] = Field(default=AGENT_SYSTEM_MESSAGE)
    function_call_tool: FunctionCallTool = Field(
        default=GoogleSearchTool.Builder()
        .name("GoogleSearchTool")
        .fixed_max_results(3)
        .build()
    )
    model: str = Field(default="gpt-4o-mini")

    class Builder(Assistant.Builder):
        """Concrete builder for ReactAssistant."""

        _assistant: "ReactAssistant"

        def __init__(self) -> None:
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "ReactAssistant":
            return ReactAssistant.model_construct()

        def api_key(self, api_key: str) -> Self:
            self._assistant.api_key = api_key
            return self

        def system_prompt(self, system_prompt: str) -> Self:
            self._assistant.system_prompt = system_prompt
            return self

        def function_call_tool(self, function_call_tool: FunctionCallTool) -> Self:
            self._assistant.function_call_tool = function_call_tool
            return self

        def model(self, model: str) -> Self:
            self._assistant.model = model
            return self

        def build(self) -> "ReactAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "ReactAssistant":
        function_call_topic = Topic(
            name="function_call_topic",
            condition=lambda msgs: msgs[-1].tool_calls
            is not None,  # only when the last message is a function call
        )
        function_result_topic = Topic(name="function_result_topic")

        agent_output_topic.condition = (
            lambda msgs: msgs[-1].content is not None
            and isinstance(msgs[-1].content, str)
            and msgs[-1].content.strip() != ""
        )

        llm_node = (
            LLMNode.Builder()
            .name("OpenAIInputNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("UserInputLLM")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.system_prompt)
                    .build()
                )
                .build()
            )
            .publish_to(function_call_topic)
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a function call node
        function_call_node = (
            LLMFunctionCallNode.Builder()
            .name("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .command(
                FunctionCallCommand.Builder()
                .function_tool(self.function_call_tool)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.Builder()
            .name("simple_agent_workflow")
            .node(llm_node)
            .node(function_call_node)
            .build()
        )

        return self
```

---

## 4. Call the Assistant

Create a `main.py` that will call the assistant created previously.

```python
import os
import uuid

from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from <your react assistant path> import ReactAssistant

api_key = "<your openai api key>"

react_assistant = ReactAssistant.Builder().api_key(api_key).build()

execution_context = ExecutionContext(
            conversation_id=uuid.uuid4().hex,
            execution_id=uuid.uuid4().hex,
            assistant_request_id=uuid.uuid4().hex,
        )

question = "your question"

input_data = [
            Message(
                role="user",
                content=qestion,
            )
        ]

output = react_assistant.execute(execution_context, input_data)
print(output[0].content)
```


## 5. Run the Application

Use Poetry to execute the script inside the virtual environment:

```bash
poetry run python main.py
```

You should see the output result

```
Graphite is an open-source framework designed for building domain-specific AI agents using composable workflows. It features an event-driven architecture that allows developers to create customizable workflows. This framework is particularly focused on constructing AI assistants that can interact within specific domains effectively.

For more detailed information, you can refer to the following resources:
1. [Introducing Graphite — An Event Driven AI Agent Framework](https://medium.com/binome/introduction-to-graphite-an-event-driven-ai-agent-framework-540478130cd2)
2. [Graphite - Framework AI Agent Builder](https://bestaiagents.ai/agent/graphite)
```

---

## Summary

✅ Initialized a Poetry project

✅ Installed `grafi` with the correct Python version constraint

✅ Wrote a minimal agent that handles an event

✅ Ran the agent with a question

---

## Next Steps

* Explore the [Graphite GitHub Repository](https://github.com/binome-dev/graphite) for full-featured examples.
* Extend your agent to respond to different event types.
* Dive into advanced features like memory, workflows, and tools.

---

Happy building! 🚀
