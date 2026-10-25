import functools
import json
import warnings
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import pytest
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic_core import PydanticSerializationError

from grafi.common.callable_component import CallableComponent
from grafi.common.decorators.llm_function import llm_function
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.event_stores import EventStoreInMemory
from grafi.common.import_ref import UntrustedImportError
from grafi.common.manifest import ManifestError
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.command import Command
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.function_call_tool import _spec
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.tool import Tool


class SampleFunction(FunctionCallTool):
    name: str = "SampleFunction"

    @llm_function
    def test_func(self, arg1: str, arg2: int) -> str:
        """A test function.

        Args:
            arg1 (str): A string argument.
            arg2 (int): An integer argument.

        Returns:
            str: The result of the function.
        """
        return f"{arg1} - {arg2}"


class ComplexMock(BaseModel):
    name: str = "Alice"
    age: Optional[int] = None
    birthday: datetime


class ComplexFunction(FunctionCallTool):
    name: str = "SampleFunction"

    @llm_function
    def test_func(self, arg1: List[Dict[str, Any]], arg2: Optional[ComplexMock]) -> str:
        """A test function.

        Args:
            arg1 (List[Dict[str, Any]]): A list of dictionaries.
            arg2 (Optional[ComplexMock]): An optional complex mock object.

        Returns:
            str: The result of the function.
        """
        return json.dumps(
            {"arg1": arg1, "arg2": arg2.model_dump_json() if arg2 else None}
        )


def look_up(city: str) -> str:
    """Look a city up.

    Args:
        city (str): The city to look up.

    Returns:
        str: What was found.
    """
    return f"found {city}"


FUNCTION_CALL_TOOL = "grafi.tools.function_calls.function_call_tool:FunctionCallTool"


@pytest.fixture
def event_store():
    return EventStoreInMemory()


@pytest.fixture
def invoke_context(event_store):
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def function_instance(event_store) -> SampleFunction:
    return SampleFunction()


def test_init(function_instance):
    assert isinstance(function_instance.get_function_specs(), List)
    assert callable(function_instance._functions()["test_func"])


def test_auto_register_function(function_instance):
    assert "test_func" in function_instance._functions()
    assert isinstance(function_instance.get_function_specs(), List)
    assert function_instance.get_function_specs()[0].name == "test_func"


def test_get_function_specs(function_instance):
    specs = function_instance.get_function_specs()
    assert isinstance(specs, List)
    assert specs[0].name == "test_func"
    assert isinstance(specs[0].parameters, ParametersSchema)
    assert "arg1" in specs[0].parameters.properties
    assert "arg2" in specs[0].parameters.properties


@pytest.mark.asyncio
async def test_invoke(function_instance, invoke_context):
    input_data = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {
                        "name": "test_func",
                        "arguments": json.dumps({"arg1": "hello", "arg2": 42}),
                    },
                }
            ],
        )
    ]
    msgs = await function_instance.invoke(invoke_context, input_data)
    for msg in msgs:
        assert msg.content == "hello - 42"


@pytest.mark.asyncio
async def test_invoke_wrong_function_name(function_instance, invoke_context):
    input_data = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {
                        "name": "wrong_func",
                        "arguments": json.dumps({"arg1": "hello", "arg2": 42}),
                    },
                }
            ],
        )
    ]
    # A call to a function the tool lacks is answered with the error.
    [answer] = await function_instance.invoke(invoke_context, input_data)
    assert answer.tool_call_id == "test_id"
    assert answer.content.startswith("Error: LookupError: No function 'wrong_func'")


def test_dump_saves_neither_the_specs_nor_the_classs_own_methods(function_instance):
    result = function_instance.model_dump(mode="json")
    assert result["class"] == f"{__name__}:SampleFunction"
    assert result["name"] == "SampleFunction"
    assert result["type"] == "FunctionCallTool"
    assert result["on_error"] == "return"
    # @llm_function methods are not saved: they load with the class.
    assert result["functions"] == {}
    # What the LLM is offered follows from the functions, so it is not saved.
    assert "function_specs" not in result  # Those it derives follow from it.


