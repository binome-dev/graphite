"""A node implementation with pre/post tool hook chains and consumer routing.

A :class:`HookedNode` threads one payload through five stages::

    consumer router -> pre-tool hooks -> Tool -> post-tool hooks -> publisher router

With nothing configured every stage is the identity and the node behaves
byte-for-byte like a plain :class:`~grafi.nodes.node.Node`. Hooks are pure
``frame -> frame`` transforms that run in declaration order; the first hook
returning REQUEST (a HITL pause) or DENY short-circuits its chain. The consumer
router classifies a resume reply's verdict back into the pipeline: an approved
pre-hook pause runs the gated tool on the STORED proposal (recovered from the
event store), so what was approved is what runs -- unless the reply itself
carries a (possibly edited) tool call, which then runs as-is.
"""

import json
import uuid
from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import Dict
from typing import List
from typing import Tuple

from loguru import logger
from pydantic import Field
from pydantic import field_validator

from grafi.common.decorators.record_decorators import process_messages_streaming_result
from grafi.common.decorators.record_decorators import record_node_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.models.function_spec import FunctionSpecs
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
from grafi.topics.topic_types import TopicType


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
    """A node that runs pre/post tool hook chains around its tool invocation."""

    consumer_router: ConsumerRouter = Field(default_factory=ConsumerRouter)
    pre_tool_hooks: List[ToolHook] = Field(default_factory=list)
    post_tool_hooks: List[ToolHook] = Field(default_factory=list)

    @field_validator("pre_tool_hooks", "post_tool_hooks", mode="before")
    @classmethod
    def _coerce_hook_chain(cls, value: Any) -> Any:
        """Accept a bare ToolHook as a one-element chain."""
        if value is None:
            return []
        if isinstance(value, ToolHook):
            return [value]
        return value

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

        # Provenance the emitted events carry beyond the consumed batch itself:
        # when a stored payload is recovered and replayed, its event ids are
        # appended here so the audit edge output -> approved-payload is one hop.
        extra_provenance: List[str] = []

        def emit(messages: Messages, to: str = "") -> PublishToTopicEvent:
            # to="" -> content-routed by the publisher router; to=<name> -> a
            # directed pause to that channel.
            return PublishToTopicEvent(
                publisher_name=self.name,
                publisher_type=self.type,
                invoke_context=invoke_context,
                consumed_event_ids=[e.event_id for e in decision.source_events]
                + extra_provenance,
                data=messages,
                name=to,
            )

        def pause(messages: Messages, stage: Stage) -> PublishToTopicEvent:
            try:
                channel = self.publisher_router.request_topic(stage)
            except ValueError as e:
                raise NodeExecutionError(
                    node_name=self.name,
                    message=str(e),
                    invoke_context=invoke_context,
                ) from e
            return emit(messages, to=channel)

        # Consumer short-circuit -> skip the tool, emit to normal output.
        if decision.entry is Entry.PUBLISHER:
            if decision.recover_event_ids is not None:
                # Post-hitl approve: forward the reviewed result from the store.
                recovered_ids, reviewed = await self._recover_from_pause(
                    invoke_context, decision.recover_event_ids
                )
                extra_provenance.extend(recovered_ids)
                yield emit(reviewed)
            else:
                # Pre-hitl deny / post-hitl deny: forward the reply (a denial).
                yield emit(_node_messages(decision.source_events))
            return

        # Stage 2 -- pre-tool hooks: decide pause/deny/proceed (may transform).
        if decision.entry is Entry.PRE_HOOK:
            frame, pauser = await self._run_hooks(
                self.pre_tool_hooks,
                invoke_context,
                _node_messages(decision.source_events),
            )
            if frame.decision is Decision.REQUEST:
                self._warn_resume_skips(self.pre_tool_hooks, pauser, "pre")
                yield pause(frame.messages, Stage.PRE_HOOK)
                return
            if frame.decision is Decision.DENY:
                yield emit(frame.messages)
                return
            tool_input = self._tool_input(frame.messages, decision.source_events)
        else:  # Entry.TOOL -- approved pre-hitl resume: run the gated tool.
            if decision.recover_event_ids is not None:
                # The reply approved without echoing a call: what was approved
                # is what runs -- recover the stored proposal and replay it.
                recovered_ids, proposal = await self._recover_from_pause(
                    invoke_context, decision.recover_event_ids
                )
                extra_provenance.extend(recovered_ids)
                tool_input = [
                    self._synth_recovery_event(
                        decision.source_events[-1], proposal, recovered_ids
                    )
                ]
            else:
                # The reply carries a (possibly edited) call: run it as-is.
                tool_input = decision.source_events

        # Reasoning is for the human reviewer, not the tool: strip it here, at
        # the orchestration boundary, before the tool sees the call.
        tool_input = _strip_reserved_tool_args(tool_input)

        # Stage 3/4 -- tool, then the post-tool hook chain.
        if any(hook.decides for hook in self.post_tool_hooks):
            # A deciding post-hook needs the whole batch -> aggregate the
            # stream (per-chunk streaming is disabled for this node).
            batches = [
                messages
                async for messages in self._command.invoke(
                    invoke_context, input_data=tool_input
                )
            ]
            frame, pauser = await self._run_hooks(
                self.post_tool_hooks,
                invoke_context,
                process_messages_streaming_result(batches),
            )
            if frame.decision is Decision.REQUEST:
                self._warn_resume_skips(self.post_tool_hooks, pauser, "post")
                yield pause(frame.messages, Stage.POST_HOOK)
                return
            # PROCEED and DENY both emit the (transformed) batch to normal
            # output; DENY additionally short-circuited the rest of the chain.
            yield emit(frame.messages)
        else:
            # Identity post-chain: stream per chunk -- byte-identical.
            async for messages in self._command.invoke(
                invoke_context, input_data=tool_input
            ):
                yield emit(messages)

    @staticmethod
    async def _run_hooks(
        hooks: List[ToolHook],
        invoke_context: InvokeContext,
        messages: Messages,
    ) -> Tuple[ToolHookFrame, int]:
        """Run a hook chain in declaration order.

        Each hook transforms the frame; the first hook whose decision is not
        PROCEED short-circuits the chain. Returns the final frame and the index
        of the short-circuiting hook (-1 when the whole chain proceeded).
        """
        frame = ToolHookFrame(invoke_context=invoke_context, messages=messages)
        for index, hook in enumerate(hooks):
            frame = await hook.invoke(frame)
            if frame.decision is not Decision.PROCEED:
                return frame, index
        return frame, -1

    def _warn_resume_skips(
        self, hooks: List[ToolHook], pauser: int, stage_name: str
    ) -> None:
        """Warn when hooks declared after the pausing hook will never run.

        An approved resume re-enters the pipeline AFTER the paused stage
        (Entry.TOOL / Entry.PUBLISHER), so hooks following the one that paused
        are skipped both now (short-circuit) and on resume.
        """
        if pauser < 0 or pauser >= len(hooks) - 1:
            return
        skipped = ", ".join(type(h).__name__ for h in hooks[pauser + 1 :])
        logger.warning(
            f"Node '{self.name}': {type(hooks[pauser]).__name__} paused the "
            f"{stage_name}-tool chain at position {pauser}; later hook(s) "
            f"[{skipped}] will not run now or when the pause is approved. "
            "Declare pausing hooks last in their chain."
        )

    def _tool_input(
        self, messages: Messages, source_events: List[ConsumeFromTopicEvent]
    ) -> List[ConsumeFromTopicEvent]:
        """Tool input as consume events so the command's reconstruction is intact.

        When the pre-hooks did not transform the batch (the common case), the
        original ``source_events`` are passed through unchanged -- byte-identical
        to today, and preserving the event-graph linkage the LLM command rebuilds
        from. When a hook transformed the messages, they ride on a copy of the
        source event.
        """
        if messages == _node_messages(source_events):
            return source_events
        return [source_events[-1].model_copy(update={"data": messages})]

    def _synth_recovery_event(
        self,
        reply_event: ConsumeFromTopicEvent,
        proposal: Messages,
        proposal_ids: List[str],
    ) -> ConsumeFromTopicEvent:
        """A fresh consume event carrying the recovered proposal.

        Gets its own event_id (it is a new occurrence, not the reply) and
        points its consumed_event_ids at the recovered proposal events, so the
        in-memory payload and the store's event graph tell the same story.
        """
        return reply_event.model_copy(
            update={
                "event_id": uuid.uuid4().hex,
                "data": proposal,
                "consumed_event_ids": list(proposal_ids),
            }
        )

    async def _recover_from_pause(
        self, invoke_context: InvokeContext, event_ids: List[str]
    ) -> Tuple[List[str], Messages]:
        """Read a paused payload back from the event store.

        Recovers only events with in-workflow-output provenance (the pause
        channels), in the given deterministic order -- callers control
        ``consumed_event_ids`` on a resume request, so this filter is also an
        integrity check that arbitrary stored events cannot be replayed as
        tool input.

        Partial matches are EXPECTED: resume requests commonly reference every
        output event of the paused invoke (pause channel plus normal outputs),
        and the provenance filter selects the reviewable subset. An id that
        resolves to nothing at all is suspicious and warned about. Raises
        loudly when recovery was intended but NO pause event is recoverable:
        an approval must act on what was approved, never silently degrade to
        the reply text.
        """
        store = current_services().event_store
        recovered_ids: List[str] = []
        recovered: Messages = []
        for event_id in event_ids:
            event = await store.get_event(event_id)
            if event is None:
                logger.warning(
                    f"Node '{self.name}': resume id {event_id} resolves to no "
                    "stored event; ignoring it."
                )
                continue
            if getattr(event, "type", None) != TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE:
                # Expected for ids of the invoke's normal outputs; the filter
                # selects the pause subset.
                continue
            data = getattr(event, "data", None)
            if data:
                recovered_ids.append(event_id)
                recovered.extend(data)
        if not recovered:
            raise NodeExecutionError(
                node_name=self.name,
                message=(
                    "Approved HITL resume could not recover the paused payload "
                    f"from the event store (consumed_event_ids={list(event_ids)}"
                    "). The resume request must reference the pause event(s) it "
                    "approves; refusing to fall back to the reply text."
                ),
                invoke_context=invoke_context,
            )
        return recovered_ids, recovered

    def spec_augmenters(self) -> List[Callable[[FunctionSpecs], FunctionSpecs]]:
        """Each hook's spec transform, pre-chain then post-chain, in order."""
        return [
            hook.augment_spec for hook in (*self.pre_tool_hooks, *self.post_tool_hooks)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "consumer_router": self.consumer_router.to_dict(),
            "pre_tool_hooks": [hook.to_dict() for hook in self.pre_tool_hooks],
            "post_tool_hooks": [hook.to_dict() for hook in self.post_tool_hooks],
        }

    @classmethod
    async def from_dict(
        cls, node_dict: Dict[str, Any], topics: Dict[str, TopicBase]
    ) -> "HookedNode":
        """Create a HookedNode instance from a dictionary representation."""
        for legacy_key in ("pre_tool_hook", "post_tool_hook"):
            if legacy_key in node_dict:
                # Fail closed: silently ignoring the old singular shape would
                # deserialize a gated node as ungated.
                raise ValueError(
                    f"Node manifest carries legacy singular '{legacy_key}'; hook "
                    f"chains serialize as '{legacy_key}s' (a list). Regenerate "
                    "the manifest from the current assistant."
                )

        node_builder = await cls._builder_from_dict(node_dict, topics)
        assert isinstance(node_builder, HookedNodeBuilder)

        if node_dict.get("consumer_router"):
            node_builder.consumer_router(
                ConsumerRouter.from_dict(node_dict["consumer_router"])
            )
        for hook_dict in node_dict.get("pre_tool_hooks") or []:
            node_builder.pre_tool_hook(hook_from_dict(hook_dict))
        for hook_dict in node_dict.get("post_tool_hooks") or []:
            node_builder.post_tool_hook(hook_from_dict(hook_dict))

        return node_builder.build()


class HookedNodeBuilder(NodeBaseBuilder):
    """Builder for HookedNode: adds the hook-chain and consumer-router fields."""

    def consumer_router(self, consumer_router: ConsumerRouter) -> "HookedNodeBuilder":
        """Set the consumer router (HITL resume channels + verdict predicate)."""
        self.kwargs["consumer_router"] = consumer_router
        return self

    def pre_tool_hook(self, pre_tool_hook: ToolHook) -> "HookedNodeBuilder":
        """Add a pre-tool hook (appends; declaration order = execution order)."""
        self.kwargs.setdefault("pre_tool_hooks", []).append(pre_tool_hook)
        return self

    def post_tool_hook(self, post_tool_hook: ToolHook) -> "HookedNodeBuilder":
        """Add a post-tool hook (appends; declaration order = execution order).

        Note: any non-identity post-hook makes the node aggregate the tool's
        stream so the chain sees the whole batch -- per-chunk streaming is
        disabled for that node.
        """
        self.kwargs.setdefault("post_tool_hooks", []).append(post_tool_hook)
        return self
