import json
from unittest.mock import patch

import pytest
from pydantic_core import PydanticSerializationError
from tavily import TavilyClient

from grafi.common.event_stores import EventStoreInMemory
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool
from grafi.tools.tool import Tool


@pytest.fixture
def event_store():
    return EventStoreInMemory()


@pytest.fixture
def tavily_client():
    return TavilyClient(api_key="fake_api_key")


@pytest.fixture
def tavily_tool(tavily_client):
    tool = TavilyTool(name="TavilyTestTool", max_tokens=6000, search_depth="advanced")
    tool._client = tavily_client  # The client is made on first use otherwise.
    return tool


def test_tavily_tool_initialization(tavily_tool):
    assert tavily_tool.search_depth == "advanced"
    assert tavily_tool.max_tokens == 6000
    assert tavily_tool.client is not None


def test_function_registration(tavily_tool):
    assert callable(tavily_tool.functions["web_search_using_tavily"])
    assert "web_search_using_tavily" in tavily_tool.functions


def test_invoke_web_search_using_tavily(tavily_tool):
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


def test_invoke_with_exceeding_token_limit(tavily_tool):
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


def test_invoke_with_format_json(tavily_tool):
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


# --------------------------------------------------------------------------- #
#  The client is made on first use                                            #
# --------------------------------------------------------------------------- #
def test_the_client_is_made_on_first_use_with_the_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "env_key")
    tool = TavilyTool()
    assert "client" not in TavilyTool.model_fields
    assert tool._client is None

    with patch(f"{TavilyTool.__module__}.TavilyClient") as client_class:
        client = tool.client
        assert tool.client is client  # Made once.

    client_class.assert_called_once_with("env_key")
    assert client is client_class.return_value


# --------------------------------------------------------------------------- #
#  Saving and loading                                                          #
# --------------------------------------------------------------------------- #
TAVILY_TOOL = "grafi.tools.function_calls.impl.tavily_tool:TavilyTool"


@pytest.fixture
def saved_tavily(monkeypatch: pytest.MonkeyPatch) -> TavilyTool:
    """A TavilyTool with its key from TAVILY_API_KEY."""
    monkeypatch.setenv("TAVILY_API_KEY", "test_key")
    return (
        TavilyTool.builder()
        .name("TestTavily")
        .api_key("test_key")
        .search_depth("basic")
        .max_tokens(3000)
        .build()
    )


def test_dump_saves_the_key_as_its_variable_and_no_client(saved_tavily):
    saved_tavily.client  # A client made is not saved.

    data = saved_tavily.model_dump(mode="json")

    assert data["class"] == TAVILY_TOOL
    assert data["name"] == "TestTavily"
    assert data["api_key"] == {"env": "TAVILY_API_KEY"}
    assert data["search_depth"] == "basic"
    assert data["max_tokens"] == 3000
    assert data["functions"] == {}  # web_search_using_tavily loads with the class.
    assert "function_specs" not in data  # It follows from the functions.
    assert not {"client", "_client"} & data.keys()
    assert "test_key" not in json.dumps(data)
    # Nor does a python-mode dump hold the client.
    assert not {"client", "_client"} & saved_tavily.model_dump().keys()


def test_round_trip(saved_tavily):
    data = saved_tavily.model_dump(mode="json")

    restored = Tool.model_validate(data)

    assert type(restored) is TavilyTool
    assert restored.tool_id == saved_tavily.tool_id
    assert restored.api_key == "test_key"  # Read from TAVILY_API_KEY.
    assert restored.search_depth == "basic"
    assert restored.max_tokens == 3000
    assert restored._client is None  # Made on first use.
    assert restored.functions == {
        "web_search_using_tavily": TavilyTool.web_search_using_tavily
    }
    assert restored.function_specs == saved_tavily.function_specs
    assert restored == saved_tavily
    assert restored.model_dump(mode="json") == data


def test_load_from_a_manifest_naming_the_class(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test_key")
    data = {
        "class": TAVILY_TOOL,
        "tool_id": "test-id",
        "name": "TestTavily",
        "oi_span_type": "TOOL",
        "api_key": {"env": "TAVILY_API_KEY"},
        "search_depth": "advanced",
        "max_tokens": 6000,
    }

    tool = Tool.model_validate(data)

    assert isinstance(tool, TavilyTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "TestTavily"
    assert tool.api_key == "test_key"
    assert tool.search_depth == "advanced"
    assert tool.max_tokens == 6000


def test_a_key_not_from_its_variable_is_never_saved(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "the_env_key")
    tool = TavilyTool.builder().api_key("another_key").build()

    with pytest.raises(
        PydanticSerializationError, match="ManifestError: .*TavilyTool.api_key"
    ):
        tool.model_dump(mode="json")
