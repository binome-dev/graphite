"""Consumer-side routing for the hooked node's internal pipeline.

A :class:`~grafi.nodes.impl.hooked_node.HookedNode` threads one payload through
five stages::

    consumer router -> pre-tool hook -> Tool -> post-tool hook -> publisher router

The **consumer router** defined here classifies an already-consumed input batch
(and, on a HITL resume, the approve/deny *verdict*) into an internal entry
point. The **publisher router** (the node's output routing table, in
:mod:`grafi.nodes.node_base`) maps an outgoing event to destination topic
names -- by content, or, on a HITL pause, by a directed channel name.

These are pure, serializable, unit-testable components; they own no queue or
tracker state (the engine keeps I/O ownership).
"""

from enum import Enum
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from loguru import logger
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from grafi.common.callable_ref import deserialize_callable
from grafi.common.callable_ref import serialize_callable
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.message import Messages


# --------------------------------------------------------------------------- #
# Decision vocabulary (shared by hooks, both routers, and the validator)
# --------------------------------------------------------------------------- #
class Decision(str, Enum):
    """A hook's verdict on the payload it was handed."""

    PROCEED = "proceed"  # continue the pipeline; or a normal terminal output
    REQUEST = "request"  # HITL pause request (pre- or post-hook)
    DENY = "deny"  # skip the rest; emit a denial answer to normal output


class Stage(str, Enum):
    """Which pipeline stage requested a pause (keys the pause channel)."""

    PRE_HOOK = "pre_hook"
    POST_HOOK = "post_hook"


class Entry(str, Enum):
    """Where the consumer router sends an incoming batch."""

    PRE_HOOK = "pre_hook"  # normal: run the full pipeline
    # pre-hitl resume APPROVED: run the gated tool -- on the recovered stored
    # proposal, or on the reply itself when it carries a (possibly edited) call.
    TOOL = "tool"
    PUBLISHER = "publisher"  # pre-hitl DENY, or post-hitl verdict: skip the tool


# --------------------------------------------------------------------------- #
# Verdict predicate (consumer router default)
# --------------------------------------------------------------------------- #
_APPROVAL_WORDS = {"approve", "approved", "yes", "y", "ok", "okay"}


def is_approved(messages: Messages) -> bool:
    """Strict approve/deny verdict over a HITL reply.

    Approve when the reply echoes a tool call (the reviewer forwarded the --
    possibly edited -- proposed call back), or when the ENTIRE reply is a bare
    approval token ("yes", "approve", "ok", ...). Anything longer, including
    "yes, but change the amount", is treated as NOT approved and flows back as
    a reply: an approval here causes the gated tool to actually run, so this
    predicate is an execution trust boundary and errs conservative.

    A named module-level function so it serializes as an import reference;
    overridable per node via :attr:`ConsumerRouter.verdict`.
    """
    if not messages:
        return False
    last = messages[-1]
    if last.tool_calls:
        return True
    content = last.content
    if not isinstance(content, str):
        return False
    return content.strip().lower().strip(".!,") in _APPROVAL_WORDS


def _messages(events: List[ConsumeFromTopicEvent]) -> Messages:
    """Flatten the messages across consumed events, preserving order."""
    return [message for event in events for message in event.data]


def _ordered_unique_ids(events: List[ConsumeFromTopicEvent]) -> List[str]:
    """The events' consumed_event_ids, deduplicated, first-occurrence order.

    Deterministic ordering matters: these ids select the stored payload an
    approved resume recovers and replays, so the same reply must always
    reconstruct the same input.
    """
    seen = set()
    ordered: List[str] = []
    for event in events:
        for event_id in event.consumed_event_ids:
            if event_id not in seen:
                seen.add(event_id)
                ordered.append(event_id)
    return ordered


