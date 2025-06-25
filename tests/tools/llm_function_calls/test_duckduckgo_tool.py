import json
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.duckduckgo_tool import DuckDuckGoTool


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


def test_invoke_function(duckduckgo_tool, mock_ddgs):
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

    result = duckduckgo_tool.invoke(invoke_context, input_message)

    print(result)

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


def test_invoke_with_invalid_function_name(duckduckgo_tool):
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

    result = duckduckgo_tool.invoke(invoke_context, input_message)
    assert len(result) == 0


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

        with pytest.raises(Exception) as excinfo:
            duckduckgo_tool.invoke(invoke_context, input_message)
        assert str(excinfo.value) == "Search failed"
