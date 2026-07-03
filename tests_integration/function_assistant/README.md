# function_assistant

Integration tests for a minimal LLM-plus-function-call assistant: an OpenAI node produces a structured form, a function node consumes it, exercised both from a live build and from a serialized manifest.

## Assistants

### `simple_function_llm_assistant.py` — `SimpleFunctionLLMAssistant`

An `Assistant` whose workflow chains an OpenAI LLM node (emitting a structured `output_format`) into a function-call node that runs a user-supplied `function`.

Topology:

```
(agent_input_topic) [input]
    --> [OpenAIInputNode: OpenAITool]
    --> (function_call_topic)
    --> [FunctionCallNode: FunctionTool]
    --> (agent_output_topic) [output]
```

## Examples

- `simple_function_llm_assistant_example.py` — Builds the assistant with a `UserForm` output format and a `print_user_form` function, invokes it with "Generate mock user", and asserts the output contains `first_name`/`last_name` and that exactly 18 events were recorded.
- `simple_function_assistant_deserialize_assistant_example.py` — Deserializes the assistant from `SimpleFunctionLLMAssistant_manifest.json` via `Assistant.from_dict()`, invokes it the same way, and asserts the same structured output and 18-event count (imports the example above to resolve the stored `print_user_form` reference; reads the OpenAI key from the environment since the manifest masks it).

## Runner

- `run_function_assistant.py` — Discovers every `*_example.py` in this directory and runs each as a subprocess, skipping any whose name contains `ollama` or `_local`, and prints a pass/fail summary.

## Manifest

- `SimpleFunctionLLMAssistant_manifest.json` — Serialized `SimpleFunctionLLMAssistant` manifest consumed by `simple_function_assistant_deserialize_assistant_example.py`.
