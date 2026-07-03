# simple_llm_assistant

Integration tests and runnable examples for single-LLM-node assistants across every supported provider, plus per-provider tool round-trips and invocation-pattern / concurrency-isolation checks.

## Assistants

### `simple_llm_assistant.py` — `SimpleLLMAssistant`
A one-node assistant that pipes input straight through a single OpenAI LLM node to output (model defaults to `gpt-4o-mini`).

Topology:
```
[input] (agent_input_topic) --> [OpenAINode: OpenAITool] --> (agent_output_topic) [output]
```

### `simple_ollama_assistant.py` — `SimpleOllamaAssistant`
Same single-node shape as above but backed by a local Ollama server (`api_url` defaults to `http://localhost:11434`, model `qwen3`).

Topology:
```
[input] (agent_input_topic) --> [OllamaInputNode: OllamaTool] --> (agent_output_topic) [output]
```

### `simple_multi_llm_assistant.py` — `SimpleMultiLLMAssistant`
Fans one input out to four OpenRouter LLM nodes (OpenAI / DeepSeek / Gemini / Qwen), each feeding a per-provider `FunctionTool` node; all four converge on a paired in-workflow topic boundary (a human-in-the-loop hand-off) before a final function node emits to output.

Topology:
```
[input] (agent_input_topic)
   |
   |--> [OpenAIInputNode:   OpenRouterTool] --> (openai_function_call_topic)   --> [OpenAINode:   FunctionTool] --+
   |--> [DeepSeekInputNode: OpenRouterTool] --> (deepseek_function_call_topic) --> [DeepSeekNode: FunctionTool] --+
   |--> [GeminiInputNode:   OpenRouterTool] --> (gemini_function_call_topic)   --> [GeminiNode:   FunctionTool] --+
   |--> [QwenInputNode:     OpenRouterTool] --> (qwen_function_call_topic)     --> [QwenNode:     FunctionTool] --+
                                                                                                                 |
                                                                                                                 v
                                                                                             (in_workflow_output_topic)
                                                                                                     :  paired (human-in-the-loop boundary)
                                                                                             (in_workflow_input_topic)
                                                                                                                 |
                                                                                                                 v
                                             [HumanRequestProcessNode: FunctionTool] --> (agent_output_topic) [output]
```

## Examples

### Per-provider tool tests
Each of these drives one LLM tool directly (not through an assistant) and exercises the same matrix: async streaming, custom chat params, async one-shot, an end-to-end path through a bare `Node`, and a `to_dict` / `ToolFactory.from_dict` serialization round-trip.

- `openai_tool_example.py` — `OpenAITool` (needs `OPENAI_API_KEY`); also covers Pydantic structured-output (`response_format`).
- `claude_tool_example.py` — `ClaudeTool` / Anthropic (needs `ANTHROPIC_API_KEY`).
- `deepseek_tool_example.py` — `DeepseekTool` (needs `DEEPSEEK_API_KEY`).
- `gemini_tool_example.py` — `GeminiTool` (needs `GEMINI_API_KEY`).
- `openrouter_tool_example.py` — `OpenRouterTool` (needs `OPENROUTER_API_KEY`).

### Invocation-pattern tests
- `simple_llm_assistant_example.py` — drives `SimpleLLMAssistant` in sequential mode (`is_sequential=True`) collected via `async_func_wrapper`; asserts event counts (12, then 24).
- `simple_llm_assistant_async_example.py` — same assistant consumed as a streaming `async for` output.
- `simple_ollama_assistant_example.py` — `SimpleOllamaAssistant` sequential run; needs a local Ollama server.
- `simple_ollama_assistant_async_example.py` — `SimpleOllamaAssistant` streaming `async for` run; needs a local Ollama server.
- `simple_multi_llm_assistant_example_local.py` — end-to-end `SimpleMultiLLMAssistant` run with stub provider functions (asserts 57 events); named `_local` so the runner skips it (requires `OPENROUTER_API_KEY`).

### Concurrency tests
Both share one `SimpleLLMAssistant` instance configured as a word-echo service, fire several invokes at once with distinct words, and assert each response echoes its own word with no cross-talk (per-invocation runtime isolation). Require `OPENAI_API_KEY`.
- `concurrent_invocation_example.py` — concurrent parallel invokes (`is_sequential=False`).
- `concurrent_sequential_invocation_example.py` — concurrent invokes on the sequential engine (`is_sequential=True`).

## Runner
- `run_simple_llm_assistant.py` — discovers and runs every `*_example.py` as a subprocess, printing a pass/fail summary; by default skips any file whose name contains `ollama` or `_local` (pass `--no-pass-local` to include them).
