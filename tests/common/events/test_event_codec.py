"""Tests for EventCodec: registry-based encoding and decoding of stored events."""

import json
from datetime import datetime
from datetime import timezone

import pytest
from pydantic import ValidationError

from grafi.common.events.component_events import NodeInvokeEvent
from grafi.common.events.event import EVENT_VERSION
from grafi.common.events.event import Event
from grafi.common.events.event import EventType
from grafi.common.events.event_codec import EventCodec
from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import EventSerializationError
from grafi.common.import_ref import reference_to
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from tests.events.event_fixtures import every_event
from tests.events.event_fixtures import round_trip
from tests.events.event_fixtures import stored


def publication(**fields) -> PublishToTopicEvent:
    return PublishToTopicEvent(
        **{
            "event_id": "evt-1",
            "name": "t",
            "offset": 0,
            "publisher_name": "p",
            "publisher_type": "t",
            "invoke_context": InvokeContext(
                conversation_id="c", invoke_id="i", assistant_request_id="r"
            ),
            "data": [Message(role="user", content="hi")],
            "timestamp": datetime(2026, 1, 1),
            **fields,
        }
    )


def test_default_codec_knows_builtin_event_types():
    assert (
        default_event_codec.event_class(EventType.PUBLISH_TO_TOPIC.value)
        is PublishToTopicEvent
    )


@pytest.mark.parametrize("event_type", list(EventType), ids=lambda t: t.value)
def test_default_codec_decodes_every_event_type_to_its_class(event_type: EventType):
    event_class = default_event_codec.event_class(event_type.value)
    assert event_class.model_fields["event_type"].default is event_type
    assert event_class.__module__.startswith("grafi.common.events.")
    assert reference_to(event_class) is not None  # Importable by its name.


@pytest.mark.parametrize(
    "event_class, other",
    [
        (TopicEvent, EventType.PUBLISH_TO_TOPIC),
        (PublishToTopicEvent, EventType.TOPIC_EVENT),
        (NodeInvokeEvent, EventType.NODE_RESPOND),
    ],
)
def test_an_event_holds_only_its_own_event_type(event_class, other: EventType):
    own = event_class.model_fields["event_type"].default
    fields = stored(every_event_of(event_class))

    with pytest.raises(ValidationError, match=f"not {other.value!r}"):
        event_class.model_validate({**fields, "event_type": other.value})
    assert event_class.model_validate(fields).event_type is own


def every_event_of(event_class) -> Event:
    return next(e for e in every_event() if type(e) is event_class)


@pytest.mark.parametrize("event", every_event(), ids=lambda event: event.event_id)
def test_every_event_round_trips_through_json(event: Event):
    encoded = stored(event)
    assert encoded["event_version"] == EVENT_VERSION == 2
    assert encoded["event_type"] == event.event_type.value
    assert "event_context" not in encoded
    decoded = default_event_codec.decode(encoded)
    assert type(decoded) is type(event)
    assert decoded == event


@pytest.mark.parametrize("version", [1, "1.0", 3, "2"])
def test_an_event_is_built_only_of_this_version(version):
    """An earlier version is read by upgrading it first, never built as is."""
    with pytest.raises(ValidationError, match="event_version"):
        publication(event_version=version)
    assert publication(event_version=2).event_version == EVENT_VERSION


def test_encode_is_the_events_json_form():
    event = publication()
    assert default_event_codec.encode(event) == event.model_dump(mode="json")
    assert json.loads(json.dumps(default_event_codec.encode(event))) == (
        default_event_codec.encode(event)
    )


def test_decode_roundtrips_a_known_event():
    event = publication()
    decoded = default_event_codec.decode(stored(event))
    assert isinstance(decoded, PublishToTopicEvent)
    assert decoded == event


@pytest.mark.parametrize(
    "event_dict",
    [
        {"event_id": "x", "event_version": 2},
        {"event_id": "x", "event_version": 2, "event_type": None},
        {"event_id": "x", "event_version": "1.0"},
    ],
    ids=["missing", "null", "version-1"],
)
def test_decode_without_event_type_raises(event_dict):
    with pytest.raises(EventSerializationError, match="unknown event type"):
        default_event_codec.decode(event_dict)


@pytest.mark.parametrize("version", [2, "1.0"])
def test_decode_unknown_event_type_raises(version):
    with pytest.raises(EventSerializationError, match="NOPE"):
        default_event_codec.decode(
            {**stored(publication()), "event_version": version, "event_type": "NOPE"}
        )


def test_decode_newer_version_raises():
    with pytest.raises(EventSerializationError, match="version 3"):
        default_event_codec.decode({**stored(publication()), "event_version": 3})


def test_decode_missing_version_raises():
    event_dict = stored(publication())
    del event_dict["event_version"]
    with pytest.raises(EventSerializationError, match="version None"):
        default_event_codec.decode(event_dict)


@pytest.mark.parametrize("version", ["2", "2.0", "1", 1.0, 2.0, True, None])
def test_decode_unknown_version_raises(version):
    with pytest.raises(EventSerializationError):
        default_event_codec.decode({**stored(publication()), "event_version": version})


