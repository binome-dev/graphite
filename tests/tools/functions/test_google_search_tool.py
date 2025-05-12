import json
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.functions.impl.google_search_tool import GoogleSearchTool


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def google_search_tool() -> GoogleSearchTool:
    """Default instance with no fixed settings."""
    return GoogleSearchTool.Builder().build()


@pytest.fixture
def mock_search():
    """
    Patch the `googlesearch.search` generator so the test never hits the
    real network.  We yield a single fake SearchResult-like object that
    has the same public attrs (title/url/description).
    """
    with patch("grafi.tools.functions.impl.google_search_tool.search") as mock:

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
#  execute() dispatcher
# --------------------------------------------------------------------------- #
def test_execute_function(google_search_tool, mock_search):
    execution_context = ExecutionContext(
        conversation_id="test_conv",
        execution_id="test_execution_id",
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

    out = google_search_tool.execute(execution_context, input_messages)

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
        GoogleSearchTool.Builder()
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
def test_execute_with_invalid_function(google_search_tool):
    execution_context = ExecutionContext(
        conversation_id="test_conv",
        execution_id="test_execution_id",
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

    # FunctionTool.execute() should ignore unknown tools → empty reply list
    result = google_search_tool.execute(execution_context, bad_call_message)
    assert result == []


# --------------------------------------------------------------------------- #
#  Error path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_error_handling(google_search_tool):
    with patch("grafi.tools.functions.impl.google_search_tool.search") as mock:
        mock.side_effect = Exception("Search failed")

        execution_context = ExecutionContext(
            conversation_id="test_conv",
            execution_id="test_execution_id",
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

        with pytest.raises(Exception) as excinfo:
            google_search_tool.execute(execution_context, message_with_call)
        assert str(excinfo.value) == "Search failed"
