"""A tool told to read a tenant's key never sends another account's: with the
tenant's variable unset, it raises rather than leave its SDK to read the SDK's
own variable, and it reads the tenant's once set."""

from typing import Any
from typing import Callable
from typing import Dict
from unittest.mock import Mock

import pytest

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.synthetic_tool import SyntheticTool
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool
from grafi.tools.llms.impl.claude_tool import ClaudeTool
from grafi.tools.llms.impl.ollama_tool import OllamaTool
from grafi.tools.tool import Tool


async def _invoke(tool: Tool, invoke_context: InvokeContext) -> Any:
    return await tool.invoke(invoke_context, [Message(role="user", content="Hi")])


async def _client(tool: Tool, invoke_context: InvokeContext) -> Any:
    return tool.client  # type: ignore[attr-defined]


async def _call_llm(tool: Tool, invoke_context: InvokeContext) -> Any:
    return await tool._call_llm("Hi")  # type: ignore[attr-defined]


CASES: Dict[str, Any] = {
    "claude": (
        ClaudeTool,
        "api_key",
        "ANTHROPIC_API_KEY",
        "grafi.tools.llms.impl.claude_tool.AsyncAnthropic",
        _invoke,
    ),
    "ollama": (
        OllamaTool,
        "api_key",
        "OLLAMA_API_KEY",
        "grafi.tools.llms.impl.ollama_tool.ollama.AsyncClient",
        _invoke,
    ),
    "tavily": (
        TavilyTool,
        "api_key",
        "TAVILY_API_KEY",
        "grafi.tools.function_calls.impl.tavily_tool.TavilyClient",
        _client,
    ),
    "synthetic": (
        SyntheticTool,
        "openai_api_key",
        "OPENAI_API_KEY",
        "grafi.tools.function_calls.impl.synthetic_tool.AsyncOpenAI",
        _call_llm,
    ),
}


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
@pytest.mark.asyncio
async def test_an_unset_tenant_key_is_never_replaced_by_the_sdks_own(
    monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext, case: Any
) -> None:
    tool_class, field, default_variable, sdk, use = case
    use: Callable[[Tool, InvokeContext], Any]
    monkeypatch.delenv("TENANT_KEY", raising=False)
    monkeypatch.setenv(default_variable, "the-default-account")
    sdk_client = Mock()
    monkeypatch.setattr(sdk, sdk_client)
    data = {field: {"env": "TENANT_KEY"}}
    if tool_class is SyntheticTool:
        data["output_model"] = {"type": "object", "properties": {}}
    tool = tool_class.model_validate(data)

    with pytest.raises(Exception, match="set TENANT_KEY"):
        await use(tool, invoke_context)
    sdk_client.assert_not_called()

    monkeypatch.setenv("TENANT_KEY", "the-tenants")
    try:
        await use(tool, invoke_context)
    except Exception:
        pass  # The mocked SDK answers nothing a tool can use.
    assert "the-tenants" in str(sdk_client.call_args)  # Ollama's, in a header.


@pytest.mark.asyncio
async def test_claude_without_its_own_key_lets_its_sdk_use_anthropics_token(
    monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext
) -> None:
    """Behind a gateway, ANTHROPIC_AUTH_TOKEN authenticates, not a key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-token")
    sdk_client = Mock()
    monkeypatch.setattr("grafi.tools.llms.impl.claude_tool.AsyncAnthropic", sdk_client)

    try:
        await _invoke(ClaudeTool(), invoke_context)
    except Exception:
        pass  # The mocked SDK answers nothing a tool can use.

    sdk_client.assert_called_once_with(api_key=None)
