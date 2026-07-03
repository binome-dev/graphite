# function_call_assistant

Integration tests and runnable examples for Graphite assistants that follow the
tool-calling loop: an LLM node decides whether to call a tool, a function-call
node runs it, and a second LLM node summarizes the result. Covers every LLM
provider (OpenAI, Claude, Deepseek, Gemini, Ollama, OpenRouter), several
function tools (mocks, web search, synthetic, agent-calling), and cross-cutting
concerns (async/streaming, no-tool-call paths, manifest deserialization,
concurrency).

## Assistants

### `simple_function_call_assistant.py` — `SimpleFunctionCallAssistant`
Canonical 3-node OpenAI tool-calling loop; the input LLM routes to either the
function-call node (when it emits a tool call) or straight to output (when it
replies in text). Takes a single `function_tool`.

Topology:
```
[input]
  |
  v
(agent_input_topic)
  |
  v
[OpenAIInputNode: OpenAITool]
  |--when=has_tool_call-------> (function_call_topic)
  |--when=has_text_response---> (agent_output_topic) --> [output]

(function_call_topic)
  |
  v
[FunctionCallNode: FunctionCallTool]     # the injected function_tool
  |                                       (unconditional publish)
  v
(function_result_topic)
  |
  v
[OpenAIOutputNode: OpenAITool]
  |--when=has_text_response---> (agent_output_topic) --> [output]
```

### `multi_functions_call_assistant.py` — `MultiFunctionsCallAssistant`
Same loop, but fans out to one `FunctionCallNode` per tool in a
`function_tools` list; every function node subscribes to the shared
`function_call_topic` and publishes to the shared `function_result_topic`.

Topology:
```
[input]
  |
  v
(agent_input_topic)
  |
  v
[OpenAIInputNode: OpenAITool]
  |--when=has_tool_call-------> (function_call_topic)
  |--when=has_text_response---> (agent_output_topic) --> [output]

(function_call_topic)          # fan-out: one node per function tool
  |                    |                    |
  v                    v                    v
[Node_<t1>: FnTool] [Node_<t2>: FnTool] [Node_<tN>: FnTool]
  |                    |                    |
  +--when=has_text_response--> (function_result_topic)
                                   |
                                   v
                        [OpenAIOutputNode: OpenAITool]
                                   |--when=has_text_response--> (agent_output_topic) --> [output]
```

### Per-provider variants
All share the exact topology of `simple_function_call_assistant.py` (input LLM
node with `has_tool_call` / `has_text_response` routing → function-call node →
output LLM node), swapping only the LLM tool class:

- `simple_claude_function_call_assistant.py` — `SimpleClaudeFunctionCallAssistant`, using `ClaudeTool` (`ANTHROPIC_API_KEY`, `claude-haiku-4-5`).
- `simple_deepseek_function_call_assistant.py` — `SimpleDeepseekFunctionCallAssistant`, using `DeepseekTool` (`DEEPSEEK_API_KEY`, `deepseek-chat`).
- `simple_gemini_function_call_assistant.py` — `SimpleGeminiFunctionCallAssistant`, using `GeminiTool` (`GEMINI_API_KEY`, `gemini-3.5-flash`).
- `simple_ollama_function_call_assistant.py` — `SimpleOllamaFunctionCallAssistant`, using `OllamaTool`; configured with `api_url` (default `http://localhost:11434`, `qwen3`) instead of an API key — requires a **local Ollama server**.
- `simple_openrouter_function_call_assistant.py` — `SimpleOpenRouterFunctionCallAssistant`, using `OpenRouterTool` (`OPENROUTER_API_KEY`, `openai/gpt-4o-mini`).

## Examples

Each script builds an assistant, invokes it, and asserts on the response and the
recorded event count (24 for a full single-tool loop, 12 when no tool is called,
27 for Ollama, larger for multi-tool / multi-invoke runs).

