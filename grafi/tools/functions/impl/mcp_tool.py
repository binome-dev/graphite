import asyncio
from contextlib import AsyncExitStack
import json
from os import environ
from types import TracebackType

from typing import Any, AsyncGenerator, List, Optional
from typing import Dict
from typing import Literal

from loguru import logger

from pydantic import Field

from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.message import Message
from grafi.tools.functions.function_tool import FunctionTool

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp import ListResourcesResult, ListPromptsResult
    from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent
    from mcp.client.stdio import stdio_client
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


class MCPTool(FunctionTool):
    """
    MCPTool extends FunctionTool to provide web search functionality using the MCP API.
    """

    # Set up API key and MCP client
    name: str = "MCPTool"
    type: str = "MCPTool"
    function_specs: List[Dict[str, Any]] = Field(default_factory=list)
    server_params: Optional[StdioServerParameters] = None,
    session: Optional[ClientSession] = None,
    prompts: Optional[ListPromptsResult] = None,
    resources: Optional[ListResourcesResult] = None,

    class Builder(FunctionTool.Builder):
        """Concrete builder for MCPTool."""

        def __init__(self):
            self._tool = self._init_tool()

        def _init_tool(self) -> "MCPTool":
            return MCPTool()

        def server_params(
            self, server_params: StdioServerParameters
        ) -> "MCPTool.Builder":
            self._tool.server_params = server_params
            return self
        
        def session(self, session: ClientSession) -> "MCPTool.Builder":
            self._tool.session = session
            return self
        
        def build(self) -> "MCPTool":
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside FastAPI or another async app
                # Schedule the coroutine and wait for it
                future = asyncio.ensure_future(self._build_async())
                # Block until the future is done
                asyncio.get_event_loop().run_until_complete(future)
            else:
                # Normal sync environment
                asyncio.run(self._build_async())

            return self._tool
        
        async def _build_async(self):
                    
            async with stdio_client(self.server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    # Initialize the connection
                    await session.initialize()

                    # List available prompts
                    self.prompts = await session.list_prompts()

                    # List available resources
                    self.resources = await session.list_resources()

                    # List available tools
                    tools = await session.list_tools()

                    for tool in tools:
                        func_spec = {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema,
                        }

                        self._tool.function_specs.append(func_spec)

        
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        input_data: Message,
    ) -> AsyncGenerator[Message, None]:
        """
        Execute the MCPTool with the provided input data.

        Args:
            execution_context (ExecutionContext): The context for executing the function.
            input_data (Message): The input data for the function.

        Returns:
            List[Message]: The output messages from the function execution.
        """
        
        if input_data.tool_calls is None:
            logger.warning("Function call is None.")
            raise ValueError("Function call is None.")

        messages: List[Message] = []

        for tool_call in input_data.tool_calls:
            if any(spec["name"] == tool_call.function.name for spec in self.function_specs):

                tool_name = tool_call.function.name
                kwargs = json.loads(tool_call.function.arguments)

                logger(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")
                
                result: CallToolResult = await self.session.call_tool(tool_name, kwargs)  # type: ignore

                # Return an error if the tool call failed
                if result.isError:
                    raise Exception(f"Error from MCP tool '{tool_name}': {result.content}")

                # Process the result content
                response_str = ""
                for content_item in result.content:
                    if isinstance(content_item, TextContent):
                        response_str += content_item.text + "\n"
                    elif isinstance(content_item, ImageContent):
                        
                        response_str=getattr(content_item, "data", None),

                    elif isinstance(content_item, EmbeddedResource):
                        # Handle embedded resources
                        response_str += f"[Embedded resource: {content_item.resource.model_dump_json()}]\n"
                    else:
                        # Handle other content types
                        response_str += f"[Unsupported content type: {content_item.type}]\n"

                
                messages.append(
                    self.to_message(response=response_str, tool_call_id=tool_call.id)
                )
        
                yield messages