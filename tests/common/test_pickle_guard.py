"""Tests for the pickle deserialization guard (security: RCE prevention)."""

import base64

import cloudpickle
import pytest

from grafi.common.exceptions import UnsafeDeserializationError
from grafi.common.pickle_guard import ENV_FLAG
from grafi.common.pickle_guard import is_pickle_deserialization_allowed
from grafi.common.pickle_guard import safe_b64_pickle_loads
from grafi.common.pickle_guard import safe_pickle_loads
from grafi.common.pickle_guard import set_pickle_deserialization_allowed


@pytest.fixture
def reset_guard():
    """Clear the process-wide override around a test, then restore it.

    The suite's conftest enables deserialization globally; these tests need to
    exercise the default-deny behavior, so they clear the override and restore
    it afterwards.
    """
    set_pickle_deserialization_allowed(None)
    yield
    set_pickle_deserialization_allowed(True)


def _payload() -> bytes:
    return cloudpickle.dumps(lambda x: True)


def _b64_payload() -> str:
    return base64.b64encode(_payload()).decode("utf-8")


def test_denied_by_default(reset_guard, monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    assert is_pickle_deserialization_allowed() is False
    with pytest.raises(UnsafeDeserializationError, match="Refusing to deserialize"):
        safe_pickle_loads(_payload(), context="unit test")


def test_error_message_mentions_context(reset_guard, monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    with pytest.raises(UnsafeDeserializationError, match="my-topic condition"):
        safe_b64_pickle_loads(_b64_payload(), context="my-topic condition")


def test_allowed_via_env(reset_guard, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "true")
    assert is_pickle_deserialization_allowed() is True
    fn = safe_pickle_loads(_payload())
    assert fn("anything") is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_falsy_env_values_deny(reset_guard, monkeypatch, value):
    monkeypatch.setenv(ENV_FLAG, value)
    assert is_pickle_deserialization_allowed() is False


def test_allowed_via_override(reset_guard, monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    set_pickle_deserialization_allowed(True)
    fn = safe_b64_pickle_loads(_b64_payload())
    assert fn("anything") is True


def test_trusted_flag_bypasses_policy(reset_guard, monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    # Even though policy denies, an explicit trusted=True call succeeds.
    fn = safe_pickle_loads(_payload(), trusted=True)
    assert fn("anything") is True


def test_override_takes_precedence_over_env(reset_guard, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "true")
    set_pickle_deserialization_allowed(False)
    assert is_pickle_deserialization_allowed() is False
