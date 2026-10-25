import json
from typing import Any
from typing import Callable
from typing import Dict
from typing import cast

from pydantic import Field

from grafi.common.models.mcp_connections import Connection
from grafi.common.models.message import Messages
from grafi.tools.function_calls.impl.mcp_tool import content_text
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.functions.function_tool import FunctionToolBuilder
from grafi.tools.mcp_config import MCPConnected

try:
    import fastmcp  # noqa: F401 - what connect() connects with.
except (ImportError, ModuleNotFoundError):
    raise ImportError("`fastmcp` not installed. Please install using `uv add fastmcp`")

try:
    import mcp  # noqa: F401
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `uv add mcp`")


class MCPFunctionTool(MCPConnected, FunctionTool):
    """A tool that calls one tool of an MCP server, with the arguments the last
    message holds, as JSON.

    Building one (``await MCPFunctionTool.builder()...build()``) checks the
    server has the tool, and, when no ``function_name`` is given, takes its
    first. It is saved with its server and tool, so loading one does not
    connect. A secret in ``mcp_config`` is given as a reference to an
    environment variable, ``"${VAR}"`` (see :mod:`grafi.tools.mcp_config`).
    """

    name: str = "MCPFunctionTool"
    type: str = "MCPFunctionTool"

    # None: it calls its server's tool, with invoke_mcp_function (see
    # _function()), so a function given it is refused.
    function: None = Field(  # type: ignore[assignment]
        default=None, exclude=True, repr=False
    )

    function_name: str = Field(default="")

    def _function(self) -> Callable[[Messages], Any]:
        return self.invoke_mcp_function

    @classmethod
    async def initialize(cls, **kwargs: Any) -> "MCPFunctionTool":
        """An MCPFunctionTool calling its server's tool ``function_name``,
        checked now, or its first."""
        wanted = kwargs.get("function_name") or ""

        async def listing(client: Any) -> Dict[str, Any]:
            tools = await client.list_tools()
            matching = [tool for tool in tools if not wanted or tool.name == wanted]
            if not matching:
                raise ValueError(
                    f"Tool '{wanted}' not found in available MCP tools."
                    if wanted
                    else "No tools available from MCP server."
                )
            return {"function_name": matching[0].name}

        return await cls._listed(kwargs, listing)

    @classmethod
    def builder(cls) -> "MCPFunctionToolBuilder":
        """
        Return a builder for MCPFunctionTool.
        """
        return MCPFunctionToolBuilder(cls)

    async def invoke_mcp_function(self, input_data: Messages) -> str:
        """Call the MCP tool with the arguments the last message holds, as
        JSON, and return its result as text."""
        kwargs = json.loads(cast(str, input_data[-1].content))
        async with self._connect() as client:
            result = await client.call_tool(self.function_name, kwargs)
        return content_text(result.content)


class MCPFunctionToolBuilder(FunctionToolBuilder[MCPFunctionTool]):
    """
    Builder for MCPFunctionTool.
    """

    def connections(
        self, connections: Dict[str, Connection]
    ) -> "MCPFunctionToolBuilder":
        self.kwargs["mcp_config"] = {
            "mcpServers": connections,
        }
        return self

    def function_name(self, function_name: str) -> "MCPFunctionToolBuilder":
        self.kwargs["function_name"] = function_name

        return self

    async def build(self) -> "MCPFunctionTool":
        mcp_tool = await self._cls.initialize(**self.kwargs)
        return mcp_tool
