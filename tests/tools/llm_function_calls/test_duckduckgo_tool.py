import json
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from grafi.common.manifest import ManifestError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.duckduckgo_tool import DuckDuckGoTool
from grafi.tools.tool import Tool


@pytest.fixture
def duckduckgo_tool() -> DuckDuckGoTool:
    return DuckDuckGoTool.builder().build()


@pytest.fixture
def mock_ddgs():
    with patch("grafi.tools.function_calls.impl.duckduckgo_tool.DDGS") as mock:
        mock_instance = Mock()
        mock.return_value = mock_instance
        mock_instance.text.return_value = [
            {"title": "Test Result", "link": "http://test.com"}
        ]
        yield mock_instance


def test_duckduckgo_tool_initialization(duckduckgo_tool: DuckDuckGoTool):
    assert duckduckgo_tool.name == "DuckDuckGoTool"
    assert duckduckgo_tool.type == "DuckDuckGoTool"
    assert duckduckgo_tool.fixed_max_results is None
    assert duckduckgo_tool.timeout == 10


def test_web_search_using_duckduckgo(duckduckgo_tool, mock_ddgs):
    query = "test query"
    max_results = 3

    result = duckduckgo_tool.web_search_using_duckduckgo(
        query=query, max_results=max_results
    )

    mock_ddgs.text.assert_called_once_with(keywords=query, max_results=max_results)
    assert isinstance(result, str)
    assert json.loads(result) == [{"title": "Test Result", "link": "http://test.com"}]


@pytest.mark.asyncio
async def test_invoke_function(duckduckgo_tool, mock_ddgs):
    invoke_context = InvokeContext(
        conversation_id="test_conv",
        invoke_id="test_invoke_id",
        assistant_request_id="test_req",
    )
    input_message = [
        Message(
            role="user",
            content="Search for Python",
            tool_calls=[
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {
                        "name": "web_search_using_duckduckgo",
                        "arguments": '{"query": "Python programming"}',
                    },
                }
            ],
        )
    ]

    result = []

    msg = await duckduckgo_tool.invoke(invoke_context, input_message)
    result.extend(msg)

    assert isinstance(result[0], Message)
    assert result[0].role == "tool"
    assert json.loads(result[0].content) == [
        {"title": "Test Result", "link": "http://test.com"}
    ]


def test_builder_configuration():
    tool = (
        DuckDuckGoTool.builder()
        .fixed_max_results(5)
        .headers({"User-Agent": "test"})
        .proxy("http://proxy.test")
        .build()
    )

    assert tool.fixed_max_results == 5
    assert tool.headers == {"User-Agent": "test"}
    assert tool.proxy == "http://proxy.test"


@pytest.mark.asyncio
async def test_invoke_with_invalid_function_name(duckduckgo_tool):
    invoke_context = InvokeContext(
        conversation_id="test_conv",
        invoke_id="test_invoke_id",
        assistant_request_id="test_req",
    )
    input_message = [
        Message(
            role="user",
            content="Search for Python",
            tool_calls=[
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {
                        "name": "invalid_function",
                        "arguments": '{"query": "Python programming"}',
                    },
                }
            ],
        )
    ]

    result = []

    msg = await duckduckgo_tool.invoke(invoke_context, input_message)
    result.extend(msg)
    [answer] = result  # The error, for the LLM.
    assert answer.content.startswith("Error: LookupError")


@pytest.mark.asyncio
async def test_error_handling(duckduckgo_tool):
    with patch("grafi.tools.function_calls.impl.duckduckgo_tool.DDGS") as mock:
        mock_instance = Mock()
        mock.return_value = mock_instance
        mock_instance.text.side_effect = Exception("Search failed")

        invoke_context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )
        input_message = [
            Message(
                role="user",
                content="Search for Python",
                tool_calls=[
                    {
                        "id": "test_id",
                        "type": "function",
                        "function": {
                            "name": "web_search_using_duckduckgo",
                            "arguments": '{"query": "Python programming"}',
                        },
                    }
                ],
            )
        ]

        from grafi.common.exceptions import FunctionCallException

        duckduckgo_tool.on_error = "raise"
        with pytest.raises(FunctionCallException) as excinfo:
            msg = await duckduckgo_tool.invoke(invoke_context, input_message)
            assert msg  # should not reach here
        assert "Search failed" in str(excinfo.value)


DUCKDUCKGO_TOOL = "grafi.tools.function_calls.impl.duckduckgo_tool:DuckDuckGoTool"


def test_load_from_a_manifest_naming_the_class():
    data = {
        "class": DUCKDUCKGO_TOOL,
        "tool_id": "test-id",
        "name": "TestDuckDuckGoTool",
        "oi_span_type": "TOOL",
        "fixed_max_results": 5,
        "headers": {"User-Agent": "test"},
        "proxy": "http://proxy.test",
        "timeout": 15,
    }

    tool = Tool.model_validate(data)

    assert isinstance(tool, DuckDuckGoTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "TestDuckDuckGoTool"
    assert tool.fixed_max_results == 5
    assert tool.headers == {"User-Agent": "test"}
    assert tool.proxy == "http://proxy.test"
    assert tool.timeout == 15
    # Its search function is the class's, not saved, so loaded with it.
    assert tool._functions() == {
        "web_search_using_duckduckgo": DuckDuckGoTool.web_search_using_duckduckgo
    }
    assert [spec.name for spec in tool.get_function_specs()] == [
        "web_search_using_duckduckgo"
    ]


def test_round_trip():
    original = (
        DuckDuckGoTool.builder()
        .name("TestDDG")
        .fixed_max_results(3)
        .headers({"User-Agent": "test"})
        .proxy("http://proxy.test")
        .timeout(20)
        .build()
    )
    data = original.model_dump(mode="json")
    assert data["class"] == DUCKDUCKGO_TOOL
    assert data["functions"] == {}
    # What it offers follows from its search method, so it is not saved.
    assert "function_specs" not in data  # Those it derives follow from it.

    restored = Tool.model_validate(data)

    assert type(restored) is DuckDuckGoTool
    assert restored.tool_id == original.tool_id
    assert restored.fixed_max_results == 3
    assert restored.headers == {"User-Agent": "test"}
    assert restored.proxy == "http://proxy.test"
    assert restored.timeout == 20
    assert restored._functions() == {
        "web_search_using_duckduckgo": DuckDuckGoTool.web_search_using_duckduckgo
    }
    assert restored.get_function_specs() == original.get_function_specs()
    assert [spec.name for spec in restored.get_function_specs()] == [
        "web_search_using_duckduckgo"
    ]
    assert restored == original
    assert restored.model_dump(mode="json") == data
    # Every field it saves is one it loads: a misspelt one is refused.
    with pytest.raises(ValidationError, match="max_result"):
        Tool.model_validate({**data, "max_result": 3})


def test_a_secret_header_set_to_a_value_is_never_saved():
    tool = DuckDuckGoTool(headers={"Authorization": "Bearer literal"})

    with pytest.raises(ManifestError, match="'Authorization'"):
        tool.to_manifest()
