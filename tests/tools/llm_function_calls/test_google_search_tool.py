import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.google_search_tool import GoogleSearchTool
from grafi.tools.tool import Tool


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def google_search_tool() -> GoogleSearchTool:
    """Default instance with no fixed settings."""
    return GoogleSearchTool.builder().build()


@pytest.fixture
def mock_search():
    """
    Patch the `googlesearch.search` generator so the test never hits the
    real network.  We yield a single fake SearchResult-like object that
    has the same public attrs (title/url/description).
    """
    with patch("grafi.tools.function_calls.impl.google_search_tool.search") as mock:

        class _FakeSearchResult:  # minimal stand-in for googlesearch.SearchResult
            def __init__(self, title, url, desc):
                self.title = title
                self.url = url
                self.description = desc

        mock.return_value = [
            _FakeSearchResult(
                title="Test Title", url="http://example.com", desc="Test Description"
            )
        ]
        yield mock


# --------------------------------------------------------------------------- #
#  Basic initialisation
# --------------------------------------------------------------------------- #
def test_google_search_tool_initialization(google_search_tool: GoogleSearchTool):
    assert google_search_tool.name == "GoogleSearchTool"
    assert google_search_tool.type == "GoogleSearchTool"
    assert google_search_tool.fixed_max_results is None
    assert google_search_tool.timeout == 10


# --------------------------------------------------------------------------- #
#  google_search() helper
# --------------------------------------------------------------------------- #
def test_google_search_function(google_search_tool, mock_search):
    query = "python unit testing"
    max_results = 3
    language = "en"

    result_json = google_search_tool.google_search(
        query=query, max_results=max_results, language=language
    )

    # Make sure the underlying search() function was invoked correctly
    mock_search.assert_called_once_with(
        query,
        num_results=max_results,
        lang=language,
        proxy=None,
        advanced=True,
    )

    assert isinstance(result_json, str)
    parsed = json.loads(result_json)
    assert parsed == [
        {
            "title": "Test Title",
            "url": "http://example.com",
            "description": "Test Description",
        }
    ]


# --------------------------------------------------------------------------- #
#  invoke() dispatcher
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_function(google_search_tool, mock_search):
    invoke_context = InvokeContext(
        conversation_id="test_conv",
        invoke_id="test_invoke_id",
        assistant_request_id="test_req",
    )
    input_messages = [
        Message(
            role="user",
            content="Search the web",
            tool_calls=[
                {
                    "id": "abc123",
                    "type": "function",
                    "function": {
                        "name": "google_search",
                        "arguments": json.dumps(
                            {"query": "python unit testing", "max_results": 1}
                        ),
                    },
                }
            ],
        )
    ]

    out = []

    async for msg in google_search_tool.invoke(invoke_context, input_messages):
        out.extend(msg)

    assert isinstance(out[0], Message)
    assert out[0].role == "tool"
    assert json.loads(out[0].content) == [
        {
            "title": "Test Title",
            "url": "http://example.com",
            "description": "Test Description",
        }
    ]


# --------------------------------------------------------------------------- #
#  Builder convenience helpers
# --------------------------------------------------------------------------- #
def test_builder_configuration():
    tool = (
        GoogleSearchTool.builder()
        .fixed_max_results(7)
        .proxy("http://proxy.local")
        .timeout(5)
        .build()
    )

    assert tool.fixed_max_results == 7
    assert tool.proxy == "http://proxy.local"
    assert tool.timeout == 5


# --------------------------------------------------------------------------- #
#  Invalid function name
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_with_invalid_function(google_search_tool):
    invoke_context = InvokeContext(
        conversation_id="test_conv",
        invoke_id="test_invoke_id",
        assistant_request_id="test_req",
    )
    bad_call_message = [
        Message(
            role="user",
            content="Do something",
            tool_calls=[
                {
                    "id": "bad",
                    "type": "function",
                    "function": {"name": "non_existent", "arguments": "{}"},
                }
            ],
        )
    ]

    result = []
    async for msg in google_search_tool.invoke(invoke_context, bad_call_message):
        result.extend(msg)
    [answer] = result  # The error, for the LLM.
    assert answer.content.startswith("Error: LookupError")


# --------------------------------------------------------------------------- #
#  Error path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_error_handling(google_search_tool):
    with patch("grafi.tools.function_calls.impl.google_search_tool.search") as mock:
        mock.side_effect = Exception("Search failed")

        invoke_context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )
        message_with_call = [
            Message(
                role="user",
                content="Search for errors",
                tool_calls=[
                    {
                        "id": "err",
                        "type": "function",
                        "function": {
                            "name": "google_search",
                            "arguments": '{"query": "Python"}',
                        },
                    }
                ],
            )
        ]

        from grafi.common.exceptions import FunctionCallException

        google_search_tool.on_error = "raise"
        with pytest.raises(FunctionCallException) as excinfo:
            async for msg in google_search_tool.invoke(
                invoke_context, message_with_call
            ):
                assert msg  # should not reach here
        assert "Search failed" in str(excinfo.value)


# --------------------------------------------------------------------------- #
#  Saving and loading
# --------------------------------------------------------------------------- #
GOOGLE_SEARCH_TOOL = (
    "grafi.tools.function_calls.impl.google_search_tool:GoogleSearchTool"
)


def test_load_from_a_manifest_naming_the_class():
    data = {
        "class": GOOGLE_SEARCH_TOOL,
        "tool_id": "test-id",
        "name": "TestGoogleSearchTool",
        "oi_span_type": "TOOL",
        "fixed_max_results": 5,
        "fixed_language": "en",
        "headers": {"User-Agent": "test"},
        "proxy": "http://proxy.test",
        "timeout": 15,
    }

    tool = Tool.model_validate(data)

    assert isinstance(tool, GoogleSearchTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "TestGoogleSearchTool"
    assert tool.fixed_max_results == 5
    assert tool.fixed_language == "en"
    assert tool.headers == {"User-Agent": "test"}
    assert tool.proxy == "http://proxy.test"
    assert tool.timeout == 15
    # Its search function is the class's, not saved, so loaded with it.
    assert tool.functions == {"google_search": GoogleSearchTool.google_search}
    assert [spec.name for spec in tool.function_specs] == ["google_search"]


def test_round_trip():
    original = (
        GoogleSearchTool.builder()
        .name("TestGoogle")
        .fixed_max_results(3)
        .fixed_language("en")
        .headers({"User-Agent": "test"})
        .proxy("http://proxy.test")
        .timeout(20)
        .build()
    )
    data = original.model_dump(mode="json")
    assert data["class"] == GOOGLE_SEARCH_TOOL
    assert data["functions"] == {}
    # What it offers follows from its search method, so it is not saved.
    assert "function_specs" not in data

    restored = Tool.model_validate(data)

    assert type(restored) is GoogleSearchTool
    assert restored.tool_id == original.tool_id
    assert restored.fixed_max_results == 3
    assert restored.fixed_language == "en"
    assert restored.headers == {"User-Agent": "test"}
    assert restored.proxy == "http://proxy.test"
    assert restored.timeout == 20
    assert restored.functions == {"google_search": GoogleSearchTool.google_search}
    assert restored.function_specs == original.function_specs
    assert [spec.name for spec in restored.function_specs] == ["google_search"]
    assert restored == original
    assert restored.model_dump(mode="json") == data
    # Every field it saves is one it loads: a misspelt one is refused.
    with pytest.raises(ValidationError, match="language"):
        Tool.model_validate({**data, "language": "fr"})
