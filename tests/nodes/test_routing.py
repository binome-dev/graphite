"""Unit tests for the hooked node's routing components (isolated, no engine)."""

from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.conditions import always_true
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.nodes.routing import ConsumerRouter
from grafi.nodes.routing import Entry
from grafi.nodes.routing import Stage
from grafi.nodes.routing import is_approved
from grafi.topics.topic_base import TopicBase


def _ctx() -> InvokeContext:
    return InvokeContext(conversation_id="c", invoke_id="i", assistant_request_id="r")


def _tool_call(name: str = "do_thing", args: str = '{"x": 1}') -> Message:
    return Message(
        role="assistant",
        tool_calls=[
            ChatCompletionMessageToolCall(
                id="call_1",
                type="function",
                function=Function(name=name, arguments=args),
            )
        ],
    )


def _consume(name: str, data, consumed_event_ids=None) -> ConsumeFromTopicEvent:
    return ConsumeFromTopicEvent(
        name=name,
        consumer_name="node",
        consumer_type="Node",
        invoke_context=_ctx(),
        offset=0,
        consumed_event_ids=consumed_event_ids or [],
        data=data,
    )


def _publish(data, name: str = "") -> PublishToTopicEvent:
    return PublishToTopicEvent(
        name=name,
        publisher_name="node",
        publisher_type="Node",
        invoke_context=_ctx(),
        offset=0,
        consumed_event_ids=[],
        data=data,
    )


# --------------------------------------------------------------------------- #
# is_approved verdict heuristic
# --------------------------------------------------------------------------- #
class TestIsApproved:
    def test_empty_is_not_approved(self):
        assert is_approved([]) is False

    def test_echoed_tool_call_is_approved(self):
        assert is_approved([_tool_call()]) is True

    def test_approval_words(self):
        for word in ("approve", "Approved", "yes", "y", "OK", "okay."):
            assert is_approved([Message(role="user", content=word)]) is True

    def test_denial_text(self):
        for word in ("no", "deny", "stop", "absolutely not"):
            assert is_approved([Message(role="user", content=word)]) is False

    def test_non_string_content_is_not_approved(self):
        assert is_approved([Message(role="assistant", content=None)]) is False


