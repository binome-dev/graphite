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
    """Which stage produced an outgoing event (keys the pause channel)."""

    PRE_HOOK = "pre_hook"
    TOOL = "tool"
    POST_HOOK = "post_hook"
    CONSUMER = "consumer"


class Entry(str, Enum):
    """Where the consumer router sends an incoming batch."""

    PRE_HOOK = "pre_hook"  # normal: run the full pipeline
    TOOL = "tool"  # pre-hitl resume APPROVED: skip the pause decision
    PUBLISHER = "publisher"  # pre-hitl DENY, or post-hitl verdict: skip the tool


# --------------------------------------------------------------------------- #
# Verdict predicate (consumer router default)
# --------------------------------------------------------------------------- #
_APPROVAL_WORDS = {"approve", "approved", "yes", "y", "ok", "okay"}


def is_approved(messages: Messages) -> bool:
    """Heuristic approve/deny verdict over a HITL reply.

    Approve when the reply echoes a tool call (the reviewer forwarded the
    proposed call back), otherwise when its first word is an approval token.
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
    words = content.strip().lower().split(maxsplit=1)
    return bool(words) and words[0].strip(".!,") in _APPROVAL_WORDS


def _messages(events: List[ConsumeFromTopicEvent]) -> Messages:
    """Flatten the messages across consumed events, preserving order."""
    return [message for event in events for message in event.data]


# --------------------------------------------------------------------------- #
# Consumer router
# --------------------------------------------------------------------------- #
class ConsumerDecision(BaseModel):
    """The consumer router's classification of an incoming batch.

    ``recover_event_ids`` is set only on an approved post-hitl resume: the node
    reads those events back from the event store and forwards the reviewed
    result (the tool is not re-run).
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

    model_config = ConfigDict(arbitrary_types_allowed=True)

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
        A mixed-source batch routes by the first matching source.
        """
        pre = [e for e in node_input if self._on_channel(e, self.pre_hitl_input)]
        if pre:
            # approve -> run the gated tool; deny -> forward the reply (denial)
            entry = Entry.TOOL if self.verdict(_messages(pre)) else Entry.PUBLISHER
            return ConsumerDecision(entry=entry, source_events=pre)

        post = [e for e in node_input if self._on_channel(e, self.post_hitl_input)]
        if post:
            # approve -> recover the reviewed result; deny -> forward the reply
            recover = (
                [eid for e in post for eid in e.consumed_event_ids]
                if self.verdict(_messages(post))
                else None
            )
            return ConsumerDecision(
                entry=Entry.PUBLISHER, source_events=post, recover_event_ids=recover
            )

        for event in node_input:
            if event.name in self.source_routes:
                matched = [e for e in node_input if e.name == event.name]
                return ConsumerDecision(
                    entry=self.source_routes[event.name], source_events=matched
                )

        return ConsumerDecision(entry=Entry.PRE_HOOK, source_events=list(node_input))

    @staticmethod
    def _on_channel(event: ConsumeFromTopicEvent, channel: Optional[str]) -> bool:
        return channel is not None and event.name == channel

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
