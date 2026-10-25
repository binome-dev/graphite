import asyncio
import functools
import inspect
import json
import warnings
from typing import Any
from typing import Callable
from typing import ClassVar
from typing import Dict
from typing import Literal
from typing import Self
from typing import Set
from typing import Tuple
from typing import TypeVar
from typing import get_type_hints

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from pydantic import validate_call

from grafi.common.async_lifecycle import wait_all
from grafi.common.callable_ref import CallableRef
from grafi.common.decorators.llm_function import is_invoke_context
from grafi.common.decorators.llm_function import llm_function
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.exceptions import FunctionCallException
from grafi.common.exceptions import ToolInvocationError
from grafi.common.exceptions.serialization import error_message
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.function_spec import GivenSpecs
from grafi.common.models.function_spec import once_each
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import ChatCompletionMessageToolCall
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.runtime.deltas import deltas_for
from grafi.tools.command import use_command
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.results import as_text
from grafi.tools.results import call
from grafi.tools.results import function_results
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

    It is saved with the functions its class does not define, by reference
    (see :mod:`grafi.common.callable_ref`), and the specs it is given; the
    specs of its functions follow from them.
    """

    name: str = "FunctionCallTool"
    type: str = "FunctionCallTool"
    # The specs of functions it calls elsewhere, such as an MCP server's, which
    # it is given; those of its own it derives (see get_function_specs()).
    function_specs: GivenSpecs = Field(
        default_factory=list, exclude_if=lambda specs: not specs
    )
    functions: Dict[str, CallableRef] = Field(default_factory=dict)
    # "raise" fails the call's node instead of answering the LLM with the error.
    on_error: Literal["return", "raise"] = "return"
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    # The class's @llm_function methods, its bases' included, by name.
    _methods: ClassVar[Dict[str, Any]] = {}

    removed_methods: ClassVar[Dict[str, str]] = {
        "to_messages": "a function's result becomes its call's answer as "
        "grafi.tools.results.as_text() makes it: shape the answer in the "
        "function instead.",
    }

    @classmethod
    def builder(cls) -> "FunctionCallToolBuilder[Self]":
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

    @model_validator(mode="after")
    def _check_specs(self) -> Self:
        """Make the specs it derives now, so a function no spec can be made of
        fails (TypeError); and warn of a spec it is given for one of its own
        functions, which the function's own spec replaces."""
        given = {spec.name for spec in self.function_specs}
        shadowed = sorted(given & self.derived_specs().keys())
        if shadowed:
            warnings.warn(
                f"{type(self).__name__} offers its own functions {shadowed} in "
                "place of the specs it is given of those names. Its "
                "function_specs are those of functions it calls elsewhere (see "
                "call_function()), such as an MCP server's tools, which a "
                "function of its own of the same name hides; a spec of its own "
                "function, or made from its fields, is derived (see "
                "derived_specs()), so code adding one, as in model_post_init, "
                "can go.",
                UserWarning,
            )
        return self

    def _functions(self) -> Dict[str, Callable]:
        """The functions it calls itself: its class's, then those it is given,
        which replace one of the same name."""
        return {**type(self)._methods, **self.functions}

    def derived_specs(self) -> Dict[str, FunctionSpec]:
        """The specs the tool derives, by name, never saved: each function's,
        named as it is keyed. A subclass offering a function it makes from its
        fields, as AgentCallingTool does, adds its spec."""
        derived = {}
        for name, function in self._functions().items():
            spec = _spec(function)
            derived[name] = (
                spec if spec.name == name else spec.model_copy(update={"name": name})
            )
        return derived

    def get_function_specs(self) -> FunctionSpecs:
        """What the LLM is offered: the specs the tool derives, then those it
        is given, once each by name."""
        return once_each([*self.derived_specs().values(), *self.function_specs])

    @record_tool_invoke
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> Messages:
        """Answer every tool call in ``input_data``, concurrently: one tool
        message per call, in the calls' order."""
        calls = [c for message in input_data for c in message.tool_calls or []]
        offered = {spec.name for spec in self.get_function_specs()}
        own = self._functions()
        answering = [
            asyncio.ensure_future(self._answer(invoke_context, c, offered, own))
            for c in calls
        ]
        try:
            return list(await asyncio.gather(*answering))
        except BaseException as error:
            for task in answering:
                task.cancel()
            # Never abandoned; a cancellation meanwhile outranks a failure.
            if await wait_all(answering) and isinstance(error, Exception):
                raise asyncio.CancelledError() from error
            raise

    async def _answer(
        self,
        invoke_context: InvokeContext,
        call: ChatCompletionMessageToolCall,
        offered: Set[str],
        own: Dict[str, Callable],
    ) -> Message:
        name = call.function.name
        try:
            if name not in offered:
                raise LookupError(f"No function {name!r}")
            arguments = json.loads(call.function.arguments or "{}")
            run = self._call_own if name in own else self.call_function
            with deltas_for(call.id):  # What the function streams is the call's.
                results = await function_results(
                    functools.partial(run, invoke_context, name, arguments)
                )
            content = "\n".join(as_text(result) for result in results)
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
        """Call ``name``, a function the tool offers (see
        ``get_function_specs()``) but does not have, with the LLM's
        ``arguments``, and return what it returns, a value or a generator.
        Override it to call functions elsewhere, as MCPTool does on a server,
        and AgentCallingTool does an agent: the tool calls its own functions
        itself."""
        raise LookupError(f"No function {name!r}")

    async def _call_own(
        self, invoke_context: InvokeContext, name: str, arguments: Dict[str, Any]
    ) -> Any:
        """Call the tool's function ``name`` with the LLM's ``arguments``,
        validated against its signature, and return what it returns. A
        parameter typed ``InvokeContext`` is passed ``invoke_context``, and
        ``self`` this tool."""
        function = self._functions()[name]
        method = function is type(self)._methods.get(name)
        if method:  # Called as the tool's method, so an override runs.
            function = getattr(type(self), name, function)
        validated, contexts, takes_self = _calling(function)
        arguments = {**arguments, **dict.fromkeys(contexts, invoke_context)}
        if method or takes_self:
            validated = functools.partial(validated, self)
        return await call(functools.partial(validated, **arguments))


def _spec(function: Callable) -> FunctionSpec:
    """The ``@llm_function`` specification of ``function``, made if need be."""
    spec = getattr(function, "_function_spec", None)
    if isinstance(spec, FunctionSpec):
        return spec
    if not inspect.isfunction(function):
        raise TypeError(
            f"A function-call tool calls functions, not {type(function).__name__}: "
            "give it a function, or an @llm_function method of the tool's class."
        )
    return llm_function(function)._function_spec  # type: ignore[attr-defined]


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
        """Add a function that can be called by the LLM, under the name of its
        ``@llm_function`` specification, made if it has none; it replaces one
        of the same name. It may be sync or async, or a generator; one whose
        first parameter is ``self`` is passed this tool.

        Args:
            function: A callable to expose as a tool function.

        Returns:
            Self for method chaining.
        """
        self.kwargs.setdefault("functions", {})[_spec(function).name] = function
        return self

    def on_error(self, on_error: Literal["return", "raise"]) -> Self:
        """Answer the LLM with a call's error (``"return"``, the default), or
        fail the node (``"raise"``)."""
        self.kwargs["on_error"] = on_error
        return self
