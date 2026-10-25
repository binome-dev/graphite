from typing import Any
from typing import Dict
from typing import Iterable
from typing import List

from pydantic import BaseModel
from pydantic import Field
from pydantic import SerializationInfo
from pydantic import field_serializer

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.mcp_connections import Connection
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.function_call_tool import FunctionCallToolBuilder
from grafi.tools.mcp_config import MCPConnected

try:
    import fastmcp  # noqa: F401 - what connect() connects with.
except (ImportError, ModuleNotFoundError):
    raise ImportError("`fastmcp` not installed. Please install using `uv add fastmcp`")

try:
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


def mcp_spec(tool: Tool) -> FunctionSpec:
    """An MCP server's tool, as the function it offers an LLM."""
    return FunctionSpec.model_validate(
        {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        }
    )


class MCPTool(MCPConnected, FunctionCallTool):
    """A tool that answers an LLM's tool calls with the tools of MCP servers.

    Building one (``await MCPTool.builder()...build()``) lists the servers'
    tools, resources and prompts; it is saved with them, so loading one does
    not connect. A secret in ``mcp_config`` is given as a reference to an
    environment variable, ``"${VAR}"`` (see :mod:`grafi.tools.mcp_config`).
    Each call connects anew, so calls hold no state in common: calls made at
    once to a stdio server each start its process.
    """

    name: str = "MCPTool"
    type: str = "MCPTool"

    # What its servers offer, listed when it is built, and saved (its
    # function_specs too).
    resources: List[Resource] = Field(default_factory=list)
    prompts: List[Prompt] = Field(default_factory=list)

    @field_serializer("resources", "prompts")
    def _save_by_alias(
        self, items: List[BaseModel], info: SerializationInfo
    ) -> List[Dict[str, Any]]:
        """MCP's models, as MCP names their fields (``_meta``), which is how
        they load."""
        return [item.model_dump(mode=info.mode, by_alias=True) for item in items]

    @classmethod
    async def initialize(cls, **kwargs: Any) -> "MCPTool":
        """An MCPTool offering what its servers do -- their tools, resources and
        prompts, listed now -- beside any specs it is given; a function of its
        own wins over a server's tool of the same name (and is warned of)."""
        given = kwargs["function_specs"] = kwargs.get("function_specs") or []

        async def listing(client: Any) -> Dict[str, Any]:
            tools = await client.list_tools()
            return {
                "function_specs": [*given, *map(mcp_spec, tools)],
                "resources": await client.list_resources(),
                "prompts": await client.list_prompts(),
            }

        return await cls._listed(kwargs, listing)

    @classmethod
    def builder(cls) -> "MCPToolBuilder":
        """
        Return a builder for MCPTool.
        """
        return MCPToolBuilder(cls)

    async def call_function(
        self, invoke_context: InvokeContext, name: str, arguments: Dict[str, Any]
    ) -> str:
        """Call the MCP server's tool ``name``, and return its result as text."""
        async with self._connect() as client:
            result = await client.call_tool(name, arguments)
        return content_text(result.content)

    async def get_prompt(
        self,
        prompt_name: str,
        *,
        arguments: Dict[str, Any] | None = None,
    ) -> Messages:
        if not any(prompt.name == prompt_name for prompt in self.prompts):
            raise ValueError(f"Prompt '{prompt_name}' not found")

        async with self._connect() as client:
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

        async with self._connect() as client:
            return await client.read_resource(uri)


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
