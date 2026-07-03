# rag_assistant

Integration tests for a single-node retrieval-augmented-generation assistant that answers questions using a `RagTool` backed by a llama-index vector store built from local documents.

## Assistants

### `simple_rag_assistant.py` — `SimpleRagAssistant`

An OpenAI-backed assistant whose `EventDrivenWorkflow` wires one `RagNode` (wrapping `RagTool` over a llama-index `BaseIndex`) directly between the input and output topics.

Topology:

```
[input] (agent_input_topic) --> [RagNode: RagTool] --> (agent_output_topic) [output]
```

## Examples

- `simple_rag_assistant_example.py` — Builds/loads a llama-index `VectorStoreIndex` from `data/`, invokes `SimpleRagAssistant` with "What is AWS EC2?", and collects the response via `async_func_wrapper(..., is_sequential=True)` (async run driven by `asyncio.run`, results gathered into a list); asserts the answer contains "EC2" and "computing" and that the event store holds 12 events, then deletes the `storage/` persist dir.
- `simple_rag_assistant_async_example.py` — Same index setup and query, but streams results with `async for output in ... .invoke(...)` (fully async iteration under `asyncio.run`); asserts each streamed output contains "EC2" and "computing" and that the event store holds 12 events, then deletes the `storage/` persist dir.

## Runner

- `run_rag_assistant.py` — Discovers and runs every `*_example.py` script in this directory as subprocesses (skipping `ollama`/`_local` tests unless `--no-pass-local`), then prints a pass/fail summary and exits non-zero on any failure.
