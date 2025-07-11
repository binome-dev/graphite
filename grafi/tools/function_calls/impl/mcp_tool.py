import json
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List

from fastmcp import Client
from loguru import logger
from pydantic import Field

from grafi.common.decorators.record_tool_a_invoke import record_tool_a_invoke
from grafi.common.decorators.record_tool_invoke import record_tool_invoke
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.mcp_connections import Connection
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.function_call_tool import FunctionCallToolBuilder


try:
    from mcp.types import CallToolResult
    from mcp.types import EmbeddedResource
    from mcp.types import ImageContent
    from mcp.types import Prompt
    from mcp.types import Resource
    from mcp.types import TextContent
    from mcp.types import Tool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


class MCPTool(FunctionCallTool):
    """
    MCPTool extends FunctionCallTool to provide web search functionality using the MCP API.
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
        await mcp_tool._a_get_function_specs()

        return mcp_tool

    @classmethod
    def builder(cls) -> "MCPToolBuilder":
        """
        Return a builder for MCPTool.
        """
        return MCPToolBuilder(cls)

    async def _a_get_function_specs(self) -> None:
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

    @record_tool_invoke
    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        raise NotImplementedError(
            "MCPTool does not support synchronous invoke. Use a_invoke instead."
        )

    @record_tool_a_invoke
    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> AsyncGenerator[Messages, None]:
        """
        Invoke the MCPTool with the provided input data.

        Args:
            invoke_context (InvokeContext): The context for executing the function.
            input_data (Message): The input data for the function.

        Returns:
            List[Message]: The output messages from the function invoke.
        """
        input_message = input_data[0]
        if input_message.tool_calls is None:
            logger.warning("Function call is None.")
            raise ValueError("Function call is None.")

        messages: List[Message] = []

        for tool_call in input_message.tool_calls:
            if any(
                tool_call.function.name == spec.name for spec in self.function_specs
            ):
                tool_name = tool_call.function.name
                kwargs = json.loads(tool_call.function.arguments)

                async with Client(self.mcp_config) as client:
                    logger.info(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")

                    result: CallToolResult = await client.call_tool(tool_name, kwargs)

                    # Process the result content
                    response_str = ""
                    for content in result.content:
                        if isinstance(content, TextContent):
                            response_str += content.text + "\n"
                        elif isinstance(content, ImageContent):
                            response_str = getattr(content, "data", "")

                        elif isinstance(content, EmbeddedResource):
                            # Handle embedded resources
                            response_str += f"[Embedded resource: {content.resource.model_dump_json()}]\n"
                        else:
                            # Handle other content types
                            response_str += (
                                f"[Unsupported content type: {content.type}]\n"
                            )

                    messages.extend(
                        self.to_messages(
                            response=response_str, tool_call_id=tool_call.id
                        )
                    )

        yield messages

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

    def to_dict(self):
        return {
            **super().to_dict(),
            "mcp_config": self.mcp_config,
            "resources": [resource.model_dump_json() for resource in self.resources],
            "prompts": [prompt.model_dump_json() for prompt in self.prompts],
        }


class MCPToolBuilder(FunctionCallToolBuilder[MCPTool]):
    """
    Builder for MCPTool.
    """

    def connections(self, connections: Dict[str, Connection]) -> "MCPToolBuilder":
        self.kwargs["mcp_config"] = {
            "mcpServers": connections,
        }
        return self

    def build(self) -> None:
        raise NotImplementedError(
            "MCPTool does not support synchronous invoke. Use a_build instead."
        )

    async def a_build(self) -> "MCPTool":
        mcp_tool = await self._cls.initialize(**self.kwargs)
        return mcp_tool
