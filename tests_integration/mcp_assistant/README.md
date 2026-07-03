# mcp_assistant

Integration examples and tests for Graphite's Model Context Protocol (MCP) tool integrations, exercising `MCPTool` and `MCPFunctionTool` against a local MCP server over HTTP, stdio, and FastMCP transports, plus assistant manifest (de)serialization.

## Assistants

### `mcp_function_tool_local.py` — `MCPFunctionToolAssistant`

An `Assistant` that routes input straight through a single `MCPFunctionTool` node (no LLM), publishing the MCP tool's response to the output topic.

Topology:

```
[input] (agent_input_topic) --> [MCPFunctionNode: MCPFunctionTool] --> (agent_output_topic) [output]
```

Alongside the class, the file contains three example tests (all requiring the local `hello` MCP server on port 8000):

- `test_mcp_function_tool_direct_invocation` — builds an `MCPFunctionTool` bound to `function_name="hello"` over `StreamableHttpConnection` (`http://localhost:8000/mcp/`), invokes `mcp_tool.function([...])` directly with kwargs JSON (`{"name": "Graphite"}`), and asserts the response contains `Hello, Graphite!`.
- `test_mcp_function_tool_in_assistant` — wires the same tool into `MCPFunctionToolAssistant` and invokes via `PublishToTopicEvent`, asserting the output message content contains `Hello, Graphite!`.
- `test_mcp_function_tool_serialization_roundtrip` — round-trips the tool through `to_dict()` / `from_dict()` and re-invokes the restored tool to confirm it still calls the MCP server.

## Examples

- `mcp_deserialize_assistant_example_local.py` — Reconstructs an assistant entirely from `MCPAssistant_manifest.json` via `Assistant.from_dict` (after registering `MCPTool` with `ToolFactory.register_tool_class`), invokes it with "Hi my name is Graphite.", and asserts exactly 24 events were recorded. Needs the local MCP server referenced by the manifest.
- `simple_function_call_assistant_fastmcp_example_local.py` — Builds an inline `SimpleFunctionCallAssistant` (imported from `tests_integration/function_call_assistant/`) whose `function_tool` is an `MCPTool` over `StreamableHttpConnection` to `http://localhost:8000/mcp/`, sends a user message, and asserts 24 events. Requires the local FastMCP server (`hello_mcp_server.py`) running on port 8000. Inline shape: `[input] --> SimpleFunctionCallAssistant(OpenAI LLM + MCPTool[http]) --> [output]`.
- `simple_function_call_assistant_mcp_example_local.py` — Same assistant shape but the `MCPTool` connects over `StdioConnection`, spawning `npx -y @modelcontextprotocol/server-everything` as a subprocess; prompts the LLM to call the MCP `echo` tool and asserts 24 events. Requires `npx` and network access to fetch the "everything" MCP server (spawned locally). Inline shape: `[input] --> SimpleFunctionCallAssistant(OpenAI LLM + MCPTool[stdio]) --> [output]`.

## Runner

- `run_mcp_assistant.py` — Discovers `*_example.py` files in this directory and runs each as a subprocess, skipping any whose name contains `ollama` or `_local` unless `--no-pass-local` is passed; supports a `collect` mode returning structured per-script results instead of printing. Note: every example here is named `*_example_local.py` / `*_local.py`, so none match the `*_example.py` glob (and would be skipped as local regardless), meaning a default run currently collects zero scripts.

## Other

- `hello_mcp_server.py` — Standalone FastMCP test-fixture server exposing a single `hello(name) -> "Hello, {name}!"` tool over HTTP at `http://127.0.0.1:8000/mcp`. Start it first (`python tests_integration/mcp_assistant/hello_mcp_server.py`) to run the HTTP-based `_local` examples above.
