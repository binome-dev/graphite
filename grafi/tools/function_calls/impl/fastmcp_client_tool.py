import json
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List

from loguru import logger
from pydantic import Field

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


try:

    from mcp.types import EmbeddedResource
    from mcp.types import ImageContent
    from mcp.types import TextContent
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mpc`")
try:
    from fastmcp import Client
    from fastmcp.exceptions import McpError
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install fastmcp`")


class FastMCPClient(FunctionCallTool):
    """
    FastMCPTool extends FunctionCallTool to provide HTTP Clienet Connections to Remote HTTP Servers.
    """

    # Set up API key and MCP client
    name: str = "FastMCPTool"
    type: str = "FastMCPClient"
    client_config: Dict[str, Any] = Field(default_factory=lambda: {})

    class Builder(FunctionCallTool.Builder):
        """Concrete builder for MCPTool."""

        _tool: "FastMCPClient"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "FastMCPClient":
            return FastMCPClient.model_construct()

        def client_config(
            self, client_config: Dict[str, Any]
        ) -> "FastMCPClient.Builder":
            """
            Set the client configuration for the MCP client.

            Args:
                client_config (Dict[str, Any]): The configuration dictionary for the MCP client.

            Returns:
                FastMCPClient.Builder: The builder instance for method chaining.
            """
            self._tool.client_config = client_config
            return self

        def build(self) -> None:
            raise NotImplementedError(
                "MCPTool does not support synchronous execution. Use a_build instead."
            )

        async def a_build(self) -> "FastMCPClient":
            await self._a_build_function_specs()
            return self._tool

        async def _a_build_function_specs(self) -> None:
            client_config = self._tool.client_config
            if (
                client_config is None
                or client_config is {}
                or client_config.get("mcpServers") is None
            ):
                raise ValueError("Client Config are not set.")

            client = Client(
                self._tool.client_config
            )  # Initialize the client with the config
            async with client:
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

        client = Client(self.client_config)
        async with client:
            logger.info(f"Client connected: {client.is_connected()}")
            for tool_call in input_message.tool_calls:
                if any(
                    spec.name == tool_call.function.name for spec in self.function_specs
                ):
                    tool_name = tool_call.function.name
                    kwargs = json.loads(tool_call.function.arguments)

                    logger.info(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")
                    try:
                        results = await client.call_tool(tool_name, kwargs)
                        response_str = ""
                        for result in results:
                            if isinstance(result, TextContent):
                                response_str = result.text + "\n"

                            if isinstance(result, TextContent):
                                response_str += result.text + "\n"
                            elif isinstance(result, ImageContent):
                                response_str = getattr(result, "data", "")

                            elif isinstance(result, EmbeddedResource):
                                # Handle embedded resources
                                response_str += f"[Embedded resource: {result.resource.model_dump_json()}]\n"
                            else:
                                # Handle other content types
                                response_str += (
                                    f"[Unsupported content type: {result.type}]\n"
                                )

                        messages.extend(
                            self.to_messages(
                                response=response_str, tool_call_id=tool_call.id
                            )
                        )

                    except McpError as e:
                        # Return an error if the tool call failed
                        logger.error(f"Error calling MCP tool: {e}")
                        raise e

        yield messages
