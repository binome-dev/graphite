import json
from typing import AsyncGenerator
from typing import List
from typing import Optional

from loguru import logger

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


try:
    from mcp import ClientSession
    from mcp import ListPromptsResult
    from mcp import ListResourcesResult
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import CallToolResult
    from mcp.types import EmbeddedResource
    from mcp.types import ImageContent
    from mcp.types import TextContent
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


class MCPTool(FunctionCallTool):
    """
    MCPTool extends FunctionCallTool to provide web search functionality using the MCP API.
    """

    # Set up API key and MCP client
    name: str = "MCPTool"
    type: str = "MCPTool"
    server_params: Optional[StdioServerParameters] = None
    prompts: Optional[ListPromptsResult] = None
    resources: Optional[ListResourcesResult] = None

    class Builder(FunctionCallTool.Builder):
        """Concrete builder for MCPTool."""

        _tool: "MCPTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "MCPTool":
            return MCPTool.model_construct()

        def server_params(
            self, server_params: StdioServerParameters
        ) -> "MCPTool.Builder":
            self._tool.server_params = server_params
            return self

        def build(self) -> None:
            raise NotImplementedError(
                "MCPTool does not support synchronous execution. Use a_build instead."
            )

        async def a_build(self) -> "MCPTool":
            await self._a_build_function_specs()
            return self._tool

        async def _a_build_function_specs(self) -> None:

            if self._tool.server_params is None:
                raise ValueError("Server parameters are not set.")

            async with stdio_client(self._tool.server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    # Initialize the connection
                    await session.initialize()

                    # List available prompts
                    self.prompts = await session.list_prompts()

                    # List available resources
                    self.resources = await session.list_resources()

                    # List available tools
                    tools_list = await session.list_tools()

                    for tool in tools_list.tools:
                        func_spec = {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema,
                        }

                        self._tool.function_specs.append(
                            FunctionSpec.model_validate(func_spec)
                        )

    @record_tool_execution
    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        raise NotImplementedError(
            "MCPTool does not support synchronous execution. Use a_execute instead."
        )

    @record_tool_a_execution
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> AsyncGenerator[Messages, None]:
        """
        Execute the MCPTool with the provided input data.

        Args:
            execution_context (ExecutionContext): The context for executing the function.
            input_data (Message): The input data for the function.

        Returns:
            List[Message]: The output messages from the function execution.
        """
        input_message = input_data[0]
        if input_message.tool_calls is None:
            logger.warning("Function call is None.")
            raise ValueError("Function call is None.")

        messages: List[Message] = []

        if self.server_params is None:
            raise ValueError("Server parameters are not set.")

        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                for tool_call in input_message.tool_calls:
                    if any(
                        spec.name == tool_call.function.name
                        for spec in self.function_specs
                    ):

                        tool_name = tool_call.function.name
                        kwargs = json.loads(tool_call.function.arguments)

                        logger.info(
                            f"Calling MCP Tool '{tool_name}' with args: {kwargs}"
                        )

                        result: CallToolResult = await session.call_tool(
                            tool_name, kwargs
                        )

                        # Return an error if the tool call failed
                        if result.isError:
                            raise Exception(
                                f"Error from MCP tool '{tool_name}': {result.content}"
                            )

                        # Process the result content
                        response_str = ""
                        for content_item in result.content:
                            if isinstance(content_item, TextContent):
                                response_str += content_item.text + "\n"
                            elif isinstance(content_item, ImageContent):

                                response_str = getattr(content_item, "data", "")

                            elif isinstance(content_item, EmbeddedResource):
                                # Handle embedded resources
                                response_str += f"[Embedded resource: {content_item.resource.model_dump_json()}]\n"
                            else:
                                # Handle other content types
                                response_str += (
                                    f"[Unsupported content type: {content_item.type}]\n"
                                )

                        messages.extend(
                            self.to_messages(
                                response=response_str, tool_call_id=tool_call.id
                            )
                        )

        yield messages
