"""Tests for EventCodec (Phase 6): registry-based event decoding."""

from datetime import datetime

import pytest

from grafi.common.events.event import Event
from grafi.common.events.event import EventType
from grafi.common.events.event_codec import EventCodec
from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


def test_default_codec_knows_builtin_event_types():
    assert (
        default_event_codec.event_class(EventType.PUBLISH_TO_TOPIC.value)
        is PublishToTopicEvent
    )


def test_decode_missing_event_type_returns_none():
    assert default_event_codec.decode({"event_id": "x"}) is None


def test_decode_unknown_event_type_returns_none():
    assert default_event_codec.decode({"event_id": "x", "event_type": "NOPE"}) is None


def test_decode_roundtrips_a_known_event():
    event = PublishToTopicEvent(
        event_id="evt-1",
        name="t",
        offset=0,
        publisher_name="p",
        publisher_type="t",
        consumed_event_ids=[],
        invoke_context=InvokeContext(
            conversation_id="c", invoke_id="i", assistant_request_id="r"
        ),
        data=[Message(role="user", content="hi")],
        timestamp=datetime(2026, 1, 1),
    )
    decoded = default_event_codec.decode(event.to_dict())
    assert isinstance(decoded, PublishToTopicEvent)
    assert decoded.event_id == "evt-1"


def test_register_adds_a_new_event_type_without_touching_the_store():
    codec = EventCodec()
    assert codec.event_class(EventType.TOPIC_EVENT.value) is None

    class _Custom(Event):
        pass

    codec.register("custom_type", _Custom)
    assert codec.event_class("custom_type") is _Custom


@pytest.mark.asyncio
async def test_store_delegates_decoding_to_codec():
    """EventStore._create_event_from_dict is a thin delegate over the codec."""
    from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory

    store = EventStoreInMemory()
    assert store._create_event_from_dict({"event_id": "x"}) is None