@pytest.mark.parametrize(
    "args,expected",
    [
        ({"arg1": "hello", "arg2": 42}, "hello - 42"),
        ({"arg1": "test", "arg2": 0}, "test - 0"),
    ],
)
@pytest.mark.asyncio
async def test_invoke_with_different_args(
    function_instance, invoke_context, args, expected
):
    input_data = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {"name": "test_func", "arguments": json.dumps(args)},
                }
            ],
        )
    ]
    msgs = await function_instance.invoke(invoke_context, input_data)
    for msg in msgs:
        assert msg.content == expected


@pytest.mark.asyncio
async def test_invoke_with_missing_args(function_instance, invoke_context):
    input_data = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {
                        "name": "test_func",
                        "arguments": json.dumps({"arg1": "hello"}),
                    },
                }
            ],
        )
    ]
    # Answered with the validation error, which the LLM can correct.
    [answer] = await function_instance.invoke(invoke_context, input_data)
    assert answer.content.startswith("Error: ValidationError")
    assert "arg2" in answer.content

    from grafi.common.exceptions import FunctionCallException

    function_instance.on_error = "raise"
    with pytest.raises(FunctionCallException):
        msgs = await function_instance.invoke(invoke_context, input_data)
        assert msgs  # should not reach here


def test_function_without_llm_decorator():
    with warnings.catch_warnings(record=True) as w:
        print(w)  # Not sure what do with this line

        # Define class without @llm_function decorator
        class InvalidFunction(FunctionCallTool):
            def test_func(self, arg: str) -> str:
                return arg.upper()

        # Verify function_specs not set since no decorated method
        invalid_instance = InvalidFunction()
        assert hasattr(invalid_instance, "function_specs")


def test_multiple_llm_functions():
    with warnings.catch_warnings(record=True) as w:
        # Define class with multiple @llm_function decorators
        class MultiFunction(FunctionCallTool):
            @llm_function
            def func1(self, arg: str) -> str:
                return arg.upper()

            @llm_function
            def func2(self, arg: str) -> str:
                return arg.lower()

        # Create instance
        multi = MultiFunction()

        # Should use first decorated function found
        assert "func1" in multi._functions()
        assert isinstance(multi.get_function_specs(), List)
        assert multi.get_function_specs()[0].name == "func1"

        # No warning since at least one decorated function exists
        assert len(w) == 0


def test_function_spec_structure(function_instance):
    spec = function_instance.get_function_specs()
    assert isinstance(spec, List)
    assert spec[0].name == "test_func"
    assert isinstance(spec[0].description, str)
    assert isinstance(spec[0].parameters, ParametersSchema)
    assert "arg1" in spec[0].parameters.properties
    assert "arg2" in spec[0].parameters.properties
    assert spec[0].parameters.properties["arg1"].type == "string"
    assert spec[0].parameters.properties["arg2"].type == "integer"


def test_complex_function_invocation():
    complex_function = ComplexFunction()
    arg1 = [{"key1": "value1"}, {"key2": 2}]
    arg2 = ComplexMock(name="Alice", age=30, birthday=datetime(1993, 1, 1))

    result = complex_function.test_func(arg1=arg1, arg2=arg2)
    result_dict = json.loads(result)

    assert result_dict["arg1"] == arg1
    assert result_dict["arg2"] == arg2.model_dump_json()


@pytest.mark.parametrize("cls", [SampleFunction, ComplexFunction])
def test_round_trip_loads_the_classs_methods_with_it(cls):
    tool = cls()
    data = tool.model_dump(mode="json")

    restored = FunctionCallTool.model_validate(data)

    assert type(restored) is cls
    assert restored.tool_id == tool.tool_id
    assert restored.name == tool.name
    assert restored.type == tool.type
    assert restored.get_function_specs() == tool.get_function_specs()
    assert restored._functions() == {"test_func": cls.test_func}
    assert restored == tool
    assert restored.model_dump(mode="json") == data


