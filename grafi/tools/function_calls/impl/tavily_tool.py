import json
from typing import Any
from typing import Dict
from typing import Literal
from typing import Self

from grafi.common.decorators.llm_function import llm_function
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.function_call_tool import FunctionCallToolBuilder


try:
    from tavily import TavilyClient
except ImportError:
    raise ImportError(
        "`tavily` not installed. Please install using `pip install tavily-python`"
    )


class TavilyTool(FunctionCallTool):
    """
    TavilyTools extends FunctionCallTool to provide web search functionality using the Tavily API.
    """

    # Set up API key and Tavily client
    name: str = "TavilyTool"
    type: str = "TavilyTool"
    client: TavilyClient
    search_depth: Literal["basic", "advanced"] = "advanced"
    max_tokens: int = 6000

    @classmethod
    def builder(cls) -> "TavilyToolBuilder":
        """
        Return a builder for TavilyTool.
        This method allows for the construction of a TavilyTool instance with specified parameters.
        """
        return TavilyToolBuilder(cls)

    @llm_function
    def web_search_using_tavily(self, query: str, max_results: int = 5) -> str:
        """
        Function to search online given a query using the Tavily API. The query can be anything.

        Args:
            query (str): The query to search for.
            max_results (int): The maximum number of results to return (default is 5).

        Returns:
            str: A JSON string containing the search results.
        """
        response = self.client.search(
            query=query, search_depth=self.search_depth, max_results=max_results
        )

        clean_response: Dict[str, Any] = {"query": query}
        if "answer" in response:
            clean_response["answer"] = response["answer"]

        clean_results = []
        current_token_count = len(json.dumps(clean_response))
        for result in response.get("results", []):
            _result = {
                "title": result["title"],
                "url": result["url"],
                "content": result["content"],
                "score": result["score"],
            }
            current_token_count += len(json.dumps(_result))
            if current_token_count > self.max_tokens:
                break
            clean_results.append(_result)
        clean_response["results"] = clean_results

        return json.dumps(clean_response) if clean_response else "No results found."

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "api_key": "****************",
            "search_depth": self.search_depth,
            "max_tokens": self.max_tokens,
        }


class TavilyToolBuilder(FunctionCallToolBuilder[TavilyTool]):
    """Builder for TavilyTool instances."""

    def api_key(self, api_key: str) -> Self:
        from tavily import TavilyClient

        self.kwargs["client"] = TavilyClient(api_key)
        return self

    def search_depth(self, search_depth: Literal["basic", "advanced"]) -> Self:
        self.kwargs["search_depth"] = search_depth
        return self

    def max_tokens(self, max_tokens: int) -> Self:
        self.kwargs["max_tokens"] = max_tokens
        return self
