"""Unit tests for the node's publisher router (isolated, no engine)."""

from typing import Callable

import pytest
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.import_ref import UntrustedImportError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.conditions import always_true
from grafi.nodes.conditions import has_text_response
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_types import TopicType


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
    def test_duplicate_destinations_evaluate_all_predicates_then_deduplicate(
        self,
    ) -> None:
        a, b = TopicBase(name="a"), TopicBase(name="b")
        calls: list[str] = []

        def condition(
            label: str, matched: bool
        ) -> Callable[[PublishToTopicEvent], bool]:
            def predicate(event: PublishToTopicEvent) -> bool:
                calls.append(label)
                return matched

            return predicate

        router = PublisherRouter(
            routes=[
                PublishRoute(topic=a, when=condition("a-false", False)),
                PublishRoute(topic=b, when=condition("b", True)),
                PublishRoute(topic=a, when=condition("a-true", True)),
                PublishRoute(topic=b, when=condition("b-again", True)),
            ]
        )
        assert router.select(_publish([])) == ["b", "a"]
        assert calls == ["a-false", "b", "a-true", "b-again"]

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

        data = router.model_dump(mode="json")

        # Topics are saved by name, predicates by import reference.
        assert data == {
            "routes": [
                {
                    "topic": "function_call",
                    "when": {"ref": "grafi.nodes.conditions:has_tool_call"},
                },
                {
                    "topic": "agent_output",
                    "when": {"ref": "grafi.nodes.conditions:has_text_response"},
                },
            ]
        }

        restored = PublisherRouter.model_validate(data, context={"topics": topics})
        assert [r.topic.name for r in restored.routes] == [
            "function_call",
            "agent_output",
        ]
        assert restored.routes[0].topic is topics["function_call"]
        assert restored.routes[1].topic is topics["agent_output"]
        assert restored.routes[0].when is has_tool_call
        assert restored.routes[1].when is has_text_response
        assert restored.model_dump(mode="json") == data

    def test_default_predicate_round_trips_by_reference(self):
        a = TopicBase(name="a")
        router = PublisherRouter(routes=[PublishRoute(topic=a)])

        data = router.model_dump(mode="json")

        assert data["routes"][0]["when"] == {
            "ref": "grafi.nodes.conditions:always_true"
        }
        restored = PublisherRouter.model_validate(data, context={"topics": {"a": a}})
        assert restored.routes[0].when is always_true

    def test_user_predicate_round_trips_by_reference(self):
        # A module-level function of a trusted module (the test's own, trusted
        # by conftest) is saved by reference and imported back.
        a = TopicBase(name="a")
        router = PublisherRouter(routes=[PublishRoute(topic=a, when=_is_urgent)])

        data = router.model_dump(mode="json")

        assert data["routes"][0]["when"] == {"ref": f"{__name__}:_is_urgent"}
        restored = PublisherRouter.model_validate(data, context={"topics": {"a": a}})
        assert restored.routes[0].when is _is_urgent

    def test_python_dump_keeps_predicate_and_topic(self):
        router = self._llm_router()

        data = router.model_dump()

        # The topic in full, and the predicate itself.
        assert data["routes"][0]["topic"] == {
            "class": TopicBase,
            "name": "function_call",
            "type": TopicType.DEFAULT_TOPIC_TYPE,
        }
        assert data["routes"][0]["when"] is has_tool_call
        # It loads back in this process, on its own
        restored = PublisherRouter.model_validate(data)
        assert [route.topic.name for route in restored.routes] == [
            "function_call",
            "agent_output",
        ]
        assert [route.when for route in restored.routes] == [
            has_tool_call,
            has_text_response,
        ]
        # or naming the topics it is given.
        topics = {route.topic.name: route.topic for route in router.routes}
        in_scope = PublisherRouter.model_validate(data, context={"topics": topics})
        assert [route.topic for route in in_scope.routes] == [
            route.topic for route in router.routes
        ]
        assert in_scope.routes[0].topic is router.routes[0].topic

    def test_lambda_predicate_cannot_be_saved(self):
        a = TopicBase(name="a")
        router = PublisherRouter(routes=[PublishRoute(topic=a, when=lambda e: True)])

        with pytest.raises(PydanticSerializationError, match="without pickle"):
            router.model_dump(mode="json")

    def test_predicate_from_untrusted_module_is_not_loaded(self):
        data = {"routes": [{"topic": "a", "when": {"ref": "untrusted_mod:pred"}}]}

        with pytest.raises(UntrustedImportError, match="outside the trusted modules"):
            PublisherRouter.model_validate(
                data, context={"topics": {"a": TopicBase(name="a")}}
            )

    @pytest.mark.parametrize(
        "data",
        [
            {"routes": [{"topic": "a", "whne": {"ref": f"{__name__}:_is_urgent"}}]},
            {"routes": [{"topic": "a"}], "route": []},
        ],
        ids=["route", "router"],
    )
    def test_a_key_it_does_not_have_is_refused(self, data):
        # A misspelt key would otherwise route every event.
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            PublisherRouter.model_validate(
                data, context={"topics": {"a": TopicBase(name="a")}}
            )

    def test_unknown_topic_raises_descriptive_error(self):
        # A manifest referencing a topic that was not reconstructed should fail
        # with a message naming the missing topic and the available ones.
        data = {
            "routes": [
                {
                    "topic": "ghost",
                    "when": {"ref": "grafi.nodes.conditions:always_true"},
                }
            ]
        }
        with pytest.raises(ValidationError, match="Unknown topic 'ghost'") as error:
            PublisherRouter.model_validate(
                data,
                context={"topics": {"agent_output": TopicBase(name="agent_output")}},
            )
        assert "agent_output" in str(error.value)


def _is_urgent(event: PublishToTopicEvent) -> bool:
    """A user's routing predicate, importable by reference."""
    return any("urgent" in str(message.content) for message in event.data)


@pytest.mark.parametrize(("tool_calls", "calls"), [(None, False), ([], False)])
def test_an_empty_tool_call_list_is_no_tool_call(tool_calls, calls):
    # [] once routed a reply as a tool call, and could loop a ReAct workflow.
    from grafi.nodes.conditions import has_no_tool_call

    event = PublishToTopicEvent(
        invoke_context=InvokeContext(
            conversation_id="c", invoke_id="i", assistant_request_id="r"
        ),
        data=[Message(role="assistant", content="done", tool_calls=tool_calls)],
    )
    assert has_tool_call(event) is calls
    assert has_no_tool_call(event) is not calls


def test_an_event_without_messages_calls_no_tool():
    from grafi.nodes.conditions import has_no_tool_call

    event = PublishToTopicEvent(
        invoke_context=InvokeContext(
            conversation_id="c", invoke_id="i", assistant_request_id="r"
        ),
        data=[],
    )
    assert has_tool_call(event) is False
    assert has_no_tool_call(event) is True


def test_text_leading_up_to_tool_calls_is_not_a_text_response():
    # Claude, Gemini and Ollama keep the text a model writes before its calls:
    # routing it as the final answer would end the run before the calls ran.
    message = _tool_call()
    message.content = "Checking."
    event = _publish([message])
    fc, out = TopicBase(name="function_call"), TopicBase(name="agent_output")
    router = PublisherRouter(
        routes=[
            PublishRoute(topic=fc, when=has_tool_call),
            PublishRoute(topic=out, when=has_text_response),
        ]
    )
    assert has_tool_call(event) and not has_text_response(event)
    assert router.select(event) == ["function_call"]
    assert has_text_response(_publish([Message(role="assistant", content="Done.")]))
    assert not has_text_response(_publish([]))