@pytest.mark.asyncio
async def test_round_trip_keeps_the_functions_the_builder_added(invoke_context):
    tool = SampleFunction.builder().function(look_up).on_error("raise").build()
    data = tool.model_dump(mode="json")
    assert data["functions"] == {"look_up": {"ref": f"{__name__}:look_up"}}
    assert "function_specs" not in data  # Those it derives follow from it.
    assert [spec.name for spec in tool.get_function_specs()] == ["test_func", "look_up"]
    assert data["on_error"] == "raise"

    restored = Tool.model_validate(data)

    assert type(restored) is SampleFunction
    assert restored.tool_id == tool.tool_id
    assert restored._functions() == {
        "test_func": SampleFunction.test_func,
        "look_up": look_up,
    }
    assert restored.get_function_specs() == tool.get_function_specs()
    assert restored.on_error == "raise"
    assert restored == tool
    assert restored.model_dump(mode="json") == data
    calls = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "a",
                "type": "function",
                "function": {
                    "name": "test_func",
                    "arguments": json.dumps({"arg1": "x", "arg2": 1}),
                },
            },
            {
                "id": "b",
                "type": "function",
                "function": {
                    "name": "look_up",
                    "arguments": json.dumps({"city": "Paris"}),
                },
            },
        ],
    )
    answers = await restored.invoke(invoke_context, [calls])
    assert [answer.content for answer in answers] == ["x - 1", "found Paris"]


def test_a_plain_function_call_tool_round_trips():
    tool = FunctionCallTool.builder().function(look_up).build()
    data = tool.model_dump(mode="json")
    assert data["class"] == FUNCTION_CALL_TOOL

    restored = Tool.model_validate(data)

    assert type(restored) is FunctionCallTool
    assert restored._functions() == {"look_up": look_up}
    assert restored == tool


def test_a_function_loaded_without_a_spec_gets_one_derived():
    data = {
        "class": FUNCTION_CALL_TOOL,
        "functions": {"look_up": {"ref": f"{__name__}:look_up"}},
    }

    tool = Tool.model_validate(data)

    assert [spec.name for spec in tool.get_function_specs()] == ["look_up"]
    assert tool.get_function_specs()[0].parameters.properties["city"].type == "string"
    assert tool._functions() == {"look_up": look_up}


def test_a_function_that_cannot_be_referenced_is_not_saved():
    def nested(city: str) -> str:
        """A function no manifest can name."""
        return city

    tool = FunctionCallTool.builder().function(nested).build()

    with pytest.raises(PydanticSerializationError, match="Cannot serialize callable"):
        tool.model_dump(mode="json")


def test_a_function_from_an_untrusted_module_is_not_loaded():
    data = {"class": FUNCTION_CALL_TOOL, "functions": {"getcwd": {"ref": "os:getcwd"}}}

    with pytest.raises(UntrustedImportError):
        Tool.model_validate(data)


def test_a_function_that_is_not_found_is_not_loaded():
    data = {
        "class": FUNCTION_CALL_TOOL,
        "functions": {"gone": {"ref": f"{__name__}:gone"}},
    }

    with pytest.raises(ManifestError, match="Cannot import"):
        Tool.model_validate(data)


def _call(call_id: str, name: str, arguments: Dict[str, Any]) -> Message:
    return Message(
        role="assistant",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    )


