"""Reusable routing predicates.

A publisher route's ``when`` decides whether an outgoing event is delivered to
that route's topic. These named, importable predicates cover the common content
checks so workflows can reference them (``when=has_tool_call``) instead of
embedding inline lambdas.

Named predicates are preferred over lambdas because they:

* serialize as a compact, human-readable reference (``{"ref": "...:has_tool_call"}``)
  rather than inline code,
* are reusable and unit-testable in isolation, and
* keep one source of truth for a routing rule (DRY) instead of copy-pasted lambdas.

For richer, parameterized routing, implement a
:class:`~grafi.common.callable_component.CallableComponent` instead.
"""

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent


def always_true(_: PublishToTopicEvent) -> bool:
    """Default routing predicate: take the route for every event.

    A named module-level function (rather than an inline ``lambda``) so it
    serializes as a tiny import reference instead of inline code.
    """
    return True


def has_tool_call(event: PublishToTopicEvent) -> bool:
    """Publish only when the last message requests a tool/function call."""
    return event.data[-1].tool_calls is not None


def has_no_tool_call(event: PublishToTopicEvent) -> bool:
    """Publish only when the last message does NOT request a tool call."""
    return event.data[-1].tool_calls is None


def has_text_response(event: PublishToTopicEvent) -> bool:
    """Publish only when the last message is a non-empty text response.

    Stricter than :func:`has_content`: the content must be a string with
    non-whitespace characters -- the usual "this is a final answer" gate.
    """
    content = event.data[-1].content
    return content is not None and isinstance(content, str) and content.strip() != ""
