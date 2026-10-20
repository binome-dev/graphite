import json
import warnings
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import pytest
from pydantic import BaseModel
from pydantic_core import PydanticSerializationError

from grafi.common.callable_component import CallableComponent
from grafi.common.callable_ref import CallableSerializationError
from grafi.common.decorators.llm_function import llm_function
from grafi.common.event_stores import EventStoreInMemory
from grafi.common.import_ref import UntrustedImportError
from grafi.common.manifest import ManifestError
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
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
    assert isinstance(function_instance.function_specs, List)
    assert callable(function_instance.functions["test_func"])


def test_auto_register_function(function_instance):
    assert "test_func" in function_instance.functions
    assert isinstance(function_instance.function_specs, List)
    assert function_instance.function_specs[0].name == "test_func"


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
    async for msgs in function_instance.invoke(invoke_context, input_data):
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
    [answer] = [
        message
        async for messages in function_instance.invoke(invoke_context, input_data)
        for message in messages
    ]
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
    assert "function_specs" not in result


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
    async for msgs in function_instance.invoke(invoke_context, input_data):
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
    [answer] = [
        message
        async for messages in function_instance.invoke(invoke_context, input_data)
        for message in messages
    ]
    assert answer.content.startswith("Error: ValidationError")
    assert "arg2" in answer.content

    from grafi.common.exceptions import FunctionCallException

    function_instance.on_error = "raise"
    with pytest.raises(FunctionCallException):
        async for msgs in function_instance.invoke(invoke_context, input_data):
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
        assert "func1" in multi.functions
        assert isinstance(multi.function_specs, List)
        assert multi.function_specs[0].name == "func1"

        # No warning since at least one decorated function exists
        assert len(w) == 0


def test_function_spec_structure(function_instance):
    spec = function_instance.function_specs
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
    assert restored.function_specs == tool.function_specs
    assert restored.functions == {"test_func": cls.test_func}
    assert restored == tool
    assert restored.model_dump(mode="json") == data


@pytest.mark.asyncio
async def test_round_trip_keeps_the_functions_the_builder_added(invoke_context):
    tool = SampleFunction.builder().function(look_up).on_error("raise").build()
    data = tool.model_dump(mode="json")
    assert data["functions"] == {"look_up": {"ref": f"{__name__}:look_up"}}
    assert "function_specs" not in data
    assert [spec.name for spec in tool.function_specs] == ["test_func", "look_up"]
    assert data["on_error"] == "raise"

    restored = Tool.model_validate(data)

    assert type(restored) is SampleFunction
    assert restored.tool_id == tool.tool_id
    assert restored.functions == {
        "test_func": SampleFunction.test_func,
        "look_up": look_up,
    }
    assert restored.function_specs == tool.function_specs
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
    answers = [
        m async for batch in restored.invoke(invoke_context, [calls]) for m in batch
    ]
    assert [answer.content for answer in answers] == ["x - 1", "found Paris"]


def test_a_plain_function_call_tool_round_trips():
    tool = FunctionCallTool.builder().function(look_up).build()
    data = tool.model_dump(mode="json")
    assert data["class"] == FUNCTION_CALL_TOOL

    restored = Tool.model_validate(data)

    assert type(restored) is FunctionCallTool
    assert restored.functions == {"look_up": look_up}
    assert restored == tool


def test_a_function_loaded_without_a_spec_gets_one_derived():
    data = {
        "class": FUNCTION_CALL_TOOL,
        "functions": {"look_up": {"ref": f"{__name__}:look_up"}},
    }

    tool = Tool.model_validate(data)

    assert [spec.name for spec in tool.function_specs] == ["look_up"]
    assert tool.function_specs[0].parameters.properties["city"].type == "string"
    assert tool.functions == {"look_up": look_up}


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

    with pytest.raises(CallableSerializationError, match="Cannot import"):
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
        [spec] = loaded.function_specs
        assert spec.name == "weather"
        assert spec.description == "Look a city up."
        assert list(spec.parameters.properties) == ["city"]
        [weather, own_name] = [
            m
            async for batch in loaded.invoke(
                invoke_context,
                [_call("a", "weather", {"city": "Oslo"}), _call("b", "look_up", {})],
            )
            for m in batch
        ]
        assert weather.content == "found Oslo"
        # Not offered under the function's own name.
        assert own_name.content.startswith("Error: LookupError")


def test_saving_and_loading_again_does_not_grow_the_specs():
    tool = SampleFunction.builder().function(look_up).build()

    for _ in range(3):
        tool = Tool.model_validate(tool.model_dump(mode="json"))
        tool = FunctionCallTool.model_validate(tool.model_dump())

    assert [spec.name for spec in tool.function_specs] == ["test_func", "look_up"]
    assert list(tool.functions) == ["test_func", "look_up"]


def test_a_python_dump_round_trips_with_the_functions_themselves():
    tool = SampleFunction.builder().function(look_up).on_error("raise").build()

    data = tool.model_dump()

    assert data["class"] is SampleFunction
    assert data["functions"] == {"look_up": look_up}
    assert "function_specs" not in data
    restored = FunctionCallTool.model_validate(data)
    assert type(restored) is SampleFunction
    assert restored == tool
    assert restored.function_specs == tool.function_specs


def test_the_specs_loaded_are_the_functions_own():
    """A manifest holds no spec, so what a loaded tool offers is what its
    functions are now: no saved description can go stale."""
    data = SampleFunction.builder().function(look_up).build().model_dump(mode="json")

    restored = Tool.model_validate(data)

    assert [spec.description for spec in restored.function_specs] == [
        SampleFunction.test_func._function_spec.description,
        look_up._function_spec.description,
    ]


def test_an_edited_spec_cannot_be_loaded():
    """A function's spec follows from it: one given in the data for it is
    replaced, and a manifest holding one is refused."""
    tool = FunctionCallTool.builder().function(look_up).build()
    data = tool.model_dump(mode="json")
    data["function_specs"] = [
        {
            "name": "look_up",
            "description": "An edited description.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    loaded = Tool.model_validate(data)
    assert loaded.function_specs == tool.function_specs

    manifest = {"apiVersion": "grafi/v2", "kind": "Tool", "spec": data}
    with pytest.raises(ManifestError, match="never saved"):
        Tool.from_manifest(manifest)


class Doubler(CallableComponent):
    def __call__(self, x: int) -> int:
        return 2 * x


def test_a_function_call_tool_refuses_what_is_not_a_function():
    with pytest.raises(TypeError, match="calls functions, not Doubler"):
        FunctionCallTool.builder().function(Doubler()).build()

