"""Tests for upcast_v1: reading the events version 1 stored, as grafi wrote
them from 0.0.26 on and, with other names, before."""

import copy
import json
import warnings
from typing import Any
from typing import Dict
from typing import List

import pytest
from pydantic import model_validator

from grafi.common.events.component_events import AssistantFailedEvent
from grafi.common.events.component_events import AssistantInvokeEvent
from grafi.common.events.component_events import NodeFailedEvent
from grafi.common.events.component_events import NodeRespondEvent
from grafi.common.events.component_events import ToolInvokeEvent
from grafi.common.events.component_events import ToolRespondEvent
from grafi.common.events.component_events import WorkflowRespondEvent
from grafi.common.events.event import Event
from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.event_v1 import upcast_v1
from grafi.common.exceptions import EventSerializationError
from grafi.common.models.invoke_context import InvokeContext
from tests.events.event_fixtures import HELLO_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_V1
from tests.events.event_fixtures import REPLY_JSON
from tests.events.event_fixtures import TIMESTAMP
from tests.events.event_fixtures import answers
from tests.events.event_fixtures import answers_json
from tests.events.event_fixtures import answers_v1
from tests.events.event_fixtures import hello
from tests.events.event_fixtures import invoke_context
from tests.events.event_fixtures import reply
from tests.events.event_fixtures import request
from tests.events.event_fixtures import request_json
from tests.events.event_fixtures import request_v1


def workflow_failed_v1() -> dict:
    return {
        "event_id": "failed",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "WorkflowFailed",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "id": "workflow_id",
            "name": "workflow",
            "type": "EventDrivenWorkflow",
            "component_type": "Workflow",
            "invoke_context": INVOKE_CONTEXT_V1,
        },
        "data": {
            "input_data": request_v1(),
            "error": "boom",
            "error_details": {"error_type": "ValueError", "message": "boom"},
        },
    }


def test_a_topic_event_is_flattened_and_its_messages_parsed():
    assert upcast_v1(request_v1()) == {
        "event_id": "test_id",
        "event_version": 2,
        "event_type": "PublishToTopic",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "consumed_event_ids": [],
        "publisher_name": "test_assistant",
        "publisher_type": "test_type",
        "name": "test_output_topic",
        "type": "AgentOutputTopic",
        "offset": -1,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "data": [HELLO_JSON],
    }


def test_a_component_event_is_flattened_with_its_nested_events():
    upcast = upcast_v1(workflow_failed_v1())
    assert upcast == {
        "event_id": "failed",
        "event_version": 2,
        "event_type": "WorkflowFailed",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "id": "workflow_id",
        "name": "workflow",
        "type": "EventDrivenWorkflow",
        "invoke_context": INVOKE_CONTEXT_JSON,
        "input_data": upcast_v1(request_v1()),
        "error": "boom",
        "error_details": {"error_type": "ValueError", "message": "boom"},
    }
    decoded = default_event_codec.decode(upcast)
    assert decoded.input_data == request()
    assert default_event_codec.encode(decoded.input_data) == request_json()


def test_a_list_of_nested_events_is_upcast():
    respond = {
        **workflow_failed_v1(),
        "event_type": "WorkflowRespond",
        "data": {"input_data": request_v1(), "output_data": answers_v1()},
    }
    decoded = default_event_codec.decode(respond)
    assert decoded.output_data == answers()
    assert [default_event_codec.encode(e) for e in decoded.output_data] == (
        answers_json()
    )


def test_upcasting_does_not_change_the_stored_event():
    stored = workflow_failed_v1()
    before = copy.deepcopy(stored)
    upcast_v1(stored)
    default_event_codec.decode(stored)
    assert stored == before


@pytest.mark.parametrize("context", [None, "not a mapping"], ids=["missing", "text"])
def test_an_event_without_its_context_raises(context: Any):
    """Version 1 holds an event's fields in its context; an event without one
    is not read."""
    event = request_v1()
    del event["event_context"]
    if context is not None:
        event["event_context"] = context

    match = "An event of version 1 holds its fields in 'event_context'"
    with pytest.raises(ValueError, match=match):
        upcast_v1(event)
    with pytest.raises(EventSerializationError, match=match):
        default_event_codec.decode(event)


