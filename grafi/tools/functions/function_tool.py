from functools import partial
from typing import Any
from typing import Callable
from typing import Self
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.async_lifecycle import owned_iterator
from grafi.common.callable_ref import CallableRef
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.exceptions import FunctionToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.results import as_messages
from grafi.tools.results import function_results
from grafi.tools.tool import Tool
from grafi.tools.tool import ToolBuilder


class FunctionTool(Tool):
    """A tool that runs a function on the messages it is given.

    The function returns the tool's output, like any Python function, sync or
    async: messages, which pass as they are (so an empty list is no output);
    None, for no output; or any other value, which becomes one message from
    ``role`` holding it as text. A
    generator streams its output instead: each string it yields reaches a
    streaming caller as a delta, and the text it yielded is its output (see
    :mod:`grafi.tools.results`). Sync code runs in a worker thread.
    """

    name: str = "FunctionTool"
    type: str = "FunctionTool"
    role: str = "assistant"
    # Called with the messages; saved by reference (see grafi.common.callable_ref).
    function: CallableRef
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    @classmethod
    def builder(cls) -> "FunctionToolBuilder":
        """
        Return a builder for FunctionTool.

        This method allows for the construction of a FunctionTool instance with specified parameters.
        """
        return FunctionToolBuilder(cls)

    @record_tool_invoke
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        results = function_results(partial(self.function, input_data))
        try:
            async with owned_iterator(results):
                async for result in results:
                    if messages := as_messages(result, self.role):
                        yield messages
        except Exception as e:
            raise FunctionToolException(
                tool_name=self.name,
                operation="invoke",
                message=f"Function failed: {e}",
                invoke_context=invoke_context,
                cause=e,
            ) from e


T_FT = TypeVar("T_FT", bound=FunctionTool)


class FunctionToolBuilder(ToolBuilder[T_FT]):
    """Builder for FunctionTool instances."""

    def role(self, role: str) -> Self:
        """Set the role for messages produced by this function.

        Args:
            role: The message role (e.g., 'assistant', 'tool').

        Returns:
            Self for method chaining.
        """
        self.kwargs["role"] = role
        return self

    def function(self, function: Callable[[Messages], Any]) -> Self:
        """Set the function to execute.

        Args:
            function: A function, sync or async, or a generator, that takes
                the messages and returns or streams the tool's output.

        Returns:
            Self for method chaining.
        """
        self.kwargs["function"] = function
        return self
