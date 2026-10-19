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
    for setting in (
        "GRAFI_SPAN_DISABLE_PAYLOADS",
        "GRAFI_SPAN_MAX_PAYLOAD_CHARS",
        "OPENINFERENCE_HIDE_INPUTS",
        "OPENINFERENCE_HIDE_OUTPUTS",
    ):
        monkeypatch.delenv(setting, raising=False)


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


def _input_attributes(value) -> dict:
    span = _Span(recording=True)
    _set_payload(span, "input.value", value, "input.mime_type")
    return span.attributes


def test_a_payload_is_set_with_its_mime_type():
    assert _input_attributes({"a": 1}) == {
        "input.value": '{"a":1}',
        "input.mime_type": "application/json",
    }


def test_openinference_hides_inputs_as_on_llm_spans(monkeypatch):
    monkeypatch.setenv("OPENINFERENCE_HIDE_INPUTS", "true")
    assert _input_attributes({"secret": "value"}) == {"input.value": "__REDACTED__"}


def test_a_hidden_payload_is_never_serialized(monkeypatch):
    class Unserializable:
        def __repr__(self) -> str:
            raise AssertionError("serialized")

    monkeypatch.setenv("OPENINFERENCE_HIDE_INPUTS", "true")
    assert _input_attributes(Unserializable())["input.value"] == "__REDACTED__"


def test_a_payload_json_cannot_hold_or_cut_short_is_plain_text(monkeypatch):
    monkeypatch.setenv("GRAFI_SPAN_MAX_PAYLOAD_CHARS", "5")
    assert _input_attributes({"a": "long"})["input.mime_type"] == "text/plain"
    monkeypatch.delenv("GRAFI_SPAN_MAX_PAYLOAD_CHARS")
    assert _input_attributes(b"\xff")["input.mime_type"] == "text/plain"


def test_openinference_hides_outputs_only_where_asked(monkeypatch):
    monkeypatch.setenv("OPENINFERENCE_HIDE_OUTPUTS", "true")
    span = _Span(recording=True)
    _set_payload(span, "output.value", "answer", "output.mime_type")
    _set_payload(span, "input.value", "question", "input.mime_type")
    assert span.attributes == {
        "output.value": "__REDACTED__",
        "input.value": '"question"',
        "input.mime_type": "application/json",
    }
