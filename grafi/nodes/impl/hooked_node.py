"""A node implementation with pre/post tool hooks and consumer routing.

A :class:`HookedNode` threads one payload through five stages::

    consumer router -> pre-tool hook -> Tool -> post-tool hook -> publisher router

With nothing configured every stage is the identity and the node behaves
byte-for-byte like a plain :class:`~grafi.nodes.node.Node`. Hooks are pure
``frame -> frame`` transforms that may signal a HITL pause; the consumer router
classifies a resume reply's verdict back into the pipeline.
"""

import json
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List

from pydantic import Field

from grafi.common.decorators.record_decorators import process_messages_streaming_result
from grafi.common.decorators.record_decorators import record_node_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.nodes.hooks.hitl_approval_hook import TOOL_CALL_REASON_KEY
from grafi.nodes.hooks.hook_factory import hook_from_dict
from grafi.nodes.hooks.tool_hook import ToolHook
from grafi.nodes.hooks.tool_hook import ToolHookFrame
from grafi.nodes.node import Node
from grafi.nodes.node_base import NodeBaseBuilder
from grafi.nodes.routing import ConsumerRouter
from grafi.nodes.routing import Decision
from grafi.nodes.routing import Entry
from grafi.nodes.routing import Stage
from grafi.runtime.execution_services import current_services
from grafi.topics.topic_base import TopicBase


def _node_messages(events: List[ConsumeFromTopicEvent]) -> Messages:
    """Flatten the messages across consumed events, preserving order."""
    return [message for event in events for message in event.data]


def _strip_reserved_tool_args(
    events: List[ConsumeFromTopicEvent],
) -> List[ConsumeFromTopicEvent]:
    """Drop the reserved ``tool_call_reason`` arg from any tool-call messages.

    The reasoning arg is injected (for human review) into the LLM's tool spec by
    a hook; it is not a real tool parameter, so the node removes it before the
    tool runs. A no-op when no tool call carries it -- the original list is
    returned unchanged, preserving the fast path.
    """
    cleaned = list(events)
    changed = False
    for index, event in enumerate(events):
        if not any(m.tool_calls for m in event.data):
            continue
        new_data: Messages = []
        event_changed = False
        for message in event.data:
            if not message.tool_calls:
                new_data.append(message)
                continue
            new_message = message.model_copy(deep=True)
            for tool_call in new_message.tool_calls or []:
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(args, dict) and TOOL_CALL_REASON_KEY in args:
                    args.pop(TOOL_CALL_REASON_KEY, None)
                    tool_call.function.arguments = json.dumps(args)
                    event_changed = True
            new_data.append(new_message)
        if event_changed:
            cleaned[index] = event.model_copy(update={"data": new_data})
            changed = True
    return cleaned if changed else events


