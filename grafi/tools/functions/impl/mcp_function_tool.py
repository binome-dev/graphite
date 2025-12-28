import json
from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import Dict

from loguru import logger
from pydantic import Field
from pydantic import PrivateAttr

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.mcp_connections import Connection
from grafi.common.models.message import Messages
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.functions.function_tool import FunctionToolBuilder


try:
    from fastmcp import Client
except (ImportError, ModuleNotFoundError):
    raise ImportError("`fastmcp` not installed. Please install using `uv add fastmcp`")

try:
    from mcp.types import CallToolResult
    from mcp.types import EmbeddedResource
    from mcp.types import ImageContent
    from mcp.types import TextContent
    from mcp.types import Tool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `uv add mcp`")


class MCPFunctionTool(FunctionTool):
    """
    MCPFunctionTool extends FunctionTool to provide functionality using the MCP API.
    """

    # Class attributes for MCPFunctionTool configuration and behavior
    name: str = "MCPFunctionTool"
    type: str = "MCPFunctionTool"

    mcp_config: Dict[str, Any] = Field(default_factory=dict)

    function: Callable[[Messages], AsyncGenerator[Messages, None]] = Field(default=None)

    function_name: str = Field(default="")

    _function_spec: FunctionSpec = PrivateAttr(default=None)

    @classmethod
    async def initialize(cls, **kwargs: Any) -> "MCPFunctionTool":
        """
        Initialize the MCPFunctionTool with the given keyword arguments.
        """
        mcp_tool = cls(**kwargs)
        mcp_tool.function = mcp_tool.invoke_mcp_function
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

        async with Client(self.mcp_config) as client:
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
        self._function_spec = FunctionSpec.model_validate(
            {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            }
        )

    async def invoke_mcp_function(
        self,
        input_data: Messages,
    ) -> AsyncGenerator[Messages, None]:
        """
        Invoke the MCPFunctionTool with the provided input data.

        Args:
            input_data (Messages): The sequence of messages, where the last message
                contains the JSON-encoded arguments for the MCP tool call.

        Returns:
            AsyncGenerator[Messages, None]: An asynchronous generator yielding the
                output messages produced by the MCP tool invocation.
        """
        input_message = input_data[-1]

        kwargs = json.loads(input_message.content)

        response_str = ""

        async with Client(self.mcp_config) as client:
            logger.info(f"Calling MCP Tool '{self.function_name}' with args: {kwargs}")

            result: CallToolResult = await client.call_tool(self.function_name, kwargs)

            # Process the result content
            for content in result.content:
                if isinstance(content, TextContent):
                    response_str += content.text + "\n"
                elif isinstance(content, ImageContent):
                    response_str = getattr(content, "data", "")

                elif isinstance(content, EmbeddedResource):
                    # Handle embedded resources
                    response_str += (
                        f"[Embedded resource: {content.resource.model_dump_json()}]\n"
                    )
                else:
                    # Handle other content types
                    response_str += f"[Unsupported content type: {content.type}]\n"

        yield response_str

    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "mcp_config": self.mcp_config,
            "function_name": self.function_name,
        }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "MCPFunctionTool":
        """
        Create an MCPFunctionTool instance from a dictionary representation.

        Args:
            data (Dict[str, Any]): A dictionary representation of the MCPFunctionTool.

        Returns:
            MCPFunctionTool: An MCPFunctionTool instance created from the dictionary.

        Note:
            This method cannot fully reconstruct the MCP connections.
            The tool needs to be re-initialized with proper MCP configuration.
        """
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            await cls.builder()
            .name(data.get("name", "MCPFunctionTool"))
            .type(data.get("type", "MCPFunctionTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .connections(data.get("mcp_config", {}).get("mcpServers", {}))
            .function_name(data.get("function_name", ""))
            .build()
        )


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
