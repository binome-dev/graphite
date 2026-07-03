# agents

Integration example scripts that exercise the shared ReAct agent (`create_react_agent`) across sync, streaming-async, and MCP-tool runs, plus a runner that discovers and executes them.

## Assistants

No Assistant/Agent subclass is defined in this directory — every example imports the shared factory `create_react_agent` from [`grafi/agents/react_agent.py`](../../grafi/agents/react_agent.py). Its `ReActAgent._construct_workflow` builds a two-node reason→act loop:

```
(agent_input_topic) [input] ─┐
                             ├──> [OpenAIInputNode: OpenAITool] ──when=has_tool_call──────> (function_call_topic)
      (function_result_topic) ┘         │                                                          │
              ▲                          └──when=has_text_response──> (agent_output_topic) [output] │
              │                                                                                    │
              └──────────────────────── [Node: FunctionCallTool] <────────────────────────────────┘
```

The LLM node loops until it answers in text instead of calling a tool: a tool call routes to the function node, whose result feeds back into the LLM; a text response exits to the output topic.

## Examples

- `react_agent_example.py` — Builds a default agent with `create_react_agent()` and `await`s the single-result path `react_agent.run("What is agent framework called Graphite?")`, printing the one returned output. Exercises the awaitable, non-streaming run.
- `react_agent_async_example.py` — Builds a default agent with `create_react_agent()` and streams the async generator path `react_agent.a_run("What is agent framework called Graphite?")` via `async for`, printing each chunk. Exercises streaming async output.
- `react_agent_mcp_tools_async_example_local.py` — Builds an `MCPTool` from a `StdioConnection` that launches a local `npx @modelcontextprotocol/server-everything` MCP server, passes it as the agent's `function_call_tool`, then streams `react_agent.run("Please call mcp function 'echo' my name 'Graphite'?")`, printing `output.content`. Exercises MCP function-calling through the agent against a live local stdio server. (Local-only: skipped by the runner because of the `_local` suffix.)

## Runner

- `run_agents.py` — Discovers all `*_example.py` files in this directory and runs each as a subprocess, collecting pass/fail/skip results; by default skips files whose name contains `ollama` or `_local` (pass `--no-pass-local` to include them).