def test_decode_invalid_event_raises_with_its_cause():
    # A known type, but missing the fields its class requires.
    with pytest.raises(EventSerializationError, match="cannot be decoded") as raised:
        default_event_codec.decode(
            {"event_id": "x", "event_version": 2, "event_type": "NodeInvoke"}
        )
    assert raised.value.__cause__ is not None
    assert raised.value.cause is raised.value.__cause__


def test_decode_invalid_field_raises():
    event_dict = {**stored(publication()), "offset": "not a number"}
    with pytest.raises(EventSerializationError, match="evt-1"):
        default_event_codec.decode(event_dict)


def test_decode_invalid_version_1_event_raises():
    # Version 1, but without the event context version 1 kept its fields in.
    with pytest.raises(EventSerializationError, match="cannot be decoded"):
        default_event_codec.decode(
            {
                "event_id": "x",
                "event_version": "1.0",
                "event_type": "PublishToTopic",
                "timestamp": "2026-01-01T00:00:00",
                "data": "[]",
            }
        )


def test_decode_does_not_change_its_input():
    event_dict = stored(publication())
    before = json.loads(json.dumps(event_dict))
    default_event_codec.decode(event_dict)
    assert event_dict == before


def test_encode_refuses_an_event_of_a_type_it_does_not_decode():
    class _Unregistered(Event):
        event_type: str = "Unregistered"  # type: ignore[assignment]

    event = _Unregistered(event_id="u", invoke_context=publication().invoke_context)

    with pytest.raises(EventSerializationError, match="register it"):
        default_event_codec.encode(event)


def test_encode_refuses_a_subclass_of_the_class_its_type_decodes_as():
    """A subclass would be read back as its base, losing what it adds."""

    class _Annotated(PublishToTopicEvent):
        note: str = "kept?"

    event = _Annotated(**publication().model_dump())

    with pytest.raises(EventSerializationError, match="_Annotated.*'PublishToTopic'"):
        default_event_codec.encode(event)
    codec = EventCodec({"PublishToTopic": _Annotated})
    assert codec.decode(codec.encode(event)) == event


def test_register_adds_a_new_event_type_without_touching_the_store():
    codec = EventCodec()
    assert codec.event_class(EventType.TOPIC_EVENT.value) is None

    class _Custom(Event):
        pass

    codec.register("custom_type", _Custom)
    assert codec.event_class("custom_type") is _Custom
    assert default_event_codec.event_class("custom_type") is None


def test_a_registered_event_type_round_trips():
    class _Audit(Event):
        event_type: str = "Audit"  # type: ignore[assignment]
        note: str

    codec = EventCodec()
    codec.register("Audit", _Audit)
    event = _Audit(
        note="checked",
        invoke_context=InvokeContext(
            conversation_id="c", invoke_id="i", assistant_request_id="r"
        ),
    )
    encoded = json.loads(json.dumps(codec.encode(event)))
    assert encoded["event_type"] == "Audit"
    assert codec.decode(encoded) == event


def test_message_tools_given_as_a_generator_are_kept_as_a_list():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search the web.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    message = Message(role="user", content="hi", tools=(tool for tool in tools))
    assert message.tools == tools
    event = publication(data=[message])
    assert stored(event)["data"][0]["tools"] == tools
    assert stored(event)["data"][0]["tools"] == tools  # Not used up by the first.
    decoded = round_trip(event)
    assert decoded == event
    assert decoded.data[0].tools == tools


@pytest.mark.parametrize("value", [object(), {"nested": object()}, [1, object()]])
def test_invoke_context_kwargs_json_cannot_hold_are_refused(value):
    with pytest.raises(ValidationError, match=r"kwargs\['client'\] cannot be stored"):
        InvokeContext(
            conversation_id="c",
            invoke_id="i",
            assistant_request_id="r",
            kwargs={"user": "ada", "client": value},
        )


def test_an_event_whose_context_was_changed_to_hold_an_object_cannot_be_encoded():
    event = publication()
    event.invoke_context.kwargs["client"] = object()  # Not validated.

    with pytest.raises(EventSerializationError, match="evt-1.*cannot be encoded"):
        default_event_codec.encode(event)


def test_invoke_context_kwargs_with_a_datetime_encode():
    at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    context = InvokeContext(
        conversation_id="c",
        invoke_id="i",
        assistant_request_id="r",
        kwargs={"at": at, "nested": {"at": at}, "tags": ("a", "b")},
    )
    event = publication(invoke_context=context)
    encoded = stored(event)
    assert encoded["invoke_context"]["kwargs"] == {
        "at": "2026-01-02T03:04:05Z",
        "nested": {"at": "2026-01-02T03:04:05Z"},
        "tags": ["a", "b"],
    }
    # Decoded, the kwargs are their JSON values: the datetime as its ISO text.
    decoded = default_event_codec.decode(encoded)
    assert decoded.invoke_context.kwargs == encoded["invoke_context"]["kwargs"]
    assert decoded.model_copy(update={"invoke_context": context}) == event
