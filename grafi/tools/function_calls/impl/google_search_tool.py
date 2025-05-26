import json
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Self

from loguru import logger

from grafi.common.decorators.llm_function import llm_function
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


try:
    from googlesearch import SearchResult
    from googlesearch import search
except ImportError:
    raise ImportError(
        "`googlesearch-python` not installed. Please install using `pip install googlesearch-python`"
    )

try:
    from pycountry import pycountry
except ImportError:
    raise ImportError(
        "`pycountry` not installed. Please install using `pip install pycountry`"
    )


class GoogleSearchTool(FunctionCallTool):
    """
    Google Search extends FunctionCallTool to provide web search functionality using the Google Search API.
    """

    name: str = "GoogleSearchTool"
    type: str = "GoogleSearchTool"
    fixed_max_results: Optional[int] = None
    fixed_language: Optional[str] = None
    headers: Optional[Any] = None
    proxy: Optional[str] = None
    timeout: Optional[int] = 10

    class Builder(FunctionCallTool.Builder):
        """Concrete builder for GoogleSearchTool."""

        _tool: "GoogleSearchTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "GoogleSearchTool":
            return GoogleSearchTool.model_construct()

        def fixed_max_results(self, fixed_max_results: Optional[int]) -> Self:
            self._tool.fixed_max_results = fixed_max_results
            return self

        def fixed_language(self, fixed_language: Optional[str]) -> Self:
            self._tool.fixed_language = fixed_language
            return self

        def headers(self, headers: Optional[Any]) -> Self:
            self._tool.headers = headers
            return self

        def proxy(self, proxy: Optional[str]) -> Self:
            self._tool.proxy = proxy
            return self

        def timeout(self, timeout: Optional[int]) -> Self:
            self._tool.timeout = timeout
            return self

        def build(self) -> "GoogleSearchTool":
            return self._tool

    @llm_function
    def google_search(
        self, query: str, max_results: int = 5, language: str = "en"
    ) -> str:
        """
        Function to search online given a query using the Google Search API. The query can be anything.

        Args:
            query (str): The query to search for.
            max_results (int): The maximum number of results to return (default is 5).
            language (str): The language to use for the search (default is "en").

        Returns:
            str: A JSON string containing the search results.
        """
        max_results = self.fixed_max_results or max_results
        language = self.fixed_language or language

        # Resolve language to ISO 639-1 code if needed
        if len(language) != 2:
            _language = pycountry.languages.lookup(language)
            if _language:
                language = _language.alpha_2
            else:
                language = "en"

        logger.info(f"Searching Google [{language}] for: {query}")

        # Perform Google search using the googlesearch-python package
        results: List[SearchResult] = list(
            search(
                query,
                num_results=max_results,
                lang=language,
                proxy=self.proxy,
                advanced=True,
            )
        )

        # Collect the search results
        res: List[Dict[str, str]] = []
        for result in results:
            res.append(
                {
                    "title": result.title,
                    "url": result.url,
                    "description": result.description,
                }
            )

        return json.dumps(res, indent=2)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "fixed_max_results": self.fixed_max_results,
            "fixed_language": self.fixed_language,
            "headers": self.headers,
            "proxy": self.proxy,
            "timeout": self.timeout,
        }
