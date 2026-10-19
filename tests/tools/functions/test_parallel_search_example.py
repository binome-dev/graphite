"""Exercise the runnable example through Graphite and an in-process MCP server."""

import uuid

import fastmcp
import pytest

from grafi.tools.functions.impl import mcp_function_tool
from tests_integration.mcp_assistant import parallel_search_example as example


@pytest.mark.asyncio
async def test_search_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    server = fastmcp.FastMCP("Search fixture")
    calls = []
    configs = []

    @server.tool()
    def web_search(objective: str, search_queries: list[str], session_id: str) -> str:
        calls.append((objective, search_queries, session_id))
        return "Python TaskGroup: https://docs.python.org/3/library/asyncio-task.html"

    def client(config: dict) -> fastmcp.Client:
        configs.append(config)
        return fastmcp.Client(server)

    monkeypatch.setattr(mcp_function_tool, "Client", client)
    results = await example.search(
        "Find TaskGroup docs", ["Python TaskGroup documentation"]
    )

    assert len(results) == 1
    assert "https://docs.python.org/3/library/asyncio-task.html" in results[0]
    assert len(calls) == 1
    assert calls[0][:2] == ("Find TaskGroup docs", ["Python TaskGroup documentation"])
    assert uuid.UUID(calls[0][2]).version == 4
    # Discovery and invocation both receive the same explicit anonymous config.
    assert configs == [example.PARALLEL_MCP_CONFIG, example.PARALLEL_MCP_CONFIG]
    assert example.PARALLEL_MCP_CONFIG["mcpServers"]["parallel"] == {
        "transport": "http",
        "url": "https://search.parallel.ai/mcp",
        "headers": {"User-Agent": "graphite-parallel-search-example"},
    }
