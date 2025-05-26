# Getting Started with Graphite: The Hello, World! Assistant

[Graphite](https://github.com/binome-dev/graphite) is an event-driven AI agent framework designed for modularity, observability, and composability. This guide will walk you through building a minimal "Hello, World" agent using the `grafi` package. For this example we will create a simple function call assistant that generates a mock user form and wrap it in a node to be used with the Graphite framework.

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
mkdir graphite-hello-world
cd graphite-hello-world
```

---

## 2. Initialize a Poetry Project

This will create the `pyproject.toml` file that Poetry needs. Be sure to specify a compatible Python version:

```bash
poetry init --name graphite-hello-world -n
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

## 3. Create Assistant

In graphite an assistant is a specialized node that can handle events and perform actions based on the input it receives. We will create a simple assistant that uses OpenAI's language model to process input, make function calls, and generate responses.

Create a file named `assistant.py` and add the code from our example directory <a href="https://github.com/binome-dev/graphite/blob/main/examples/function_assistant/simple_function_llm_assistant.py" title="SimpleFunctionLLMAssistant">here</a>
### Class `SimpleFunctionLLMAssistant`
```python
# assistant.py
class SimpleFunctionLLMAssistant(Assistant):

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="SimpleFunctionLLMAssistant")
    type: str = Field(default="SimpleFunctionLLMAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")
    output_format: OutputType
    function: Callable
```
- `oi_span_type`: this field defines the OpenInference span kind for the assistant, which is set to `AGENT`, ,you will see this span kind in the OpenTelemetry traces.
- `name`: the name of the assistant. This could be any string that identifies the assistant.
- `type`: the type of the assistant, which is set to `SimpleFunctionLLMAssistant`.
- `api_key`: the API key for OpenAI, which can be set via an environment variable or directly in the code.
- `model`: the model to be used by the assistant, defaulting to `gpt-4o-mini`.
- `output_format`: the format of the output, which is an instance of `OutputType`. This will be later used to define the output to be returned by the assistant. Will be mapped to a pydantic class.
- `function`: a callable function that the assistant will use to process the input data. This function is a python function, can be any callable that takes input and returns output. In this case, it will be used to process the user form data.


### Class `Builder`
Every assistant in Graphite has an inner class called builder class that allows you to construct the assistant step by step. The `Builder` class for `SimpleFunctionLLMAssistant` will allow you to set the API key, model, output format, and function before building the assistant. This class uses the builder pattern to create an instance of `SimpleFunctionLLMAssistant`. It is used to initialize the assistant with the fields that have been defined in the previous step.

```python
class SimpleFunctionLLMAssistant(Assistant):
   ...
   ...
    class Builder(Assistant.Builder):
        """Concrete builder for SimpleFunctionLLMAssistant."""

        _assistant: "SimpleFunctionLLMAssistant"

        def __init__(self) -> None:
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "SimpleFunctionLLMAssistant":
            return SimpleFunctionLLMAssistant.model_construct()

        def api_key(self, api_key: str) -> Self:
            self._assistant.api_key = api_key
            return self

        def model(self, model: str) -> Self:
            self._assistant.model = model
            return self

        def output_format(self, output_format: OutputType) -> Self:
            self._assistant.output_format = output_format
            return self

        def function(self, function: Callable) -> Self:
            self._assistant.function = function
            return self

        def build(self) -> "SimpleFunctionLLMAssistant":
            self._assistant._construct_workflow()
            return self._assistant
```

```python3
    def _construct_workflow(self) -> "SimpleFunctionLLMAssistant":
        function_topic = Topic(name="function_call_topic")

        llm_input_node = (
            LLMNode.Builder()
            .name("OpenAIInputNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("UserInputLLM")
                    .api_key(self.api_key)
                    .model(self.model)
                    .chat_params({"response_format": self.output_format})
                    .build()
                )
                .build()
            )
            .publish_to(function_topic)
            .build()
        )

        # Create a function node

        function_call_node = (
            FunctionNode.Builder()
            .name("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_topic).build())
            .command(
                FunctionCommand.Builder()
                .function_tool(FunctionTool.Builder().function(self.function).build())
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.Builder()
            .name("simple_function_call_workflow")
            .node(llm_input_node)
            .node(function_call_node)
            .build()
        )

        return self
```

---

## 4. Call the Assistant

Create a `main.py` that will call the assistant created previously.

### Setup `OPENAI_API_KEY`

```python
from grafi.common.containers.container import container
event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")
```

Replace your `OPENAI_API_KEY` in the environment variable or set it directly in the code for testing purposes.

```bash
export OPENAI_API_KEY="sk-proj-***********"
```

### Create the `UserForm` model
```python3
from pydantic import BaseModel

class UserForm(BaseModel):
    """
    A simple user form model for demonstration purposes.
    """

    first_name: str
    last_name: str
    location: str
    gender: str

```

### Create the `print_user_form` function

A function to print user form details from the messages received by the assistant.

```python3
from grafi.common.models.message import Message, Messages
def print_user_form(input_messages: Messages) -> List[str]:
    """
    Function to print user form details.

    Args:
        Messages: The input messages containing user form details.

    Returns:
        list: A list string containing the user form details.
    """

    user_details = []

    for message in input_messages:
        if message.role == "assistant" and message.content:
            try:
                if isinstance(message.content, str):
                    form = UserForm.model_validate_json(message.content)
                    print(
                        f"User Form Details:\nFirst Name: {form.first_name}\nLast Name: {form.last_name}\nLocation: {form.location}\nGender: {form.gender}\n"
                    )
                    user_details.append(form.model_dump_json(indent=2))
            except Exception as e:
                raise ValueError(
                    f"Failed to parse user form from message content: {message.content}. Error: {e}"
                )

    return user_details
```

### Create the `get_execution_context` function

This function will create an `ExecutionContext` for the assistant to use during execution. It generates unique IDs for conversation and execution to be tracked through the event store.

```python3
import uuid
from grafi.common.models.execution_context import ExecutionContext

def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )
```

### Putting it all together

```python3
execution_context = get_execution_context()

assistant = (
    SimpleFunctionLLMAssistant.Builder()
    .name("SimpleFunctionLLMAssistant")
    .api_key(api_key)
    .function(print_user_form)
    .output_format(UserForm)
    .build()
)

# Test the run method
input_data = [
    Message(
        role="user",
        content="Generate mock user.",
    )
]

output = assistant.execute(execution_context, input_data)
print(output)
```

---

## 5. Run the Application

Use Poetry to execute the script inside the virtual environment:

```bash
poetry run python main.py
```

You should see:

```
graphite-hello-world-OsMKLmDe-py3.12 ❯ poetry run python main.py
2025-05-26 19:19:10.299 | DEBUG    | grafi.common.instrumentations.tracing:is_local_endpoint_available:27 - Endpoint check failed: [Errno -3] Temporary failure in name resolution
2025-05-26 19:19:10.300 | DEBUG    | grafi.common.instrumentations.tracing:is_local_endpoint_available:27 - Endpoint check failed: [Errno 111] Connection refused
2025-05-26 19:19:10.300 | DEBUG    | grafi.common.instrumentations.tracing:setup_tracing:95 - OTLP endpoint is not available. Using InMemorySpanExporter.
2025-05-26 19:19:10.341 | INFO     | grafi.common.topics.topic:publish_data:76 - [agent_input_topic] Message published with event_id: 858d841f8b8d48498fc3c31cf9a50c24
2025-05-26 19:19:10.341 | DEBUG    | grafi.nodes.impl.llm_node:execute:57 - Executing LLMNode with inputs: [ConsumeFromTopicEvent(event_id='11ede69c47c34222a9bcb7c81adfb469', event_version='1.0', execution_context=ExecutionContext(conversation_id='conversation_id', execution_id='467fb5006a25440c80f5801c05bfc807', assistant_request_id='c574d43fdea94280817facb9c3a597dc', user_id=''), event_type=<EventType.CONSUME_FROM_TOPIC: 'ConsumeFromTopic'>, timestamp=datetime.datetime(2025, 5, 26, 18, 19, 10, 341430, tzinfo=datetime.timezone.utc), topic_name='agent_input_topic', offset=0, data=[Message(name=None, message_id='16e956e2e0424362b6362f6899bff798', timestamp=1748283550341049054, content='Generate mock user.', refusal=None, annotations=None, audio=None, role='user', tool_call_id=None, tools=None, function_call=None, tool_calls=None)], consumer_name='OpenAIInputNode', consumer_type='LLMNode')]
2025-05-26 19:19:11.840 | INFO     | grafi.common.topics.topic:publish_data:76 - [function_call_topic] Message published with event_id: b1ee77395c3e449193d1a2175133bf98
User Form Details:
First Name: John
Last Name: Doe
Location: New York, USA
Gender: Male

2025-05-26 19:19:11.841 | INFO     | grafi.common.topics.output_topic:publish_data:80 - [agent_output_topic] Message published with event_id: 7398d115a1fb4a4c9e2b14a4dcf6a114
[Message(name=None, message_id='5bc27a0909b146049e0d5ce5c66e068f', timestamp=1748283551841195922, content='["{\\n  \\"first_name\\": \\"John\\",\\n  \\"last_name\\": \\"Doe\\",\\n  \\"location\\": \\"New York, USA\\",\\n  \\"gender\\": \\"Male\\"\\n}"]', refusal=None, annotations=None, audio=None, role='function', tool_call_id=None, tools=None, function_call=None, tool_calls=None)]
```

---

## Summary

✅ Initialized a Poetry project
✅ Installed `grafi` with the correct Python version constraint
✅ Wrote a minimal agent that handles an event
✅ Ran the agent using a test event

---

## Next Steps

* Explore the [Graphite GitHub Repository](https://github.com/binome-dev/graphite) for full-featured examples.
* Extend your agent to respond to different event types.
* Dive into advanced features like memory, workflows, and tools.

---

Happy building! 🚀