@pytest.mark.asyncio
async def test_a_function_keyed_under_another_name_is_offered_under_its_key(
    invoke_context,
):
    tool = FunctionCallTool(functions={"weather": look_up})
    data = tool.model_dump(mode="json")
    assert data["functions"] == {"weather": {"ref": f"{__name__}:look_up"}}

    restored = Tool.model_validate(data)

    for loaded in (tool, restored):
        [spec] = loaded.get_function_specs()
        assert spec.name == "weather"
        assert spec.description == "Look a city up."
        assert list(spec.parameters.properties) == ["city"]
        [weather, own_name] = await loaded.invoke(
            invoke_context,
            [_call("a", "weather", {"city": "Oslo"}), _call("b", "look_up", {})],
        )
        assert weather.content == "found Oslo"
        # Not offered under the function's own name.
        assert own_name.content.startswith("Error: LookupError")


def test_saving_and_loading_again_does_not_grow_the_specs():
    tool = SampleFunction.builder().function(look_up).build()

    for _ in range(3):
        tool = Tool.model_validate(tool.model_dump(mode="json"))
        tool = FunctionCallTool.model_validate(tool.model_dump())

    assert [spec.name for spec in tool.get_function_specs()] == ["test_func", "look_up"]
    assert list(tool._functions()) == ["test_func", "look_up"]


def test_a_python_dump_round_trips_with_the_functions_themselves():
    tool = SampleFunction.builder().function(look_up).on_error("raise").build()

    data = tool.model_dump()

    assert data["class"] is SampleFunction
    assert data["functions"] == {"look_up": look_up}
    assert "function_specs" not in data  # Those it derives follow from it.
    restored = FunctionCallTool.model_validate(data)
    assert type(restored) is SampleFunction
    assert restored == tool
    assert restored.get_function_specs() == tool.get_function_specs()


def test_the_specs_loaded_are_the_functions_own():
    """A manifest holds no spec, so what a loaded tool offers is what its
    functions are now: no saved description can go stale."""
    data = SampleFunction.builder().function(look_up).build().model_dump(mode="json")

    restored = Tool.model_validate(data)

    assert [spec.description for spec in restored.get_function_specs()] == [
        SampleFunction.test_func._function_spec.description,
        look_up._function_spec.description,
    ]


