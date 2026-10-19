import asyncio
import functools
import inspect
import json
from typing import Any
from typing import Callable
from typing import ClassVar
from typing import Dict
from typing import Literal
from typing import Self
from typing import Tuple
from typing import TypeVar
from typing import get_type_hints

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ConfigDict
from pydantic import Field
from pydantic import validate_call

from grafi.common.async_lifecycle import owned_iterator
from grafi.common.async_lifecycle import wait_all
from grafi.common.callable_ref import deserialize_callable
from grafi.common.callable_ref import serialize_callable
from grafi.common.decorators.llm_function import is_invoke_context
from grafi.common.decorators.llm_function import llm_function
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.exceptions import FunctionCallException
from grafi.common.exceptions import ToolInvocationError
from grafi.common.exceptions.serialization import error_message
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import ChatCompletionMessageToolCall
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.runtime.deltas import deltas_for
from grafi.tools.command import use_command
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.results import as_text
from grafi.tools.results import function_results
from grafi.tools.results import in_thread
from grafi.tools.results import is_sync
from grafi.tools.tool import Tool
from grafi.tools.tool import ToolBuilder


@use_command(FunctionCallCommand)
class FunctionCallTool(Tool):
    """A tool that answers an LLM's tool calls by calling functions.

    Its functions are its ``@llm_function`` methods, its bases' included, and
    those the builder adds. It answers each call it is given with one tool
    message: what the function returns, or streams, as text (see
    :mod:`grafi.tools.results`); or, unless ``on_error`` is ``"raise"``, the
    error the call raised, such as invalid arguments or an unknown function, so
    the LLM can recover. Calls run concurrently, sync functions in worker
    threads, so a tool's sync functions must be safe to run at the same time.
    Arguments are validated against the function's signature, and a parameter
    typed ``InvokeContext`` is passed the request's context.
    """

    name: str = "FunctionCallTool"
    type: str = "FunctionCallTool"
    function_specs: FunctionSpecs = Field(default_factory=list)
    functions: Dict[str, Callable] = Field(default_factory=dict)
    # "raise" fails the call's node instead of answering the LLM with the error.
    on_error: Literal["return", "raise"] = "return"
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    # The class's @llm_function methods, its bases' included, by name.
    _methods: ClassVar[Dict[str, Any]] = {}

    @classmethod
    def builder(cls) -> "FunctionCallToolBuilder":
        """
        Return a builder for FunctionCallTool.

        This method allows for the construction of a FunctionCallTool instance with specified parameters.
        """
        return FunctionCallToolBuilder(cls)

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register the @llm_function methods of the class and of its bases."""
        super().__init_subclass__(**kwargs)
        methods = {}
        for klass in reversed(cls.__mro__):
            for attr in vars(klass).values():
                spec = getattr(attr, "_function_spec", None)
                if isinstance(spec, FunctionSpec):
                    methods[spec.name] = attr
        cls._methods = methods
        cls.functions = dict(methods)
        cls.function_specs = [method._function_spec for method in methods.values()]

    def get_function_specs(self) -> FunctionSpecs:
        """The specifications of the functions offered to the LLM."""
        return self.function_specs

    @record_tool_invoke
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        """Answer every tool call in ``input_data``, concurrently: one tool
        message per call, in the calls' order."""
        calls = [call for message in input_data for call in message.tool_calls or []]
        if not calls:
            return
        answering = [
            asyncio.ensure_future(self._answer(invoke_context, call)) for call in calls
        ]
        try:
            answers = await asyncio.gather(*answering)
        except BaseException as error:
            for task in answering:
                task.cancel()
            # Never abandoned; a cancellation meanwhile outranks a failure.
            if await wait_all(answering) and isinstance(error, Exception):
                raise asyncio.CancelledError() from error
            raise
        yield answers

    async def _answer(
        self, invoke_context: InvokeContext, call: ChatCompletionMessageToolCall
    ) -> Message:
        name = call.function.name
        try:
            if all(spec.name != name for spec in self.function_specs):
                raise LookupError(f"No function {name!r}")
            arguments = json.loads(call.function.arguments or "{}")
            results = function_results(
                functools.partial(self.call_function, invoke_context, name, arguments)
            )
            with deltas_for(call.id):  # What the function streams is the call's.
                async with owned_iterator(results):
                    content = "\n".join([as_text(result) async for result in results])
        except Exception as error:
            if self.on_error == "raise":
                if isinstance(error, ToolInvocationError):
                    raise
                raise FunctionCallException(
                    tool_name=self.name,
                    function_name=name,
                    message=f"Function {name!r} failed: {error}",
                    invoke_context=invoke_context,
                    cause=error,
                ) from error
            content = f"Error: {type(error).__name__}: {error_message(error)}"
            logger.warning("{} answers call {} with {}", self.name, call.id, content)
        return Message(role="tool", tool_call_id=call.id, content=content)

    async def call_function(
        self, invoke_context: InvokeContext, name: str, arguments: Dict[str, Any]
    ) -> Any:
        """Call the function ``name`` with the LLM's ``arguments``, validated
        against its signature, and return what it returns, a value or a
        generator. A parameter typed ``InvokeContext`` is passed
        ``invoke_context``, and ``self`` this tool. Override to call functions
        elsewhere, such as on a server, as MCPTool does."""
        function = self.functions[name]
        method = function is type(self)._methods.get(name)
        if method:  # Called as the tool's method, so an override runs.
            function = getattr(type(self), name, function)
        validated, contexts, takes_self = _calling(function)
        arguments = {**arguments, **dict.fromkeys(contexts, invoke_context)}
        call = functools.partial(validated, self) if method or takes_self else validated
        if is_sync(function):
            return await in_thread(functools.partial(call, **arguments))
        result = call(**arguments)
        return await result if inspect.isawaitable(result) else result

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the tool instance to a dictionary representation.

        Returns:
            Dict[str, Any]: A dictionary representation of the tool.
        """

        # Functions discovered from @llm_function-decorated methods are intrinsic
        # to the class and re-registered automatically on from_dict (see
        # __init_subclass__), so they are NOT serialized. Only standalone
        # functions added via the builder are serialized (as references).
        serialized_functions = {
            name: serialize_callable(function)
            for name, function in self.functions.items()
            if function is not type(self)._methods.get(name)
        }

        return {
            **super().to_dict(),
            "base_class": "FunctionCallTool",
            "function_specs": [spec.model_dump() for spec in self.function_specs],
            "functions": serialized_functions,
            "on_error": self.on_error,
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "FunctionCallTool":
        """
        Create a FunctionCallTool instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the FunctionCallTool.

        Returns:
            FunctionCallTool: A FunctionCallTool instance created from the dictionary.

        Note:
            Each function is reconstructed (without pickle) from its import
            reference or CallableComponent config. See
            :mod:`grafi.common.callable_ref`.
        """
        function_call_tool_builder = (
            cls.builder()
            .name(data.get("name", "FunctionCallTool"))
            .type(data.get("type", "FunctionCallTool"))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .on_error(data.get("on_error", "return"))
        )

        for func_name, func_serialized in data.get("functions", {}).items():
            func = deserialize_callable(
                func_serialized, context=f"function '{func_name}'"
            )
            function_call_tool_builder.function(func)

        return function_call_tool_builder.build()


@functools.lru_cache(maxsize=1024)
def _calling(function: Callable) -> Tuple[Callable, Tuple[str, ...], bool]:
    """``function`` validating its arguments, the names of its parameters typed
    ``InvokeContext``, and whether its first parameter is ``self``."""
    parameters = list(inspect.signature(function).parameters)
    hints = get_type_hints(function)
    return (
        validate_call(config=ConfigDict(arbitrary_types_allowed=True))(function),
        tuple(name for name in parameters if is_invoke_context(hints.get(name))),
        parameters[:1] == ["self"],
    )


T_F = TypeVar("T_F", bound=FunctionCallTool)


class FunctionCallToolBuilder(ToolBuilder[T_F]):
    """
    Builder for FunctionCallTool.

    This class provides a fluent interface for constructing a FunctionCallTool instance.
    It allows setting the function and building the tool.
    """

    def function(self, function: Callable) -> Self:
        """Add a function that can be called by the LLM.

        If the function is not already decorated with @llm_function,
        it will be automatically wrapped. It may be sync or async, or a
        generator; one whose first parameter is ``self`` is passed this tool.

        Args:
            function: A callable to expose as a tool function.

        Returns:
            Self for method chaining.
        """
        if not hasattr(function, "_function_spec"):
            function = llm_function(function)
        spec: FunctionSpec = function._function_spec  # type: ignore[attr-defined]
        methods = self._cls._methods  # Kept beside the functions added.
        functions = self.kwargs.setdefault("functions", dict(methods))
        specs = self.kwargs.setdefault(
            "function_specs", [method._function_spec for method in methods.values()]
        )
        functions[spec.name] = function  # Replacing one of the same name.
        specs[:] = [*(other for other in specs if other.name != spec.name), spec]
        return self

    def on_error(self, on_error: Literal["return", "raise"]) -> Self:
        """Answer the LLM with a call's error (``"return"``, the default), or
        fail the node (``"raise"``)."""
        self.kwargs["on_error"] = on_error
        return self