class AuditEvent(Event):
    """An event type of a user's, which 0.0.36 stored in a layout of its own."""

    event_type: str = "Audit"  # type: ignore[assignment]
    note: str

    @model_validator(mode="before")
    @classmethod
    def _read_v1(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("event_version") == "1.0":
            data = {
                "event_id": data["event_id"],
                "timestamp": data["timestamp"],
                "invoke_context": data["context"],
                "note": data["payload"]["note"],
            }
        return data


def test_an_event_of_ones_own_in_grafis_layout_reaches_its_class_as_stored():
    """grafi's upgrade, which renames and flattens grafi's own fields, is not
    applied to a type of yours."""
    codec = default_event_codec.copy()
    codec.register("Audit", AuditEvent)
    stored = {
        "event_id": "audit-2",
        "event_version": "1.0",
        "event_type": "Audit",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "event_context": {"tool_name": "search"},
        "context": {
            "conversation_id": "c",
            "invoke_id": "i",
            "assistant_request_id": "r",
        },
        "payload": {"note": "as stored"},
    }

    assert codec.decode(stored).note == "as stored"


def test_an_event_class_of_ones_own_reads_its_v1_layout():
    codec = default_event_codec.copy()
    codec.register("Audit", AuditEvent)
    stored = {
        "event_id": "audit-1",
        "event_version": "1.0",
        "event_type": "Audit",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "context": {
            "conversation_id": "c",
            "invoke_id": "i",
            "assistant_request_id": "r",
        },
        "payload": {"note": "kept"},
    }

    event = codec.decode(stored)

    assert isinstance(event, AuditEvent)
    assert (event.note, event.invoke_context.conversation_id) == ("kept", "c")
    assert codec.decode(codec.encode(event)) == event


@pytest.mark.parametrize("missing", ["name", "type"])
def test_a_topic_event_without_its_topic_raises(missing: str):
    event = request_v1()
    del event["event_context"][missing]

    with pytest.raises(ValueError, match="names its topic and type"):
        upcast_v1(event)
    with pytest.raises(EventSerializationError, match="names its topic and type"):
        default_event_codec.decode(event)


# --------------------------------------------------------------------------- #
# Events grafi before 0.0.26 stored: the same form, with other names
# --------------------------------------------------------------------------- #


def _base(event_id: str, event_type: str) -> Dict[str, Any]:
    """What every event before 0.0.26 stored besides its context and data."""
    return {
        "event_id": event_id,
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": event_type,
        "timestamp": "2009-02-13T23:31:30+00:00",
    }


def request_0_0_25() -> Dict[str, Any]:
    """request(), as grafi 0.0.25 stored it: its topic as topic_name and
    topic_type."""
    return {
        **_base("test_id", "PublishToTopic"),
        "event_context": {
            "consumed_event_ids": [],
            "publisher_name": "test_assistant",
            "publisher_type": "test_type",
            "topic_name": "test_output_topic",
            "topic_type": "AgentOutputTopic",
            "offset": -1,
            "invoke_context": INVOKE_CONTEXT_V1,
        },
        "data": json.dumps([HELLO_JSON]),
    }


def answers_0_0_25() -> List[Dict[str, Any]]:
    """answers(), as grafi 0.0.25 stored them."""
    return [
        {
            **_base("test_id", "ConsumeFromTopic"),
            "event_context": {
                "consumer_name": "test_node",
                "consumer_type": "test_type",
                "topic_name": "test_topic",
                "topic_type": "AgentOutputTopic",
                "offset": -1,
                "invoke_context": INVOKE_CONTEXT_V1,
            },
            "data": json.dumps([HELLO_JSON, REPLY_JSON]),
        }
    ]


def _context(component: str) -> Dict[str, Any]:
    """A component event's context, as grafi 0.0.25 stored it: its fields
    prefixed with the component's kind."""
    return {
        f"{component}_id": f"{component}_id",
        f"{component}_name": component,
        f"{component}_type": component.capitalize(),
        "invoke_context": INVOKE_CONTEXT_V1,
    }


def _fields(component: str) -> Dict[str, Any]:
    """The fields of a component event decoded from _context(component)."""
    return {
        "id": f"{component}_id",
        "name": component,
        "type": component.capitalize(),
        "invoke_context": invoke_context(),
        "timestamp": TIMESTAMP,
    }


NODE_TOPICS = {
    "subscribed_topics": ["test_topic"],
    "publish_to_topics": ["test_output_topic"],
}


def _stored_and_decoded() -> List[Any]:
    """Each kind of event as grafi 0.0.25 stored it, and as it decodes."""
    return [
        (
            {
                **_base("node_respond", "NodeRespond"),
                "event_context": {**_context("node"), **NODE_TOPICS},
                "data": {
                    "input_data": answers_0_0_25(),
                    "output_data": request_0_0_25(),
                },
            },
            NodeRespondEvent(
                event_id="node_respond",
                input_data=answers(),
                output_data=request(),
                **NODE_TOPICS,
                **_fields("node"),
            ),
        ),
        (
            {
                **_base("node_failed", "NodeFailed"),
                "event_context": {**_context("node"), **NODE_TOPICS},
                "data": {"input_data": answers_0_0_25(), "error": "boom"},
            },
            NodeFailedEvent(
                event_id="node_failed",
                input_data=answers(),
                error="boom",
                **NODE_TOPICS,
                **_fields("node"),
            ),
        ),
        (
            {
                **_base("tool_invoke", "ToolInvoke"),
                "event_context": _context("tool"),
                "data": {"input_data": json.dumps([HELLO_JSON])},
            },
            ToolInvokeEvent(
                event_id="tool_invoke", input_data=[hello()], **_fields("tool")
            ),
        ),
        (
            {
                **_base("tool_respond", "ToolRespond"),
                "event_context": _context("tool"),
                "data": {
                    "input_data": json.dumps([HELLO_JSON]),
                    "output_data": json.dumps([REPLY_JSON]),
                },
            },
            ToolRespondEvent(
                event_id="tool_respond",
                input_data=[hello()],
                output_data=[reply()],
                **_fields("tool"),
            ),
        ),
        (
            {
                **_base("workflow_respond", "WorkflowRespond"),
                "event_context": _context("workflow"),
                "data": {
                    "input_event": request_0_0_25(),
                    "output_data": answers_0_0_25(),
                },
            },
            WorkflowRespondEvent(
                event_id="workflow_respond",
                input_data=request(),
                output_data=answers(),
                **_fields("workflow"),
            ),
        ),
        (
            {
                **_base("assistant_invoke", "AssistantInvoke"),
                "event_context": _context("assistant"),
                "data": {"input_event": request_0_0_25()},
            },
            AssistantInvokeEvent(
                event_id="assistant_invoke",
                input_data=request(),
                **_fields("assistant"),
            ),
        ),
        (
            {
                **_base("assistant_failed", "AssistantFailed"),
                "event_context": _context("assistant"),
                "data": {"input_event": request_0_0_25(), "error": "boom"},
            },
            AssistantFailedEvent(
                event_id="assistant_failed",
                input_data=request(),
                error="boom",
                **_fields("assistant"),
            ),
        ),
    ]


def test_topic_events_before_0_0_26_are_read():
    assert default_event_codec.decode(request_0_0_25()) == request()
    assert [default_event_codec.decode(e) for e in answers_0_0_25()] == answers()
    assert upcast_v1(request_0_0_25()) == upcast_v1(request_v1())


@pytest.mark.parametrize(
    "stored, event",
    _stored_and_decoded(),
    ids=[event.event_id for _, event in _stored_and_decoded()],
)
def test_component_events_before_0_0_26_are_read(stored: Dict[str, Any], event: Event):
    before = copy.deepcopy(stored)

    decoded = default_event_codec.decode(stored)

    assert type(decoded) is type(event)
    assert decoded == event
    assert stored == before
    # Stored again, it is of version 2, and reads back as itself.
    assert default_event_codec.decode(default_event_codec.encode(decoded)) == event


def test_a_later_revision_of_ones_own_type_is_upgraded_as_grafis(
    monkeypatch: pytest.MonkeyPatch,
):
    """From version 2 on, an event of a type of yours holds the fields grafi's
    Event gives it, so grafi's next upgrade reaches it too."""
    from grafi.common.events import event_codec

    upgraded: List[str] = []

    def upcast_v2(event: Dict[str, Any]) -> Dict[str, Any]:
        upgraded.append(event["event_type"])
        return {**event, "event_version": 2}  # As revision 3 would, simulated.

    monkeypatch.setattr(event_codec, "EVENT_VERSION", 3)
    monkeypatch.setitem(event_codec._UPCASTERS, 2, upcast_v2)
    codec = default_event_codec.copy()
    codec.register("Audit", AuditEvent)
    stored = AuditEvent(
        note="v2",
        invoke_context=InvokeContext(
            conversation_id="c", invoke_id="i", assistant_request_id="r"
        ),
    ).model_dump(mode="json")

    assert codec.decode(stored).note == "v2"
    assert upgraded == ["Audit"]


def test_an_events_to_dict_of_0036_is_warned_of() -> None:
    """Nothing calls it now: rows are the event's JSON form."""
    with pytest.warns(UserWarning, match=r"Legacy.to_dict\(\) is never called"):

        class Legacy(AuditEvent):
            def to_dict(self) -> Dict[str, Any]:
                return {}


class _LegacyToDict:
    """A mixin with 0.0.36's to_dict()."""

    def to_dict(self) -> Dict[str, Any]:
        return {}


def test_an_events_to_dict_from_a_mixin_is_warned_of() -> None:
    with pytest.warns(UserWarning, match=r"Mixed.to_dict\(\) is never called"):

        class Mixed(_LegacyToDict, AuditEvent):
            pass


def test_an_events_from_dict_classmethod_is_warned_of_once() -> None:
    """Not again for each subclass deriving it."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        class Legacy(AuditEvent):
            @classmethod
            def from_dict(cls, data: Dict[str, Any]) -> "Legacy":
                raise NotImplementedError

        class Child(Legacy):
            pass

    assert [str(w.message).split("(")[0] for w in caught] == ["Legacy.from_dict"]