### OpenAI — `SimpleFunctionCallAssistant`
- `simple_function_call_assistant_example.py` — baseline sync run with a `WeatherMock` tool; also asserts idempotent re-invoke (same `invoke_context` returns `[]`).
- `simple_function_call_assistant_async_example.py` — same tool via async streaming (`async for` over `invoke`), async `@llm_function`, `gpt-5-nano`.
- `simple_function_call_assistant_no_func_call_example.py` — off-topic prompt so the LLM answers in text with no tool call (12 events).
- `simple_function_call_assistant_no_func_call_async_example.py` — the no-tool-call path via async streaming.
- `simple_function_call_assistant_complex_function_example.py` — `LocalFileMock` tool with a multi-arg signature (`list[str]` + optional `root_path`); guarded by `__main__` so it can be imported to register the tool for manifest deserialization.
- `simple_function_call_assistant_multi_functions_example.py` — one `LocalInfoMock` tool exposing two `@llm_function`s (weather + population), exercised across two questions; also `__main__`-guarded for import/registration.

### Function tools (on `SimpleFunctionCallAssistant`)
- `simple_function_call_assistant_agent_example.py` — uses `AgentCallingTool` (delegates to a mocked sub-agent) as the tool, sync.
- `simple_function_call_assistant_agent_async_example.py` — same with an async `agent_call`, streaming.
- `simple_function_call_assistant_tavily_example.py` — real `TavilyTool` web search (`TAVILY_API_KEY`).
- `simple_function_call_assistant_google_search_example.py` — real `GoogleSearchTool` web search.
- `simple_function_call_assistant_synthetic_example.py` — `SyntheticTool` (LLM-backed) with Pydantic input/output schemas and a strict system prompt forcing tool use.
- `simple_function_call_assistant_duckduckgo_example_local.py` — `DuckDuckGoTool` search; `_local` in name so the runner skips it.

### Manifest deserialization
- `simple_function_call_assistant_deserialize_assistant_example.py` — rebuilds an assistant from `SimpleFunctionCallAssistant_manifest.json` via `Assistant.from_dict`, importing `LocalInfoMock` from the multi-functions example to register the custom tool class.
- `complex_function_call_assistant_deserialize_assistant_example.py` — rebuilds from `complex_function_manifest.json`, importing/registering `LocalFileMock` from the complex-function example.

### Concurrency
- `concurrent_function_call_invocation_example.py` — fires several concurrent `invoke`s (`is_sequential=False`, `asyncio.gather`) at one assistant with distinct postcodes; asserts each response references only its own request, proving per-invocation isolation.

### Per-provider examples
- `simple_claude_function_call_assistant_example.py` — Claude, sync `WeatherMock`.
- `simple_claude_function_call_assistant_async_example.py` — Claude, async streaming.
- `simple_deepseek_function_call_assistant_example.py` — Deepseek, streaming; also asserts idempotent re-invoke returns `[]`.
- `simple_gemini_function_call_assistant_example.py` — Gemini, sync (asserts a non-empty response, phrasing-independent).
- `simple_openrouter_function_call_assistant_example.py` — OpenRouter, sync; asserts idempotent re-invoke returns `[]`.
- `simple_ollama_function_call_assistant_example.py` — Ollama, sync (27 events); requires a **local Ollama server**, skipped by the runner.
- `simple_ollama_function_call_assistant_async_example.py` — Ollama, async streaming; requires a **local Ollama server**, skipped by the runner.

### Multi-function examples (`MultiFunctionsCallAssistant`)
- `multi_functions_call_assistant_example.py` — three tools (weather / population / house-price) across three sequential invokes (34 → 68 → 102 events).
- `multi_functions_call_assistant_async_example.py` — the same three-tool scenario via async streaming.

## Runner
- `run_function_call_assistant.py` — discovers every `*_example.py` in this directory and runs each as a subprocess, reporting pass/fail; by default skips scripts whose name contains `ollama` or `_local` (pass `--no-pass-local` to include them).