class HookedNode(Node):
    """A node that runs pre/post tool hooks around its tool invocation."""

    consumer_router: ConsumerRouter = Field(default_factory=ConsumerRouter)
    pre_tool_hook: ToolHook = Field(default_factory=ToolHook)
    post_tool_hook: ToolHook = Field(default_factory=ToolHook)

    @classmethod
    def builder(cls) -> "HookedNodeBuilder":
        """Return a builder for HookedNode."""
        return HookedNodeBuilder(cls)

    @record_node_invoke
    async def invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> AsyncGenerator[PublishToTopicEvent, None]:
        if self._command is None:
            raise NodeExecutionError(
                node_name=self.name,
                message="Cannot invoke a node without a tool/command.",
                invoke_context=invoke_context,
            )

        # Stage 1 -- consumer router: classify the incoming batch.
        decision = self.consumer_router.classify(node_input)

        def emit(messages: Messages, to: str = "") -> PublishToTopicEvent:
            # to="" -> content-routed by the publisher router; to=<name> -> a
            # directed pause to that channel.
            return PublishToTopicEvent(
                publisher_name=self.name,
                publisher_type=self.type,
                invoke_context=invoke_context,
                consumed_event_ids=[e.event_id for e in decision.source_events],
                data=messages,
                name=to,
            )

        def pause(messages: Messages, stage: Stage) -> PublishToTopicEvent:
            return emit(messages, to=self.publisher_router.request_topic(stage))

        # Consumer short-circuit -> skip the tool, emit to normal output.
        if decision.entry is Entry.PUBLISHER:
            if decision.recover_event_ids:
                # Post-hitl approve: forward the reviewed result from the store.
                yield emit(await self._recover_result(decision.recover_event_ids))
            else:
                # Pre-hitl deny / post-hitl deny: forward the reply (a denial).
                yield emit(_node_messages(decision.source_events))
            return

        # Stage 2 -- pre-tool hook: decide pause/deny/proceed (and may transform).
        if decision.entry is Entry.PRE_HOOK:
            frame = await self.pre_tool_hook.invoke(
                ToolHookFrame(
                    invoke_context=invoke_context,
                    messages=_node_messages(decision.source_events),
                )
            )
            if frame.decision is Decision.REQUEST:
                yield pause(frame.messages, Stage.PRE_HOOK)
                return
            if frame.decision is Decision.DENY:
                yield emit(frame.messages)
                return
            tool_input = self._tool_input(frame.messages, decision.source_events)
        else:  # Entry.TOOL -- approved pre-hitl resume: run the gated tool.
            tool_input = decision.source_events

        # Reasoning is for the human reviewer, not the tool: strip it here, at
        # the orchestration boundary, before the tool sees the call.
        tool_input = _strip_reserved_tool_args(tool_input)

        # Stage 3/4 -- tool, then optional post-tool hook.
        if self.post_tool_hook.decides:
            # A deciding post-hook needs the whole batch -> aggregate the stream.
            batches = [
                messages
                async for messages in self._command.invoke(
                    invoke_context, input_data=tool_input
                )
            ]
            frame = await self.post_tool_hook.invoke(
                ToolHookFrame(
                    invoke_context=invoke_context,
                    messages=process_messages_streaming_result(batches),
                )
            )
            if frame.decision is Decision.REQUEST:
                yield pause(frame.messages, Stage.POST_HOOK)
                return
            yield emit(frame.messages)
        else:
            # Default (identity) post-hook: stream per chunk -- byte-identical.
            async for messages in self._command.invoke(
                invoke_context, input_data=tool_input
            ):
                yield emit(messages)

    def _tool_input(
        self, messages: Messages, source_events: List[ConsumeFromTopicEvent]
    ) -> List[ConsumeFromTopicEvent]:
        """Tool input as consume events so the command's reconstruction is intact.

        When the pre-hook did not transform the batch (the common case), the
        original ``source_events`` are passed through unchanged -- byte-identical
        to today, and preserving the event-graph linkage the LLM command rebuilds
        from. When a hook transformed the messages, they ride on a copy of the
        source event.
        """
        if messages == _node_messages(source_events):
            return source_events
        return [source_events[-1].model_copy(update={"data": messages})]

    async def _recover_result(self, event_ids: List[str]) -> Messages:
        """Read the reviewed result back from the event store (recover, D11).

        On an approved post-hook resume the reply's ``consumed_event_ids`` point
        at the recorded review event; its result is forwarded without re-running
        the tool. Uses the same event store the LLM command reconstructs from.
        """
        store = current_services().event_store
        recovered: Messages = []
        for event_id in event_ids:
            event = await store.get_event(event_id)
            data = getattr(event, "data", None)
            if data:
                recovered.extend(data)
        return recovered

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "consumer_router": self.consumer_router.to_dict(),
            "pre_tool_hook": self.pre_tool_hook.to_dict(),
            "post_tool_hook": self.post_tool_hook.to_dict(),
        }

    @classmethod
    async def from_dict(
        cls, node_dict: Dict[str, Any], topics: Dict[str, TopicBase]
    ) -> "HookedNode":
        """Create a HookedNode instance from a dictionary representation."""
        node_builder = await cls._builder_from_dict(node_dict, topics)
        assert isinstance(node_builder, HookedNodeBuilder)

        if node_dict.get("consumer_router"):
            node_builder.consumer_router(
                ConsumerRouter.from_dict(node_dict["consumer_router"])
            )
        if node_dict.get("pre_tool_hook"):
            node_builder.pre_tool_hook(hook_from_dict(node_dict["pre_tool_hook"]))
        if node_dict.get("post_tool_hook"):
            node_builder.post_tool_hook(hook_from_dict(node_dict["post_tool_hook"]))

        return node_builder.build()


class HookedNodeBuilder(NodeBaseBuilder):
    """Builder for HookedNode: adds the hook and consumer-router fields."""

    def consumer_router(self, consumer_router: ConsumerRouter) -> "HookedNodeBuilder":
        """Set the consumer router (HITL resume channels + verdict predicate)."""
        self.kwargs["consumer_router"] = consumer_router
        return self

    def pre_tool_hook(self, pre_tool_hook: ToolHook) -> "HookedNodeBuilder":
        """Set the pre-tool hook (pause/transform before the tool runs)."""
        self.kwargs["pre_tool_hook"] = pre_tool_hook
        return self

    def post_tool_hook(self, post_tool_hook: ToolHook) -> "HookedNodeBuilder":
        """Set the post-tool hook (pause/transform on the tool output)."""
        self.kwargs["post_tool_hook"] = post_tool_hook
        return self
