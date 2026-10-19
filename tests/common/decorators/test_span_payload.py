"""Tests for the payloads record_base sets on spans."""

import json

import pytest

from grafi.common.decorators.record_base import _set_payload


class _Span:
    def __init__(self, recording: bool) -> None:
        self.recording = recording
        self.attributes: dict = {}

    def is_recording(self) -> bool:
        return self.recording

    def set_attribute(self, key, value) -> None:
        self.attributes[key] = value


@pytest.fixture(autouse=True)
def _default_settings(monkeypatch):
    monkeypatch.delenv("GRAFI_SPAN_DISABLE_PAYLOADS", raising=False)
    monkeypatch.delenv("GRAFI_SPAN_MAX_PAYLOAD_CHARS", raising=False)


def _payload(value, recording: bool = True):
    span = _Span(recording)
    _set_payload(span, "input", value)
    return span.attributes.get("input")


def test_a_payload_is_set_as_json():
    assert json.loads(_payload({"a": 1})) == {"a": 1}


def test_a_large_payload_is_truncated(monkeypatch):
    monkeypatch.setenv("GRAFI_SPAN_MAX_PAYLOAD_CHARS", "50")
    assert _payload("x" * 1000) == '"' + "x" * 49 + "...[truncated 952 chars]"


def test_an_invalid_limit_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("GRAFI_SPAN_MAX_PAYLOAD_CHARS", "not-a-number")
    assert _payload("x" * 20_000).endswith("...[truncated 10002 chars]")


def test_a_zero_limit_keeps_the_whole_payload(monkeypatch):
    monkeypatch.setenv("GRAFI_SPAN_MAX_PAYLOAD_CHARS", "0")
    assert _payload("x" * 20_000) == '"' + "x" * 20_000 + '"'


def test_payloads_can_be_disabled(monkeypatch):
    monkeypatch.setenv("GRAFI_SPAN_DISABLE_PAYLOADS", "true")
    assert _payload({"secret": "value"}) is None


def test_a_span_not_recording_gets_no_payload():
    assert _payload({"a": 1}, recording=False) is None


def test_a_value_json_cannot_hold_is_set_as_its_repr():
    class Weird:
        def __repr__(self) -> str:
            return "WEIRD"

    assert _payload(Weird()) == '"WEIRD"'


def _circular() -> list:
    circular: list = []
    circular.append(circular)
    return circular


@pytest.mark.parametrize("value", ["\ud800", b"\xff", _circular()])
def test_a_value_json_cannot_encode_is_set_as_its_repr(value):
    assert _payload(value) == repr(value)
