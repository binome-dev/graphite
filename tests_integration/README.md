# tests_integration

End-to-end examples that run real Graphite assistants against live services
(OpenAI and other LLM providers, vector stores, MCP servers, Postgres). Unlike
the unit tests in `tests/`, these exercise whole workflows through real model
calls, so they run in CI only on `main` with provider API keys in the
environment.

Each subdirectory has its own `README.md` describing every file: assistant
definitions are documented with an ASCII **topology graph** (topics and nodes,
with `--when=...-->` content routes and `--from_stage=...-->` HITL pause
channels), and example scripts are documented by **what they test**. Every
directory has a `run_*.py` runner that executes its `*_example.py` scripts as
subprocesses and prints a pass/fail summary (local/ollama scripts are skipped by
default; pass `--no-pass-local` to include them).

## Directories

### Core workflow patterns
| Directory | Demonstrates |
| --- | --- |
| [`simple_llm_assistant/`](simple_llm_assistant/) | Single LLM node across every provider (OpenAI, Claude, Deepseek, Gemini, OpenRouter, Ollama), plus invocation-pattern and parallel-vs-sequential concurrency-isolation checks. |
| [`simple_stream_assistant/`](simple_stream_assistant/) | Token-by-token streaming output, with and without a function-call step. |
| [`function_assistant/`](function_assistant/) | Minimal LLM → function-tool pipeline that turns a prompt into a structured form. |
| [`function_call_assistant/`](function_call_assistant/) | The tool-calling loop (LLM decides → function node runs → LLM summarizes) across all providers, with manifest (de)serialization and concurrency variants. |
| [`input_output_topics/`](input_output_topics/) | Content-based multi-input/multi-output routing: a router node fans messages to different downstream paths via `publish_to(..., when=...)`. |
| [`agents/`](agents/) | The shared `create_react_agent` factory exercised across sync, async-streaming, and MCP-tool runs. |
| [`react_assistant/`](react_assistant/) | A full ReAct reasoning loop (thought → action → search tool → observation → summary), including event-recovery and stop-mid-run examples. |

### Human-in-the-loop and hooks
| Directory | Demonstrates |
| --- | --- |
| [`hith_assistant/`](hith_assistant/) | Human-in-the-loop pause/resume via paired in-workflow output/input topics (approval, KYC intake, generic HITL). |
| [`hooked_node_assistant/`](hooked_node_assistant/) | `HookedNode` use cases: a pre-execution approval gate with a policy hook chain, a post-generation editorial review gate, and a no-HITL PII-redaction + disclaimer guardrail chain (with a manifest round-trip). |

### Tools, retrieval, and multimodal
| Directory | Demonstrates |
| --- | --- |
| [`rag_assistant/`](rag_assistant/) | Retrieval-augmented generation through a `RagTool` over a llama-index vector store. |
| [`embedding_assistant/`](embedding_assistant/) | Retrieval from a persistent ChromaDB store using OpenAI embeddings. |
| [`multimodal_assistant/`](multimodal_assistant/) | Image input to an OpenAI vision model. |
| [`mcp_assistant/`](mcp_assistant/) | Model Context Protocol tool integrations (`MCPTool`/`MCPFunctionTool`) over HTTP, stdio, and FastMCP — requires a local MCP server. |
| [`invoke_kwargs/`](invoke_kwargs/) | Passing a Jinja `prompt_template` through `InvokeContext.kwargs` to rewrite the prompt at invoke time. |

### Infrastructure
| Directory | Demonstrates |
| --- | --- |
| [`event_store_postgres/`](event_store_postgres/) | Durable event persistence against a live PostgreSQL-backed `EventStorePostgres` across turns in one conversation. |