# --------------------------------------------------------------------------- #
# ConsumerRouter.classify
# --------------------------------------------------------------------------- #
class TestConsumerRouter:
    def test_default_routes_to_pre_hook(self):
        router = ConsumerRouter()
        batch = [
            _consume("input", [Message(role="user", content="hi")]),
            _consume("input", [Message(role="user", content="there")]),
        ]
        d = router.classify(batch)
        assert d.entry is Entry.PRE_HOOK
        assert d.source_events == batch
        assert d.recover_event_ids is None

    def test_pre_hitl_approve_routes_to_tool(self):
        router = ConsumerRouter(pre_hitl_input="pre_in")
        d = router.classify([_consume("pre_in", [Message(role="user", content="yes")])])
        assert d.entry is Entry.TOOL
        assert d.recover_event_ids is None

    def test_pre_hitl_deny_routes_to_publisher(self):
        router = ConsumerRouter(pre_hitl_input="pre_in")
        d = router.classify([_consume("pre_in", [Message(role="user", content="no")])])
        assert d.entry is Entry.PUBLISHER
        assert d.recover_event_ids is None

    def test_post_hitl_approve_recovers_from_store(self):
        router = ConsumerRouter(post_hitl_input="post_in")
        d = router.classify(
            [
                _consume(
                    "post_in",
                    [Message(role="user", content="approve")],
                    consumed_event_ids=["review-1"],
                )
            ]
        )
        assert d.entry is Entry.PUBLISHER
        assert d.recover_event_ids == ["review-1"]

    def test_post_hitl_deny_forwards_reply(self):
        router = ConsumerRouter(post_hitl_input="post_in")
        d = router.classify(
            [
                _consume(
                    "post_in",
                    [Message(role="user", content="no")],
                    consumed_event_ids=["review-1"],
                )
            ]
        )
        assert d.entry is Entry.PUBLISHER
        assert d.recover_event_ids is None

    def test_custom_verdict_predicate(self):
        router = ConsumerRouter(
            pre_hitl_input="pre_in",
            verdict=lambda msgs: msgs[-1].content == "go",
        )
        assert (
            router.classify(
                [_consume("pre_in", [Message(role="user", content="go")])]
            ).entry
            is Entry.TOOL
        )
        assert (
            router.classify(
                [_consume("pre_in", [Message(role="user", content="yes")])]
            ).entry
            is Entry.PUBLISHER
        )

    def test_multiple_pre_hitl_events_classified_together(self):
        router = ConsumerRouter(pre_hitl_input="pre_in")
        d = router.classify(
            [
                _consume("pre_in", [Message(role="user", content="some context")]),
                _consume("pre_in", [Message(role="user", content="yes")]),
            ]
        )
        # verdict runs over the flattened messages of every resume event
        assert d.entry is Entry.TOOL
        assert len(d.source_events) == 2

    def test_multiple_post_hitl_events_union_recover_ids(self):
        router = ConsumerRouter(post_hitl_input="post_in")
        d = router.classify(
            [
                _consume(
                    "post_in",
                    [Message(role="user", content="ok")],
                    consumed_event_ids=["r1"],
                ),
                _consume(
                    "post_in",
                    [Message(role="user", content="approve")],
                    consumed_event_ids=["r2"],
                ),
            ]
        )
        assert d.entry is Entry.PUBLISHER
        assert d.recover_event_ids == ["r1", "r2"]
        assert len(d.source_events) == 2

    def test_pre_hitl_event_takes_priority_over_normal(self):
        router = ConsumerRouter(pre_hitl_input="pre_in")
        d = router.classify(
            [
                _consume("input", [Message(role="user", content="normal")]),
                _consume("pre_in", [Message(role="user", content="yes")]),
            ]
        )
        assert d.entry is Entry.TOOL
        assert [e.name for e in d.source_events] == ["pre_in"]

    def test_source_route_selects_entry_by_topic(self):
        router = ConsumerRouter(source_routes={"replay": Entry.PUBLISHER})
        d = router.classify([_consume("replay", [Message(role="user", content="x")])])
        assert d.entry is Entry.PUBLISHER
        assert [e.name for e in d.source_events] == ["replay"]

    def test_source_route_groups_messages_from_same_source(self):
        router = ConsumerRouter(source_routes={"replay": Entry.TOOL})
        d = router.classify(
            [
                _consume("replay", [Message(role="user", content="a")]),
                _consume("replay", [Message(role="user", content="b")]),
            ]
        )
        assert d.entry is Entry.TOOL
        assert len(d.source_events) == 2

    def test_unrouted_source_defaults_to_pre_hook(self):
        router = ConsumerRouter(source_routes={"replay": Entry.PUBLISHER})
        d = router.classify([_consume("fresh", [Message(role="user", content="x")])])
        assert d.entry is Entry.PRE_HOOK

    def test_hitl_channel_takes_priority_over_source_route(self):
        # the verdict-driven HITL channel wins even if the topic is also in
        # source_routes
        router = ConsumerRouter(
            pre_hitl_input="hitl", source_routes={"hitl": Entry.PUBLISHER}
        )
        d = router.classify([_consume("hitl", [Message(role="user", content="yes")])])
        assert d.entry is Entry.TOOL  # approve via verdict, not the source_route

    def test_serialization_round_trip(self):
        router = ConsumerRouter(
            pre_hitl_input="pre_in",
            post_hitl_input="post_in",
            source_routes={"replay": Entry.PUBLISHER, "fast": Entry.TOOL},
        )
        restored = ConsumerRouter.from_dict(router.to_dict())
        assert restored.pre_hitl_input == "pre_in"
        assert restored.post_hitl_input == "post_in"
        assert restored.verdict is is_approved
        assert restored.source_routes == {
            "replay": Entry.PUBLISHER,
            "fast": Entry.TOOL,
        }


# --------------------------------------------------------------------------- #
# PublisherRouter pause channels (from_stage routes, added with the hooks)
# --------------------------------------------------------------------------- #
class TestPublisherPauseRoutes:
    def test_directed_name_overrides_content(self):
        fc = TopicBase(name="function_call")
        router = PublisherRouter(routes=[PublishRoute(topic=fc)])
        # a pause event names its channel; content routing is bypassed
        event = _publish([_tool_call()], name="pre_hitl_out")
        assert router.select(event) == ["pre_hitl_out"]

    def test_pause_route_excluded_from_content(self):
        out = TopicBase(name="agent_output")
        pause = TopicBase(name="pre_hitl_out")
        router = PublisherRouter(
            routes=[
                PublishRoute(topic=out, when=always_true),
                PublishRoute(topic=pause, when=always_true, from_stage=Stage.PRE_HOOK),
            ]
        )
        # from_stage routes never match content, even with always_true
        assert router.select(_publish([Message(role="assistant", content="x")])) == [
            "agent_output"
        ]

    def test_request_topic_names_the_pause_channel(self):
        out = TopicBase(name="agent_output")
        pause = TopicBase(name="pre_hitl_out")
        router = PublisherRouter(
            routes=[
                PublishRoute(topic=out),
                PublishRoute(topic=pause, from_stage=Stage.PRE_HOOK),
            ]
        )
        assert router.request_topic(Stage.PRE_HOOK) == "pre_hitl_out"

    def test_serialization_round_trip_with_pause_route(self):
        out = TopicBase(name="agent_output")
        pause = TopicBase(name="pre_hitl_out")
        router = PublisherRouter(
            routes=[
                PublishRoute(topic=out),
                PublishRoute(topic=pause, from_stage=Stage.PRE_HOOK),
            ]
        )
        topics = {t.name: t for t in router.publish_to}
        restored = PublisherRouter.from_dict(router.to_dict(), topics)
        assert restored.routes[1].from_stage is Stage.PRE_HOOK
        assert restored.request_topic(Stage.PRE_HOOK) == "pre_hitl_out"
