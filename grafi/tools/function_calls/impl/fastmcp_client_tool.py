import json
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List
from typing import Optional

import httpx
from loguru import logger
from pydantic import Field

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.mcp_tool_spec import MCPToolSpec
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.function_call_tool import FunctionCallToolBuilder


try:

    from mcp import ListPromptsResult
    from mcp import ListResourcesResult
    from mcp.types import CallToolResult
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
    FastMCPClient extends FunctionCallTool to provide web search functionality using the MCP API.
    """

    # Set up API key and MCP client
    name: str = "FastMCPClient"
    type: str = "FastMCPClient"
    # server_params: Optional[StdioServerParameters] = None
    prompts: Optional[ListPromptsResult] = None
    resources: Optional[ListResourcesResult] = None
    client_config: Dict[str, Any] = Field(default_factory=lambda: {})

    @classmethod
    def builder(cls) -> "FastMCPClientBuilder":
        """
        Return a builder for FastMCPClient.
        """
        return FastMCPClientBuilder(cls)

    async def _a_get_function_specs(self) -> None:

        client_config = self.client_config
        if (
            client_config is None
            or client_config is {}
            or client_config.get("mcpServers") is None
        ):
            raise ValueError("Client Config are not set.")
        logger.debug(f"Initializing FastMCPClient with config: {client_config}")
        client = Client(self.client_config)  # Initialize the client with the config

        try:

            async with client:
                logger.debug(f"Client connected: {client.is_connected()}")
                tools = await client.list_tools()
                logger.debug(f"Current tools {tools}")

                for tool in tools:
                    mcp_tool_spec = {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    }

                    # self.function_specs.append(mcp_tool_spec)
                    self.function_specs.append(
                        FunctionSpec.model_validate(mcp_tool_spec)
                    )

                self.resources = await client.list_resources()

                self.prompts = await client.list_prompts()

                logger.debug(f"Resources: {self.resources}")
                logger.debug(f"Prompts: {self.prompts}")
        except ConnectionError as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            raise ConnectionError(
                f"Failed to connect to MCP server. Please check your configuration: {e}"
            )

        except httpx.ConnectError as e:
            logger.error(f"Connection To MCP Server failed, is the server up?: {e}")
            raise ConnectionError(
                f"Failed to connect to MCP server. Please check your configuration: {e}"
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error: {e.response.status_code} - {e}")
            raise ConnectionError(
                f"HTTP error: {e.response.status_code} - {e.response.text}"
            )

        except httpx.RequestError as e:
            logger.error(f"Request failed: {e}")
            raise httpx.RequestError(
                f"Request failed: {e}. Please check your MCP server configuration."
            )

    @record_tool_execution
    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        raise NotImplementedError(
            "FastMCPClient does not support synchronous execution. Use a_execute instead."
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
            logger.debug(f"Client connected: {client.is_connected()}")
            for tool_call in input_message.tool_calls:
                if any(
                    spec.name == tool_call.function.name for spec in self.function_specs
                ):
                    tool_name = tool_call.function.name
                    kwargs = json.loads(tool_call.function.arguments)

                    logger.debug(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")
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


class FastMCPClientBuilder(FunctionCallToolBuilder[FastMCPClient]):
    """
    Builder for FastMCPClient.
    """

    def client_config(self, config: Dict[str, Any]) -> "FastMCPClientBuilder":
        """
        Set the client configuration for the FastMCPClient.
        """
        self._obj.client_config = config
        return self

    def build(self) -> None:
        raise NotImplementedError(
            "FastMCPClient does not support synchronous execution. Use a_build instead."
        )

    async def a_build(self) -> "FastMCPClient":
        await self._obj._a_get_function_specs()
        return self._obj
