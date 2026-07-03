# react_assistant

Integration tests for the ReAct (reason + act) agent, a multi-node LLM loop (thought -> action -> search tool -> observation -> summary) exercised through basic, async, deserialize-from-manifest, event-recovery, and stop-workflow example scripts.

## Assistants

### `react_assistant.py` — `ReActAssistant`

An `EventDrivenWorkflow`-based agent implementing the ReAct pattern: a thought/action/observation reasoning loop backed by a pluggable search `FunctionCallTool`, terminating in a summary LLM node.

Topology:

```
(agent_input_topic) [input]
        |
        v
[ThoughtNode: OpenAITool] <-----------------------------------.
        |          ^                                           |
        |          '--- (also subscribes agent_input_topic)    |
        v                                                       |
(thought_result)                                               |
        |                                                       |
        v                                                       |
[ActionNode: OpenAITool]                                        |
        |                                                       |
        |--when=has_tool_call--> (action_search_result)         |
        |                               |                       |
        |                               v                       |
        |                   [SearchNode: FunctionCallTool]       |
        |                               |                       |
        |                               v                       |
        |                     (search_function_result)          |
        |                               |                       |
        |                               v                       |
        |                   [ObservationNode: OpenAITool]        |
        |                               |                       |
        |                               v                       |
        |                       (observation_result) -----------'
        |
        |--when=has_text_response--> (action_finish_result)
                                            |
                                            v
                                  [SummariesNode: OpenAITool]
                                            |
                                            v
                                   (agent_output_topic) [output]
```

`ThoughtNode` subscribes to `agent_input_topic` OR `observation_result`, so a fresh question and a looped-back observation both re-enter the reasoning loop at the thought stage.

## Examples

- `react_assistant_example.py` — Basic run: builds the assistant with a `TavilyTool` search tool, invokes it once via `async_func_wrapper(..., is_sequential=True)`, and asserts a non-null output plus the recorded event count.
- `react_assistant_async_example.py` — Async streaming run: invokes the assistant and iterates outputs with `async for`, printing each chunk and the total event count.
- `react_assistant_deserialize_assistant_example.py` — Deserialize-from-manifest: loads `ReActAssistant_manifest.json`, registers `TavilyTool` with `ToolFactory`, rebuilds the assistant via `Assistant.from_dict`, prints workflow/node counts, then invokes it to confirm the reconstructed agent runs.
- `react_assistant_recovery_example.py` — Event recovery/resume: loads pre-recorded unfinished events from `react_events_unfinished.json` into the event store, reuses their `invoke_context`, and re-invokes the assistant so the workflow resumes from where it was interrupted.
- `react_assistant_stop_workflow_example.py` — Stop-workflow mid-run (sync): starts a background `threading.Thread` that calls `assistant.stop_workflow()` after 4 seconds while the invoke is in flight.
- `react_assistant_async_stop_workflow_example.py` — Stop-workflow mid-run (async): uses `asyncio.gather` to run the invoke concurrently with a coroutine that calls `assistant.stop_workflow()` after 5 seconds.

Supporting data files: `ReActAssistant_manifest.json` is the serialized assistant manifest consumed by the deserialize example; `react_events_unfinished.json` holds the pre-recorded interrupted events replayed by the recovery example.

## Runner

- `run_react_assistant.py` — Discovers and runs every `*_example.py` script in this directory as a subprocess (skipping `ollama`/`_local` tests unless `--no-pass-local`), then prints a pass/fail summary and exits non-zero on any failure.
