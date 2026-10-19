from typing import Any
from typing import Dict
from typing import Iterable
from typing import List

from pydantic import Field

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.mcp_connections import Connection
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.function_call_tool import FunctionCallToolBuilder

try:
    from fastmcp import Client
except (ImportError, ModuleNotFoundError):
    raise ImportError("`fastmcp` not installed. Please install using `uv add fastmcp`")

try:
    from mcp.types import CallToolResult
    from mcp.types import EmbeddedResource
    from mcp.types import ImageContent
    from mcp.types import Prompt
    from mcp.types import Resource
    from mcp.types import TextContent
    from mcp.types import Tool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `uv add mcp`")


def content_text(contents: Iterable[Any]) -> str:
    """An MCP result's content as text, a line per item: text as it is, an
    image as its base64 data, an embedded resource as its JSON."""
    lines = []
    for content in contents:
        if isinstance(content, TextContent):
            lines.append(content.text)
        elif isinstance(content, ImageContent):
            lines.append(content.data)
        elif isinstance(content, EmbeddedResource):
            lines.append(f"[Embedded resource: {content.resource.model_dump_json()}]")
        else:
            lines.append(f"[Unsupported content type: {content.type}]")
    return "\n".join(lines)


class MCPTool(FunctionCallTool):
    """
    MCPTool extends FunctionCallTool to provide functionality using the MCP API.
    """

    # Set up API key and MCP client
    name: str = "MCPTool"
    type: str = "MCPTool"

    mcp_config: Dict[str, Any] = Field(default_factory=dict)
    resources: List[Resource] = Field(default_factory=list)
    prompts: List[Prompt] = Field(default_factory=list)

    @classmethod
    async def initialize(cls, **kwargs: Any) -> "MCPTool":
        """
        Initialize the MCPTool with the given keyword arguments.
        """
        mcp_tool = cls(**kwargs)
        await mcp_tool._get_function_specs()

        return mcp_tool

    @classmethod
    def builder(cls) -> "MCPToolBuilder":
        """
        Return a builder for MCPTool.
        """
        return MCPToolBuilder(cls)

    async def _get_function_specs(self) -> None:
        if not self.mcp_config:
            raise ValueError("mcp_config are not set.")

        all_tools: list[Tool] = []

        async with Client(self.mcp_config) as client:
            all_tools.extend(await client.list_tools())
            self.resources = await client.list_resources()
            self.prompts = await client.list_prompts()

        for tool in all_tools:
            func_spec = {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            }

            self.function_specs.append(FunctionSpec.model_validate(func_spec))

    async def call_function(
        self, invoke_context: InvokeContext, name: str, arguments: Dict[str, Any]
    ) -> str:
        """Call the MCP server's tool ``name``, and return its result as text."""
        async with Client(self.mcp_config) as client:
            result: CallToolResult = await client.call_tool(name, arguments)
        return content_text(result.content)

    async def get_prompt(
        self,
        prompt_name: str,
        *,
        arguments: Dict[str, Any] | None = None,
    ) -> Messages:
        if not any(prompt.name == prompt_name for prompt in self.prompts):
            raise ValueError(f"Prompt '{prompt_name}' not found")

        async with Client(self.mcp_config) as client:
            prompt = await client.get_prompt(prompt_name, arguments=arguments)
            return [
                Message(
                    role=message.role,
                    content=message.content,
                )
                for message in prompt.messages
            ]

    async def get_resources(self, uri: str) -> List:
        if not any(resource.uri.encoded_string() == uri for resource in self.resources):
            raise ValueError(f"Resource with URI '{uri}' not found")

        async with Client(self.mcp_config) as client:
            return await client.read_resource(uri)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "mcp_config": self.mcp_config,
            "resources": [resource.model_dump_json() for resource in self.resources],
            "prompts": [prompt.model_dump_json() for prompt in self.prompts],
        }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "MCPTool":
        """
        Create an MCPTool instance from a dictionary representation.

        Args:
            data (Dict[str, Any]): A dictionary representation of the MCPTool.

        Returns:
            MCPTool: An MCPTool instance created from the dictionary.

        Note:
            This method cannot fully reconstruct the MCP connections.
            The tool needs to be re-initialized with proper MCP configuration.
        """
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        return (
            await cls.builder()
            .name(data.get("name", "MCPTool"))
            .type(data.get("type", "MCPTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .connections(data.get("mcp_config", {}).get("mcpServers", {}))
            .build()
        )


class MCPToolBuilder(FunctionCallToolBuilder[MCPTool]):
    """
    Builder for MCPTool.
    """

    def connections(self, connections: Dict[str, Connection]) -> "MCPToolBuilder":
        self.kwargs["mcp_config"] = {
            "mcpServers": connections,
        }
        return self

    async def build(self) -> "MCPTool":
        mcp_tool = await self._cls.initialize(**self.kwargs)
        return mcp_tool
