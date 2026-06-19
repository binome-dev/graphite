"""Tests for pickle-free callable (de)serialization (grafi.common.callable_ref)."""

import pytest

from grafi.common.callable_component import CallableComponent
from grafi.common.callable_ref import CallableSerializationError
from grafi.common.callable_ref import deserialize_callable
from grafi.common.callable_ref import serialize_callable


def module_level_function(x: int) -> int:
    """A stable, importable callable -> serializes as a reference."""
    return x + 1


class Adder(CallableComponent):
    """A configurable callable -> serializes as component config."""

    amount: int

    def __call__(self, x: int) -> int:
        return x + self.amount


# --- reference form -------------------------------------------------------


def test_module_level_function_serializes_as_reference():
    assert serialize_callable(module_level_function) == {
        "ref": f"{__name__}:module_level_function"
    }


def test_reference_roundtrips_to_same_object():
    restored = deserialize_callable(serialize_callable(module_level_function))
    assert restored is module_level_function
    assert restored(41) == 42


# --- component form -------------------------------------------------------


def test_component_serializes_as_config():
    assert serialize_callable(Adder(amount=5)) == {
        "component": f"{__name__}:Adder",
        "config": {"amount": 5},
    }


def test_component_roundtrips():
    restored = deserialize_callable(serialize_callable(Adder(amount=5)))
    assert isinstance(restored, Adder)
    assert restored(10) == 15


def test_component_reference_to_non_component_rejected():
    with pytest.raises(CallableSerializationError, match="not a CallableComponent"):
        deserialize_callable({"component": f"{__name__}:module_level_function"})


# --- no pickle: hard errors -----------------------------------------------


def test_lambda_cannot_be_serialized():
    with pytest.raises(CallableSerializationError, match="without pickle"):
        serialize_callable(lambda x: x > 0)


def test_closure_cannot_be_serialized():
    def make_adder(n):
        def adder(x):
            return x + n

        return adder

    with pytest.raises(CallableSerializationError, match="without pickle"):
        serialize_callable(make_adder(10))


def test_legacy_base64_string_is_rejected():
    with pytest.raises(CallableSerializationError, match="pickle payload"):
        deserialize_callable("gASVbase64blob", context="function")


def test_legacy_base64_dict_is_rejected():
    with pytest.raises(CallableSerializationError, match="pickle payload"):
        deserialize_callable({"base64": "blob", "code": "lambda _: True"})


def test_malformed_reference_raises():
    with pytest.raises(CallableSerializationError, match="Malformed import reference"):
        deserialize_callable({"ref": "no_separator_here"})


def test_reference_to_non_callable_raises():
    with pytest.raises(CallableSerializationError, match="non-callable"):
        deserialize_callable({"ref": f"{__name__}:__doc__"})


def test_dict_without_known_keys_raises():
    with pytest.raises(CallableSerializationError, match="ref.*component"):
        deserialize_callable({"unexpected": "value"})