def test_a_spec_given_for_its_own_function_is_replaced_and_warned_of():
    """A function's spec follows from it: one given for it is not offered,
    in code and in a manifest alike, and what is saved loads."""
    tool = FunctionCallTool.builder().function(look_up).build()
    edited = [
        {
            "name": "look_up",
            "description": "An edited description.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    warned = r"offers its own functions \['look_up'\] in place of the specs"

    with pytest.warns(UserWarning, match=warned):
        given = Tool.model_validate({**tool.model_dump(), "function_specs": edited})
    assert given.get_function_specs() == tool.get_function_specs()
    with pytest.warns(UserWarning, match=warned):
        loaded = Tool.from_manifest(given.to_manifest())
    assert loaded.get_function_specs() == tool.get_function_specs()
    assert loaded.to_manifest() == given.to_manifest()


class Doubler(CallableComponent):
    def __call__(self, x: int) -> int:
        return 2 * x


def test_a_function_call_tool_refuses_what_is_not_a_function():
    with pytest.raises(TypeError, match="calls functions, not Doubler"):
        FunctionCallTool.builder().function(Doubler()).build()
    # When it is made, so it never saves what could not be loaded.
    with pytest.raises(TypeError, match="calls functions, not partial"):
        FunctionCallTool(functions={"add": functools.partial(look_up, "x")})


def test_code_using_the_removed_streaming_hooks_fails_loudly() -> None:
    """They would be ignored: a tool that streamed message by message would
    publish, store and route every piece."""
    with pytest.raises(TypeError, match="is_streaming was removed"):
        Message(role="assistant", content="Hel", is_streaming=True)  # type: ignore[call-arg]
    # Messages stored before still load.
    stored = Message.model_validate({"role": "assistant", "is_streaming": True})
    assert stored.role == "assistant"

    with pytest.warns(UserWarning, match="to_messages\\(\\) is never called"):

        class Old(FunctionCallTool):
            def to_messages(self, response: Any) -> List[Message]:
                return []

    with pytest.warns(UserWarning, match="to_stream_messages\\(\\) is never"):

        class OldLLM(OpenAITool):
            def to_stream_messages(self, chunks: Any) -> List[Message]:
                return []

    with pytest.warns(UserWarning, match="to_messages\\(\\) is never called"):

        class OldFunctionTool(FunctionTool):
            def to_messages(self, response: Any) -> List[Message]:
                return []


def test_a_tool_or_command_that_still_yields_fails_loudly() -> None:
    """Their output is returned now: a yielding one would fail on every run,
    with an error not saying why."""
    with pytest.raises(TypeError, match="OldTool.invoke\\(\\) yields: a tool returns"):

        class OldTool(Tool):
            @record_tool_invoke
            async def invoke(self, invoke_context, input_data):  # type: ignore
                yield [Message(role="assistant", content="hi")]

    with pytest.raises(TypeError, match="OldCommand.invoke\\(\\) yields"):

        class OldCommand(Command):
            async def invoke(self, invoke_context, input_data):  # type: ignore
                yield []

    with pytest.raises(TypeError, match="SyncTool.invoke\\(\\) is not async def"):

        class SyncTool(Tool):
            def invoke(self, invoke_context, input_data):  # type: ignore
                return []


class _LegacyMessages:
    """A mixin with a method grafi called in 0.0.36 and earlier."""

    def to_messages(self, response: Any) -> List[Message]:
        return []


def test_a_removed_method_from_a_mixin_is_warned_of() -> None:
    """Warned of, not refused: a helper of that name may be the tool's own."""
    with pytest.warns(UserWarning, match="to_messages\\(\\) is never called"):

        class Mixed(_LegacyMessages, FunctionCallTool):
            pass

    assert Mixed().get_function_specs() == []  # Built, and usable.


class _LegacyMessagesToo(_LegacyMessages):
    """A mixin taking the method on from its base."""


class _AnotherMixin(_LegacyMessages):
    """Another, taking it on too."""


def test_a_removed_method_from_a_mixins_base_is_warned_of_once() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        class Mixed(_LegacyMessagesToo, FunctionCallTool):
            pass

        class MixedAgain(_AnotherMixin, Mixed):  # Mixed has it already.
            pass

    warned = [str(w.message) for w in caught if "to_messages" in str(w.message)]
    assert warned == [
        "Mixed.to_messages() is never called by grafi, which called it in "
        "0.0.36 and earlier: a function's result becomes its call's answer as "
        "grafi.tools.results.as_text() makes it: shape the answer in the "
        "function instead."
    ]


class RemoteSearch(FunctionCallTool):
    """Calls functions elsewhere, offering the specs it is given."""

    async def call_function(
        self, invoke_context: InvokeContext, name: str, arguments: Dict[str, Any]
    ) -> Any:
        return f"found {arguments['q']}"


def test_the_specs_a_tool_is_given_are_saved():
    """Only the specs it makes follow from it: those it is given are its data."""
    spec = FunctionSpec(
        name="search",
        description="Search the web.",
        parameters=ParametersSchema(
            properties={"q": ParameterSchema(type="string")}, required=["q"]
        ),
    )
    tool = RemoteSearch(function_specs=[spec])

    loaded = Tool.from_manifest(json.loads(json.dumps(tool.to_manifest())))

    assert loaded.get_function_specs() == [spec]


class AppendingSpecs(FunctionCallTool):
    """The pattern before grafi v2: a spec appended as the tool is set up."""

    def model_post_init(self, context: Any) -> None:
        super().model_post_init(context)
        self.function_specs.append(
            FunctionSpec(name="lookup", description="Look up.", parameters={})
        )


def test_specs_appended_as_a_tool_is_set_up_are_offered_once():
    """Saved, and appended again on loading, they never grow."""
    tool = AppendingSpecs()
    for _ in range(3):
        tool = Tool.from_manifest(json.loads(json.dumps(tool.to_manifest())))

    assert [spec.name for spec in tool.get_function_specs()] == ["lookup"]
    assert len(tool.to_manifest()["spec"]["function_specs"]) <= 2


class SetUpOnItsOwn(FunctionCallTool):
    """Sets itself up without calling its base's model_post_init, as tools
    written for grafi before v2 did."""

    def model_post_init(self, context: Any) -> None:
        self.name = "set up"

    @llm_function
    def forecast(self, city: str) -> str:
        """Tomorrow's weather."""
        return f"Rain in {city}"


@pytest.mark.asyncio
async def test_a_tools_functions_need_no_call_to_its_bases_set_up():
    tool = SetUpOnItsOwn()
    call = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "forecast", "arguments": '{"city": "Oslo"}'},
                }
            ],
        }
    )
    context = InvokeContext(
        conversation_id="c", invoke_id="i", assistant_request_id="r"
    )

    [answer] = await tool.invoke(context, [call])

    assert tool.name == "set up"
    assert [spec.name for spec in tool.get_function_specs()] == ["forecast"]
    assert answer.content == "Rain in Oslo"


