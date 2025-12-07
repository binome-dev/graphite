import json
import warnings
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import pytest
from pydantic import BaseModel

from grafi.common.decorators.llm_function import llm_function
from grafi.common.event_stores import EventStoreInMemory
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


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
    async for msgs in function_instance.invoke(invoke_context, input_data):
        assert msgs == []


def test_to_dict(function_instance):
    result = function_instance.to_dict()
    assert isinstance(result, dict)
    assert isinstance(result["function_specs"], list)  # model_dump() returns dict
    assert result["name"] == "SampleFunction"
    assert result["type"] == "FunctionCallTool"
    assert result["function_specs"][0]["name"] == "test_func"
    assert result["function_specs"][0]["description"] is not None
    assert isinstance(result["function_specs"][0]["parameters"], dict)


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
    from grafi.common.exceptions import FunctionCallException

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


@pytest.mark.asyncio
async def test_function_call_deserialization(function_instance):
    function_call: SampleFunction = function_instance
    dict_representation = function_call.to_dict()

    deserialized_function: SampleFunction = await SampleFunction.from_dict(
        dict_representation
    )

    assert isinstance(deserialized_function, FunctionCallTool)
    assert deserialized_function.name == function_call.name
    assert deserialized_function.type == function_call.type
    assert deserialized_function.function_specs == function_call.function_specs


@pytest.mark.asyncio
async def test_complex_function_call_deserialization():
    complex_function = ComplexFunction()
    dict_representation = complex_function.to_dict()

    deserialized_function: ComplexFunction = await ComplexFunction.from_dict(
        dict_representation
    )

    assert isinstance(deserialized_function, FunctionCallTool)
    assert deserialized_function.name == complex_function.name
    assert deserialized_function.type == complex_function.type
    assert deserialized_function.function_specs == complex_function.function_specs
