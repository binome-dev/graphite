"""Tests for the CallableComponent base (grafi.common.callable_component)."""

import pytest

from grafi.common.callable_component import CallableComponent


class Multiplier(CallableComponent):
    factor: int

    def __call__(self, x: int) -> int:
        return x * self.factor


def test_subclass_is_callable_with_config():
    component = Multiplier(factor=3)
    assert component(4) == 12
    assert component.model_dump() == {"factor": 3}


def test_incomplete_subclass_cannot_be_instantiated():
    # __call__ is abstract: a subclass that omits it fails fast at construction
    # (e.g. when a manifest loads) rather than later at call time.
    class NoImpl(CallableComponent):
        pass

    with pytest.raises(TypeError, match="abstract"):
        NoImpl()
