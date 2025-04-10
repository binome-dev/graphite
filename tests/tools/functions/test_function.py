import json
import warnings

import pytest

from grafi.common.decorators.llm_function import llm_function
from grafi.common.event_stores import EventStoreInMemory
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.message import Message
from grafi.tools.functions.function_tool import FunctionTool


class SampleFunction(FunctionTool):
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


@pytest.fixture
def event_store():
    return EventStoreInMemory()


@pytest.fixture
def execution_context(event_store):
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id="execution_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def function_instance(event_store):
    return SampleFunction()


def test_init(function_instance):
    assert isinstance(function_instance.function_specs, FunctionSpec)
    assert callable(function_instance.function)


def test_auto_register_function(function_instance):
    assert function_instance.function.__name__ == "test_func"
    assert isinstance(function_instance.function_specs, FunctionSpec)
    assert function_instance.function_specs.name == "test_func"


def test_get_function_specs(function_instance):
    specs = function_instance.get_function_specs()
    assert isinstance(specs, FunctionSpec)
    assert specs.name == "test_func"
    assert isinstance(specs.parameters, ParametersSchema)
    assert "arg1" in specs.parameters.properties
    assert "arg2" in specs.parameters.properties


def test_execute(function_instance, execution_context):
    input_data = Message(
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
    result = function_instance.execute(execution_context, input_data)
    assert result[0].content == "hello - 42"


def test_execute_wrong_function_name(function_instance, execution_context):
    input_data = Message(
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
    result = function_instance.execute(execution_context, input_data)
    assert len(result) == 0


def test_to_dict(function_instance):
    result = function_instance.to_dict()
    assert isinstance(result, dict)
    assert isinstance(result["function_specs"], dict)  # model_dump() returns dict
    assert result["name"] == "SampleFunction"
    assert result["type"] == "FunctionTool"
    assert result["function_specs"]["name"] == "test_func"
    assert result["function_specs"]["description"] is not None
    assert isinstance(result["function_specs"]["parameters"], dict)


@pytest.mark.parametrize(
    "args,expected",
    [
        ({"arg1": "hello", "arg2": 42}, "hello - 42"),
        ({"arg1": "test", "arg2": 0}, "test - 0"),
    ],
)
def test_execute_with_different_args(
    function_instance, execution_context, args, expected
):
    input_data = Message(
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
    result = function_instance.execute(execution_context, input_data)
    assert result[0].content == expected


def test_execute_with_missing_args(function_instance, execution_context):
    input_data = Message(
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
    with pytest.raises(TypeError):
        function_instance.execute(execution_context, input_data)


def test_function_without_llm_decorator():
    with warnings.catch_warnings(record=True) as w:
        print(w)  # Not sure what do with this line

        # Define class without @llm_function decorator
        class InvalidFunction(FunctionTool):
            def test_func(self, arg: str) -> str:
                return arg.upper()

        # Verify function_specs not set since no decorated method
        invalid_instance = InvalidFunction()
        assert hasattr(invalid_instance, "function_specs")


def test_multiple_llm_functions():
    with warnings.catch_warnings(record=True) as w:
        # Define class with multiple @llm_function decorators
        class MultiFunction(FunctionTool):
            @llm_function
            def func1(self, arg: str) -> str:
                return arg.upper()

            @llm_function
            def func2(self, arg: str) -> str:
                return arg.lower()

        # Create instance
        multi = MultiFunction()

        # Should use first decorated function found
        assert multi.function.__name__ == "func1"
        assert isinstance(multi.function_specs, FunctionSpec)
        assert multi.function_specs.name == "func1"

        # No warning since at least one decorated function exists
        assert len(w) == 0


def test_inherit_llm_function():
    # Test inheritance behavior
    class BaseFunction(FunctionTool):
        @llm_function
        def base_func(self, arg: str) -> str:
            return arg

    class ChildFunction(BaseFunction):
        pass

    child = ChildFunction()

    # Should inherit parent's decorated function
    assert child.function.__name__ == "base_func"
    assert isinstance(child.function_specs, FunctionSpec)
    assert child.function_specs.name == "base_func"


def test_function_spec_structure(function_instance):
    spec = function_instance.function_specs
    assert isinstance(spec, FunctionSpec)
    assert spec.name == "test_func"
    assert isinstance(spec.description, str)
    assert isinstance(spec.parameters, ParametersSchema)
    assert "arg1" in spec.parameters.properties
    assert "arg2" in spec.parameters.properties
    assert spec.parameters.properties["arg1"].type == "string"
    assert spec.parameters.properties["arg2"].type == "integer"
