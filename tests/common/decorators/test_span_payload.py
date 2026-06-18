"""Tests for span payload bounding / redaction in record_base."""

from grafi.common.decorators.record_base import _DEFAULT_SPAN_MAX_PAYLOAD_CHARS
from grafi.common.decorators.record_base import _span_max_payload_chars
from grafi.common.decorators.record_base import _span_payload
from grafi.common.decorators.record_base import _span_payloads_disabled

ENV_DISABLE = "GRAFI_SPAN_DISABLE_PAYLOADS"
ENV_MAX = "GRAFI_SPAN_MAX_PAYLOAD_CHARS"


def test_small_payload_is_serialized_verbatim(monkeypatch):
    monkeypatch.delenv(ENV_DISABLE, raising=False)
    monkeypatch.delenv(ENV_MAX, raising=False)
    assert _span_payload({"a": 1}) == '{"a": 1}'


def test_large_payload_is_truncated(monkeypatch):
    monkeypatch.delenv(ENV_DISABLE, raising=False)
    monkeypatch.setenv(ENV_MAX, "50")
    payload = _span_payload({"data": "x" * 1000})
    assert "truncated" in payload
    assert len(payload) < 1000


def test_payloads_can_be_disabled(monkeypatch):
    monkeypatch.setenv(ENV_DISABLE, "true")
    assert _span_payloads_disabled() is True
    assert _span_payload({"secret": "value"}) is None


def test_default_max_chars(monkeypatch):
    monkeypatch.delenv(ENV_MAX, raising=False)
    assert _span_max_payload_chars() == _DEFAULT_SPAN_MAX_PAYLOAD_CHARS


def test_invalid_max_chars_falls_back_to_default(monkeypatch):
    monkeypatch.setenv(ENV_MAX, "not-a-number")
    assert _span_max_payload_chars() == _DEFAULT_SPAN_MAX_PAYLOAD_CHARS


def test_non_serializable_payload_uses_repr(monkeypatch):
    monkeypatch.delenv(ENV_DISABLE, raising=False)
    monkeypatch.delenv(ENV_MAX, raising=False)

    class Weird:
        def __repr__(self) -> str:
            return "WEIRD"

    # to_jsonable_python falls back; ensure we still get a string, not an error.
    result = _span_payload(Weird())
    assert isinstance(result, str)