# --------------------------------------------------------------------------- #
# Consumer router
# --------------------------------------------------------------------------- #
class ConsumerDecision(BaseModel):
    """The consumer router's classification of an incoming batch.

    ``recover_event_ids`` expresses RECOVERY INTENT, not merely id presence:

    * ``None`` -- no recovery; the pipeline runs on ``source_events`` as-is.
    * a list (possibly empty) -- the node must reconstruct the stored payload
      from these event ids. On an approved post-hitl resume
      (``entry=PUBLISHER``) the recovered reviewed result is forwarded without
      re-running the tool; on an approved pre-hitl resume whose reply carries
      no tool call (``entry=TOOL``) the recovered proposal is what the gated
      tool runs. An empty list means recovery was intended but the reply
      carried no ids -- the node fails loudly rather than running the tool on
      the reply text.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    entry: Entry
    source_events: List[ConsumeFromTopicEvent]
    recover_event_ids: Optional[List[str]] = None


class ConsumerRouter(BaseModel):
    """Classify an already-consumed ``node_input`` into an internal entry point.

    Routing is keyed on the message's **source topic**, so the same node can
    treat inputs differently by where they came from:

    * ``source_routes`` maps a source topic name to the ``Entry`` (handling) its
      messages take -- e.g. fresh input runs the pre-hook -> tool path while a
      replay topic skips straight to the publisher.
    * ``pre_hitl_input`` / ``post_hitl_input`` are the verdict-driven special
      case for HITL resumes (approve/deny), checked first.

    Default (nothing configured) is a no-op: the batch flows whole into the
    pre-hook -> tool path, byte-for-byte as today.
    """

    # extra="forbid": a mistyped channel name must fail loudly, not silently
    # leave the node ungated.
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    pre_hitl_input: Optional[str] = None  # topic name of the pre-hook resume channel
    post_hitl_input: Optional[str] = None  # topic name of the post-hook resume channel
    verdict: Callable[[Messages], bool] = is_approved  # named predicate; both phases
    # General per-source handling: source topic name -> the Entry its messages
    # take. The HITL channels above are the verdict-driven special case.
    source_routes: Dict[str, Entry] = Field(default_factory=dict)

    def classify(self, node_input: List[ConsumeFromTopicEvent]) -> ConsumerDecision:
        """Classify a consumed batch into an internal entry point, by source.

        Messages arriving on a configured channel are gathered by their source
        topic and routed together. HITL resume channels (verdict-driven) take
        priority, then ``source_routes``; anything else flows into the pre-hook.

        A mixed-source batch routes as a SINGLE decision by the first matching
        source; the non-selected events were already consumed by the engine and
        are dropped from processing (they remain in the event store). This is
        logged loudly because it usually indicates a fan-in node whose sources
        should be separated.
        """
        pre = [e for e in node_input if self._on_channel(e, self.pre_hitl_input)]
        if pre:
            self._warn_dropped(
                pre, node_input, f"pre_hitl_input='{self.pre_hitl_input}'"
            )
            if not self.verdict(_messages(pre)):
                # deny -> forward the reply (a denial) to normal output
                return ConsumerDecision(entry=Entry.PUBLISHER, source_events=pre)
            # approve -> run the gated tool. If the reply itself carries a
            # (possibly edited) tool call, run the reply as-is; otherwise the
            # node must recover the stored proposal -- what was approved is
            # what runs.
            reply_has_call = any(m.tool_calls for m in _messages(pre))
            return ConsumerDecision(
                entry=Entry.TOOL,
                source_events=pre,
                recover_event_ids=None if reply_has_call else _ordered_unique_ids(pre),
            )

        post = [e for e in node_input if self._on_channel(e, self.post_hitl_input)]
        if post:
            self._warn_dropped(
                post, node_input, f"post_hitl_input='{self.post_hitl_input}'"
            )
            # approve -> recover the reviewed result; deny -> forward the reply
            recover = (
                _ordered_unique_ids(post) if self.verdict(_messages(post)) else None
            )
            return ConsumerDecision(
                entry=Entry.PUBLISHER, source_events=post, recover_event_ids=recover
            )

        for event in node_input:
            if event.name in self.source_routes:
                matched = [e for e in node_input if e.name == event.name]
                self._warn_dropped(
                    matched, node_input, f"source_routes['{event.name}']"
                )
                return ConsumerDecision(
                    entry=self.source_routes[event.name], source_events=matched
                )

        return ConsumerDecision(entry=Entry.PRE_HOOK, source_events=list(node_input))

    @staticmethod
    def _on_channel(event: ConsumeFromTopicEvent, channel: Optional[str]) -> bool:
        return channel is not None and event.name == channel

    @staticmethod
    def _warn_dropped(
        selected: List[ConsumeFromTopicEvent],
        node_input: List[ConsumeFromTopicEvent],
        channel: str,
    ) -> None:
        """Log the consumed-but-not-processed remainder of a mixed batch."""
        if len(selected) == len(node_input):
            return
        selected_ids = {e.event_id for e in selected}
        dropped = [e for e in node_input if e.event_id not in selected_ids]
        logger.warning(
            f"Consumer router matched {channel} and is processing only "
            f"{len(selected)}/{len(node_input)} events of a mixed batch; "
            "dropping already-consumed events "
            + ", ".join(f"{e.name}#{e.offset}(event_id={e.event_id})" for e in dropped)
            + ". They remain in the event store but will not be processed."
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pre_hitl_input": self.pre_hitl_input,
            "post_hitl_input": self.post_hitl_input,
            "verdict": serialize_callable(self.verdict),
            "source_routes": {
                topic: entry.value for topic, entry in self.source_routes.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConsumerRouter":
        raw = data.get("verdict")
        verdict = (
            deserialize_callable(raw, context="consumer router verdict")
            if raw
            else is_approved
        )
        return cls(
            pre_hitl_input=data.get("pre_hitl_input"),
            post_hitl_input=data.get("post_hitl_input"),
            verdict=verdict,
            source_routes={
                topic: Entry(value)
                for topic, value in data.get("source_routes", {}).items()
            },
        )
