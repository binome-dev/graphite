"""Tests for upcast_v1: reading the events version 1 stored, as grafi wrote
them from 0.0.26 on and, with other names, before."""

import copy
import json
from typing import Any
from typing import Dict
from typing import List

import pytest

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
