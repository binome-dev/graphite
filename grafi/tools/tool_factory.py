"""
ToolFactory - Factory class for deserializing tools from dictionary representations.

This module provides a centralized factory for creating tool instances from
serialized dictionary data. It automatically determines the correct tool type
and instantiates the appropriate class.
"""

from typing import Any
from typing import Dict
from typing import Type

from grafi.tools.function_calls.impl.agent_calling_tool import AgentCallingTool
from grafi.tools.function_calls.impl.duckduckgo_tool import DuckDuckGoTool
from grafi.tools.function_calls.impl.google_search_tool import GoogleSearchTool
from grafi.tools.function_calls.impl.mcp_tool import MCPTool
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.llms.impl.claude_tool import ClaudeTool
from grafi.tools.llms.impl.deepseek_tool import DeepseekTool
from grafi.tools.llms.impl.gemini_tool import GeminiTool
from grafi.tools.llms.impl.ollama_tool import OllamaTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from grafi.tools.tool import Tool


class ToolFactory:
    """
    Factory class for creating tool instances from dictionary representations.

    This factory maps tool class names to their corresponding classes and provides
    a single entry point for deserializing tools from dictionary data.

    The factory uses the "class" field in the dictionary to determine which tool
    class to instantiate, then delegates to that class's from_dict() method.

    Example:
        >>> tool_data = {
        ...     "class": "OpenAITool",
        ...     "name": "my_llm",
        ...     "model": "gpt-4o-mini",
        ...     ...
        ... }
        >>> tool = ToolFactory.from_dict(tool_data)
        >>> isinstance(tool, OpenAITool)
        True
    """

    # Registry mapping class name strings to their corresponding classes
    _TOOL_REGISTRY: Dict[str, Type[Tool]] = {
        # Base classes
        "FunctionTool": FunctionTool,
        # LLM implementations
        "OpenAITool": OpenAITool,
        "ClaudeTool": ClaudeTool,
        "DeepseekTool": DeepseekTool,
        "GeminiTool": GeminiTool,
        "OllamaTool": OllamaTool,
        "OpenRouterTool": OpenRouterTool,
        # FunctionCall implementations
        "TavilyTool": TavilyTool,
        "DuckDuckGoTool": DuckDuckGoTool,
        "GoogleSearchTool": GoogleSearchTool,
        "MCPTool": MCPTool,
        "AgentCallingTool": AgentCallingTool,
    }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> Tool:
        """
        Create a tool instance from a dictionary representation.

        This method automatically determines the tool class from the dictionary's
        "class" field and instantiates the appropriate tool class using its
        from_dict method.

        Args:
            data (Dict[str, Any]): A dictionary representation of the tool.
                Must contain at least:
                - "class": The tool class name (e.g., "OpenAITool", "ClaudeTool")
                Other required fields depend on the specific tool class.

        Returns:
            Tool: An instance of the appropriate tool subclass.

        Raises:
            ValueError: If the tool class name is unknown or not registered.
            KeyError: If the required "class" key is missing from the data dictionary.
            NotImplementedError: If the tool class doesn't implement from_dict().

        Example:
            >>> data = {
            ...     "class": "OpenAITool",
            ...     "tool_id": "abc123",
            ...     "name": "OpenAITool",
            ...     "type": "OpenAITool",
            ...     "oi_span_type": "LLM",
            ...     "model": "gpt-4o-mini",
            ...     "system_message": "You are a helpful assistant",
            ...     "chat_params": {},
            ...     "is_streaming": False,
            ...     "structured_output": False
            ... }
            >>> tool = await ToolFactory.from_dict(data)
            >>> isinstance(tool, OpenAITool)
            True
        """
        # Extract the class name
        class_name = data.get("class")

        if class_name is None:
            raise KeyError("Missing required key 'class' in tool data")

        # Look up the appropriate class
        tool_class = cls._TOOL_REGISTRY.get(class_name)

        if tool_class is None:
            raise ValueError(
                f"Unknown tool class: {class_name}. "
                f"Registered classes: {list(cls._TOOL_REGISTRY.keys())}"
            )

        # Instantiate using the class's from_dict method
        try:
            return await tool_class.from_dict(data)
        except NotImplementedError as e:
            raise NotImplementedError(
                f"Tool class '{class_name}' does not implement from_dict(). "
                f"Original error: {e}"
            ) from e

    @classmethod
    def register_tool_class(cls, class_name: str, tool_class: Type[Tool]) -> None:
        """
        Register a custom tool class with the factory.

        This allows extending the factory with new tool classes without
        modifying the factory code.

        Args:
            class_name (str): The class name string (should match tool.__class__.__name__).
            tool_class (Type[Tool]): The tool class to register.

        Example:
            >>> class CustomTool(Tool):
            ...     @classmethod
            ...     async def from_dict(cls, data):
            ...         return cls(**data)
            >>> ToolFactory.register_tool_class("CustomTool", CustomTool)
        """
        cls._TOOL_REGISTRY[class_name] = tool_class

    @classmethod
    def unregister_tool_class(cls, class_name: str) -> None:
        """
        Unregister a tool class from the factory.

        Args:
            class_name (str): The class name string to unregister.

        Raises:
            KeyError: If the class name is not registered.
        """
        if class_name not in cls._TOOL_REGISTRY:
            raise KeyError(f"Tool class '{class_name}' is not registered")
        del cls._TOOL_REGISTRY[class_name]

    @classmethod
    def get_registered_classes(cls) -> Dict[str, Type[Tool]]:
        """
        Get a copy of the current tool class registry.

        Returns:
            Dict[str, Type[Tool]]: A dictionary mapping class names to their
                registered tool classes.
        """
        return cls._TOOL_REGISTRY.copy()

    @classmethod
    def is_registered(cls, class_name: str) -> bool:
        """
        Check if a tool class is registered.

        Args:
            class_name (str): The class name to check.

        Returns:
            bool: True if the class is registered, False otherwise.
        """
        return class_name in cls._TOOL_REGISTRY