class OffersElsewhere(FunctionCallTool):
    """Offers a function it does not have, and calls none elsewhere."""


@pytest.mark.asyncio
async def test_a_function_offered_but_not_called_elsewhere_is_answered_unknown():
    spec = FunctionSpec(name="remote", description="Remote.", parameters={})
    tool = OffersElsewhere(function_specs=[spec])
    call = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "remote", "arguments": "{}"},
                }
            ],
        }
    )
    context = InvokeContext(
        conversation_id="c", invoke_id="i", assistant_request_id="r"
    )

    [answer] = await tool.invoke(context, [call])

    assert answer.content == "Error: LookupError: No function 'remote'"


class Strict(FunctionCallTool):
    """Revalidates every assignment."""

    model_config = ConfigDict(validate_assignment=True)
    seen: List[str] = Field(default_factory=list, exclude=True)

    def model_post_init(self, context: Any) -> None:
        self.seen = [spec.name for spec in self.get_function_specs()]

    @llm_function
    def ping(self) -> str:
        """Ping."""
        return "pong"


def test_set_up_needs_no_assignment_and_is_seen_in_model_post_init():
    """Its class's functions are merged as they are read: nothing is set
    that revalidation would set again, and model_post_init sees them."""
    tool = Strict()
    tool.name = "renamed"  # Revalidated.

    assert tool.seen == ["ping"]
    assert [spec.name for spec in tool.get_function_specs()] == ["ping"]


class AddsAsItSetsUp(FunctionCallTool):
    """Gives itself a function and its spec as it is set up, as grafi's
    builders did in 0.0.36 and earlier."""

    def model_post_init(self, context: Any) -> None:
        self.functions["look_up"] = look_up
        self.function_specs.append(_spec(look_up))


def test_a_spec_added_for_its_own_function_as_it_sets_up_is_warned_of():
    """The code adding it is no longer needed; the function's own is offered."""
    with pytest.warns(UserWarning, match=r"its own functions \['look_up'\]"):
        tool = AddsAsItSetsUp()

    assert [spec.name for spec in tool.get_function_specs()] == ["look_up"]


def test_a_removed_method_is_warned_of_once_where_it_is_written():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        class Old(FunctionCallTool):
            def to_messages(self, response: Any) -> List[Message]:
                return []

        class Older(Old):
            pass

    [warning] = [w for w in caught if "to_messages" in str(w.message)]
    assert warning.filename == __file__


def test_a_parameters_type_is_declared_and_saved_only_when_given():
    typed = ParameterSchema(type="string", description="A city.")
    untyped = ParameterSchema(description="Anything.")

    assert typed.model_dump() == {"type": "string", "description": "A city."}
    assert untyped.model_dump() == {"description": "Anything."}
