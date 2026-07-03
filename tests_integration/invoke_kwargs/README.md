# invoke_kwargs

Integration bundle demonstrating how a Jinja `prompt_template` passed through `InvokeContext.kwargs` is propagated into an LLM node at invoke time to rewrite the user prompt before the model is called.

## Assistants

### `simple_llm_prompt_template_assistant.py` — `SimpleLLMPromptTemplateAssistant`

A single-node OpenAI assistant whose LLM node runs a custom `LLMPromptTemplateCommand` (instead of the default `LLMCommand`) so that a `prompt_template` from the invoke kwargs is applied to the incoming message.

Topology:

```
[input] (agent_input_topic) --> [OpenAINode: OpenAITool] --> (agent_output_topic) [output]
```

(The node's command is `LLMPromptTemplateCommand` wrapping `OpenAITool`; it renders the Jinja `prompt_template` from `invoke_context.kwargs` over the last message before dispatching to OpenAI.)

## Examples

- `simple_llm_prompt_template_assistant_example.py` — Builds `SimpleLLMPromptTemplateAssistant` and invokes it with an `InvokeContext` carrying a `prompt_template` kwarg (a sonnet-writing prompt with a `{{ input_text }}` placeholder). Verifies that the kwargs-supplied template is substituted with the input message content, that output is produced, and that exactly 12 events are recorded in the event store.

## Runner

- `run_invoke_kwargs.py` — Discovers and runs every `*_example.py` script in this directory as a subprocess, skips `ollama`/`_local` tests by default (`--no-pass-local` to include them), and prints a pass/fail summary (exit code 1 on any failure).

## Other

- `llm_prompt_template_command.py` — `LLMPromptTemplateCommand(LLMCommand)`, a custom command that overrides `get_tool_input`: if `invoke_context.kwargs["prompt_template"]` is present, it renders that string as a Jinja `Template` with `input_text` bound to the last message's content and returns the rendered prompt as a new user message (falling back to the original messages on render error).
