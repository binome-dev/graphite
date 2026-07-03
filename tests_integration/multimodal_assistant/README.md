# multimodal_assistant

Integration test demonstrating multimodal (image) input to an OpenAI LLM through a single-node Graphite assistant.

## Assistants

### `simple_llm_assistant.py` — `SimpleLLMAssistant`

An `Assistant` that wraps a single `OpenAITool` LLM node in an `EventDrivenWorkflow`, subscribing to the input topic and publishing responses to the output topic.

Topology:

```
[input] (agent_input_topic) --> [OpenAINode: OpenAITool] --> (agent_output_topic) [output]
```

## Examples

- `simple_llm_assistant_image_rec_example.py` — Loads `graphite_powered_by_binome.png`, base64-encodes it into an `image_url` message alongside the text prompt "what's in this image?", invokes `SimpleLLMAssistant`, and asserts the model's response contains "GRAPHITE" and that exactly 12 events were recorded in the event store.

## Runner

- `run_multimodal_assistant.py` — Discovers and runs every `*_example.py` script in this directory as a subprocess (skipping `ollama`/`_local` tests unless `--no-pass-local`), then prints a pass/fail summary and exits non-zero on any failure.
