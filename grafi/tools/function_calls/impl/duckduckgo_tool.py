import json
from typing import Any
from typing import Self

from grafi.common.decorators.llm_function import llm_function
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


try:
    from duckduckgo_search import DDGS
except ImportError:
    raise ImportError(
        "`duckduckgo-search` not installed. Please install using `pip install duckduckgo-search`"
    )


class DuckDuckGoTool(FunctionCallTool):
    """
    DuckDuckGoTool extends FunctionCallTool to provide web search functionality using the DuckDuckGo Search API.
    """

    # Set up API key and Tavily client
    name: str = "DuckDuckGoTool"
    type: str = "DuckDuckGoTool"
    fixed_max_results: int | None = None
    headers: dict[str, str] | None = None
    proxy: str | None = None
    timeout: int = 10

    class Builder(FunctionCallTool.Builder):
        """Concrete builder for DuckDuckGoTool."""

        _tool: "DuckDuckGoTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "DuckDuckGoTool":
            return DuckDuckGoTool.model_construct()

        def fixed_max_results(self, fixed_max_results: int) -> Self:
            self._tool.fixed_max_results = fixed_max_results
            return self

        def headers(self, headers: Any) -> Self:
            self._tool.headers = headers
            return self

        def proxy(self, proxy: str) -> Self:
            self._tool.proxy = proxy
            return self

        def timeout(self, timeout: int) -> Self:
            self._tool.timeout = timeout
            return self

        def build(self) -> "DuckDuckGoTool":
            return self._tool

    @llm_function
    def web_search_using_duckduckgo(self, query: str, max_results: int = 5) -> str:
        """
        Function to search online given a query using the Tavily API. The query can be anything.

        Args:
            query (str): The query to search for.
            max_results (int): The maximum number of results to return (default is 5).

        Returns:
            str: A JSON string containing the search results.
        """
        ddgs = DDGS(
            headers=self.headers,
            proxy=self.proxy,
            timeout=self.timeout,
        )

        return json.dumps(
            ddgs.text(
                keywords=query, max_results=(self.fixed_max_results or max_results)
            ),
            indent=2,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "fixed_max_results": self.fixed_max_results,
            "headers": self.headers,
            "proxy": self.proxy,
            "timeout": self.timeout,
        }
