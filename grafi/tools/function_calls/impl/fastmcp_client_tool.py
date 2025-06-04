
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
    from fastmcp import Client
    from fastmcp import FastMCP
    from fastmcp import Resource 
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install fastmcp`")


class FastMCPClient(FunctionCallTool):
    """
    FastMCPTool extends FunctionCallTool to provide HTTP Clienet Connections to Remote HTTP Servers.
    """

    # Set up API key and MCP client
    name: str = "FastMCPTool"
    type: str = "FastMCPClient"
    host: str = "localhost"
    port : int = 8000 
    # Here not sure if we want to make the host and port as arguments or the entire client config? Gonna use client_config for now but maybe we want
    # to make it more flexible in the future.
    client : Client = None
    client_config = {
        "mcpServers": {
            "remote": {"url": "http://localhost:8080/mcp"},
        }

    }

    class Builder(FunctionCallTool.Builder):
        """Concrete builder for MCPTool."""

        _tool: "FastMCPClient"

        def __init__(self) -> None:
            if self._tool.client_config is {}:
                raise ValueError("Client Config are not set.")
            self.client = Client(self._tool.client_config) # Not sure if saving the client reference is good here, might just have to initialize it in the a_build function, keeping here for reference
            self._tool = self._init_tool()

        def _init_tool(self) -> "FastMCPClient":
            return FastMCPClient.model_construct()

        def build(self) -> None:
            raise NotImplementedError(
                "MCPTool does not support synchronous execution. Use a_build instead."
            )

        async def a_build(self) -> "FastMCPClient":
            await self._a_build_function_specs()
            return self._tool

        async def _a_build_function_specs(self) -> None:

            client = Client(self._tool.client_config) 
            async with self._tool.client:
                logger.info(f"Client connected: {client.is_connected()}")
                tools_list = await client.list_tools()

                for tool in tools_list:
                    func_spec = {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    }

                    self._tool.function_specs.append(
                        FunctionSpec.model_validate(func_spec)
                    )
                 
                self.resources = await client.list_resources()
                self.prompts = await client.list_prompts()
            


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
        Execute the FastMCPClient with the provided input data.

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

        if self.client_config is None:
            raise ValueError("Client Config not set.")

        client = Client(self._tool.client_config) 
        async with client:
            logger.info(f"Client connected: {client.is_connected()}")
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

                    result = await client.call_tool(
                        tool_name, kwargs
                    )

                    # Return an error if the tool call failed
                    if result.isError:
                        raise Exception(
                            f"Error from MCP tool '{tool_name}': {result.content}"
                        )

                    # Can't write this last bit as I can't get the imports to work to execute this
                    response_str = ""
                    for content_item in result.content:
                        if isinstance(content_item, TextContent):
                            response_str += content_item.text + "\n"
                        elif isinstance(content_item, ImageContent):

