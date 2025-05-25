from unittest.mock import patch

import pytest
from tavily import TavilyClient

from grafi.common.event_stores import EventStoreInMemory
from grafi.common.models.execution_context import ExecutionContext
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool


@pytest.fixture
def event_store():
    return EventStoreInMemory()


@pytest.fixture
def tavily_client():
    return TavilyClient(api_key="fake_api_key")


@pytest.fixture
def tavily_tool(tavily_client):
    execution_context = ExecutionContext(
        conversation_id="conversation_id",
        execution_id="execution_id",
        assistant_request_id="assistant_request_id",
    )
    return TavilyTool(
        name="TavilyTestTool",
        execution_context=execution_context,
        client=tavily_client,
        search=True,
        max_tokens=6000,
        search_depth="advanced",
        use_search_context=False,
    )


def test_tavily_tool_initialization(tavily_tool):
    assert tavily_tool.search_depth == "advanced"
    assert tavily_tool.max_tokens == 6000
    assert tavily_tool.client is not None


def test_function_registration(tavily_tool):
    assert callable(tavily_tool.functions["web_search_using_tavily"])
    assert "web_search_using_tavily" in tavily_tool.functions


def test_execute_web_search_using_tavily(tavily_tool):
    with patch.object(
        tavily_tool.client,
        "search",
        return_value={
            "results": [
                {
                    "title": "Result1",
                    "url": "http://example.com",
                    "content": "Content1",
                    "score": 90,
                }
            ]
        },
    ):
        result = tavily_tool.web_search_using_tavily(
            "Python programming", max_results=1
        )
        assert "Result1" in result


def test_execute_with_exceeding_token_limit(tavily_tool):
    with patch.object(
        tavily_tool.client,
        "search",
        return_value={
            "results": [
                {
                    "title": "Result1",
                    "url": "http://example.com",
                    "content": "Content1",
                    "score": 90,
                },
                {
                    "title": "Result2",
                    "url": "http://example.com",
                    "content": "Content2",
                    "score": 80,
                },
            ]
        },
    ):
        tavily_tool.max_tokens = 50  # Set a low token limit
        result = tavily_tool.web_search_using_tavily("Data Science", max_results=10)
        assert "Result2" not in result  # Result2 should be excluded due to token limit


def test_execute_with_format_json(tavily_tool):
    with patch.object(
        tavily_tool.client,
        "search",
        return_value={
            "results": [
                {
                    "title": "Result1",
                    "url": "http://example.com",
                    "content": "Content1",
                    "score": 90,
                }
            ]
        },
    ):
        result = tavily_tool.web_search_using_tavily("AI")
        assert isinstance(result, str) and result.startswith("{")  # JSON string
