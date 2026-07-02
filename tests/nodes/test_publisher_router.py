"""Unit tests for the node's publisher router (isolated, no engine)."""

from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.topics.conditions import has_text_response
from grafi.topics.conditions import has_tool_call
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


def _publish(data, name: str = "") -> PublishToTopicEvent:
    return PublishToTopicEvent(
        name=name,
        publisher_name="node",
        publisher_type="Node",
        invoke_context=_ctx(),
        offset=0,
        data=data,
    )


class TestPublisherRouter:
    def _llm_router(self):
        fc = TopicBase(name="function_call")
        out = TopicBase(name="agent_output")
        return PublisherRouter(
            routes=[
                PublishRoute(topic=fc, when=has_tool_call),
                PublishRoute(topic=out, when=has_text_response),
            ]
        )

    def test_content_routes_tool_call(self):
        router = self._llm_router()
        assert router.select(_publish([_tool_call()])) == ["function_call"]

    def test_content_routes_text(self):
        router = self._llm_router()
        event = _publish([Message(role="assistant", content="the answer")])
        assert router.select(event) == ["agent_output"]

    def test_plain_node_selects_every_topic(self):
        a, b = TopicBase(name="a"), TopicBase(name="b")
        router = PublisherRouter(routes=[PublishRoute(topic=a), PublishRoute(topic=b)])
        # default when=always_true -> deliver to all
        assert router.select(_publish([Message(role="assistant", content="x")])) == [
            "a",
            "b",
        ]

    def test_predicate_error_is_treated_as_not_met(self):
        # has_tool_call indexes data[-1]; empty data raises IndexError -> omitted
        fc = TopicBase(name="function_call")
        router = PublisherRouter(routes=[PublishRoute(topic=fc, when=has_tool_call)])
        assert router.select(_publish([])) == []

    def test_publish_to_property_lists_all_topics(self):
        router = self._llm_router()
        assert [t.name for t in router.publish_to] == ["function_call", "agent_output"]

    def test_serialization_round_trip(self):
        router = self._llm_router()
        topics = {t.name: t for t in router.publish_to}
        restored = PublisherRouter.from_dict(router.to_dict(), topics)
        assert [r.topic.name for r in restored.routes] == [
            "function_call",
            "agent_output",
        ]
        assert restored.routes[0].when is has_tool_call
        assert restored.routes[1].when is has_text_response
