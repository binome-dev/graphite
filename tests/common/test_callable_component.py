"""Tests for the CallableComponent base (grafi.common.callable_component)."""

import json

import pytest

from grafi.common.callable_component import CallableComponent
from grafi.common.manifest import Component


class Multiplier(CallableComponent):
    factor: int

    def __call__(self, x: int) -> int:
        return x * self.factor


def test_subclass_is_callable_with_config():
    component = Multiplier(factor=3)
    assert component(4) == 12
    assert component.model_dump() == {"class": Multiplier, "factor": 3}


def test_it_is_saved_as_a_component():
    component = Multiplier(factor=3)

    data = component.model_dump(mode="json")

    assert isinstance(component, Component)
    assert data == {"class": f"{__name__}:Multiplier", "factor": 3}
    loaded = CallableComponent.model_validate(json.loads(json.dumps(data)))
    assert type(loaded) is Multiplier
    assert loaded(4) == 12
    assert type(Component.from_manifest(component.to_manifest())) is Multiplier


def test_incomplete_subclass_cannot_be_instantiated():
    # __call__ is abstract: a subclass that omits it fails fast at construction
    # (e.g. when a manifest loads) rather than later at call time.
    class NoImpl(CallableComponent):
        pass

    with pytest.raises(TypeError, match="abstract"):
        NoImpl()
    with pytest.raises(TypeError, match="abstract"):
        CallableComponent()
