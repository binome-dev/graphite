# event_store_postgres

Integration scripts that run a single-node OpenAI LLM assistant against a live PostgreSQL-backed `EventStorePostgres` to verify that workflow events are durably persisted and accumulate correctly across invokes in one conversation.

## Assistants

### `simple_llm_assistant.py` — `SimpleLLMAssistant`

A minimal `Assistant` that wires one OpenAI LLM node between an agent-input topic and an output topic, driven by an `EventDrivenWorkflow`; configurable via a builder (`api_key`, `system_message`, `model`, default `gpt-4o-mini`).

Topology:

```
(agent_input_topic)[entry]
        |
        v
[OpenAINode: OpenAITool]
        |
        v
(agent_output_topic)[terminal/output]
```

## Examples

- `simple_llm_assistant_postgres_integration.py` — Points a `SimpleLLMAssistant` at an `EventStorePostgres` (via `GrafiRuntime`/`bind_services`), calls `initialize()`, then runs two user turns in one `conversation_id`; asserts the model recalls the user's name and that `get_conversation_events` returns exactly 12 events after the first invoke and 24 after the second, confirming Postgres persistence and per-conversation event accumulation. (An embedded docstring documents the `docker compose` Postgres service it expects at `localhost:5432/grafi_test_db`.)

## Runner / Setup

- `run_event_store_postgres.py` — CLI runner that discovers and subprocess-executes every `*_example.py` in this directory, skipping `ollama`/`_local` scripts unless `--no-pass-local` is passed, and prints a pass/fail summary. (Note: the integration script here is named `*_integration.py`, not `*_example.py`, so it is not matched by this runner and must be run directly.)
