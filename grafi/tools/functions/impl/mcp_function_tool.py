import json
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import Optional
from typing import cast

from pydantic import Field
from pydantic import PrivateAttr

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.mcp_connections import Connection
from grafi.common.models.mcp_connections import MCPConfig
from grafi.common.models.mcp_connections import with_env
from grafi.common.models.message import Messages
from grafi.tools.function_calls.impl.mcp_tool import content_text
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.functions.function_tool import FunctionToolBuilder

try:
    from fastmcp import Client
except (ImportError, ModuleNotFoundError):
    raise ImportError("`fastmcp` not installed. Please install using `uv add fastmcp`")

try:
    from mcp.types import CallToolResult
    from mcp.types import Tool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `uv add mcp`")


class MCPFunctionTool(FunctionTool):
    """A tool that calls one tool of an MCP server, with the arguments the last
    message holds, as JSON.

    Building one (``await MCPFunctionTool.builder()...build()``) checks the
    server has the tool, and, when no ``function_name`` is given, takes its
    first. It is saved with its server and tool, so loading one does not
    connect. A secret in ``mcp_config`` is given as a reference to an
    environment variable, ``"${VAR}"`` (see
    :mod:`grafi.common.models.mcp_connections`).
    """

    name: str = "MCPFunctionTool"
    type: str = "MCPFunctionTool"

    mcp_config: MCPConfig = Field(default_factory=dict)

    # Always invoke_mcp_function, so never saved.
    function: Optional[Callable[[Messages], Awaitable[str]]] = Field(  # type: ignore[assignment]
        default=None, exclude=True, repr=False
    )

    function_name: str = Field(default="")

    _function_spec: Optional[FunctionSpec] = PrivateAttr(default=None)

    def model_post_init(self, _context: Any) -> None:
        self.function = self.invoke_mcp_function

    @classmethod
    async def initialize(cls, **kwargs: Any) -> "MCPFunctionTool":
        """
        Initialize the MCPFunctionTool with the given keyword arguments.
        """
        mcp_tool = cls(**kwargs)
        await mcp_tool._get_function_spec()

        return mcp_tool

    @classmethod
    def builder(cls) -> "MCPFunctionToolBuilder":
        """
        Return a builder for MCPFunctionTool.
        """
        return MCPFunctionToolBuilder(cls)

    async def _get_function_spec(self) -> None:
        if not self.mcp_config:
            raise ValueError("mcp_config are not set.")

        all_tools: list[Tool] = []

        async with Client(with_env(self.mcp_config)) as client:
            all_tools.extend(await client.list_tools())

        matching_tools = [
            tool
            for tool in all_tools
            if not self.function_name or tool.name == self.function_name
        ]

        if not matching_tools:
            raise ValueError(
                f"Tool '{self.function_name}' not found in available MCP tools."
                if self.function_name
                else "No tools available from MCP server."
            )

        tool = matching_tools[0]
        self.function_name = tool.name  # The one called, when none was named.
        self._function_spec = FunctionSpec.model_validate(
            {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            }
        )

    async def invoke_mcp_function(self, input_data: Messages) -> str:
        """Call the MCP tool with the arguments the last message holds, as
        JSON, and return its result as text."""
        kwargs = json.loads(cast(str, input_data[-1].content))
        async with Client(with_env(self.mcp_config)) as client:
            result: CallToolResult = await client.call_tool(self.function_name, kwargs)
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
