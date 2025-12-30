# ──────────────────────────────────────────────────────────────────────────────
# 1.  Processing tracker – counts active consumer cycles
# ──────────────────────────────────────────────────────────────────────────────
import asyncio
from collections import defaultdict
from typing import Dict, Optional, Set

from loguru import logger


class AsyncNodeTracker:
    """
    Central tracker for workflow activity and quiescence detection.
    
    Design: All tracking calls come from the ORCHESTRATOR layer,
    not from TopicBase. This keeps topics as pure message queues.
    
    Quiescence = (no active nodes) AND (no uncommitted messages) AND (work done)
    
    Usage in workflow:
        # In publish_events():
        tracker.on_messages_published(len(published_events))
        
        # In _commit_events():
        tracker.on_messages_committed(len(events))
        
        # In node processing:
        await tracker.enter(node_name)
        ... process ...
        await tracker.leave(node_name)
    """

    def __init__(self) -> None:
        # Node activity tracking
        self._active: Set[str] = set()
        self._processing_count: Dict[str, int] = defaultdict(int)

        # Message tracking (uncommitted = published but not yet committed)
        self._uncommitted_messages: int = 0

        # Synchronization
        self._cond = asyncio.Condition()
        self._quiescence_event = asyncio.Event()

        # Work tracking (prevents premature quiescence before any work)
        self._total_committed: int = 0
        self._has_started: bool = False

        # Force stop flag (for explicit workflow stop)
        self._force_stopped: bool = False

    def reset(self) -> None:
        """Reset for a new workflow run."""
        self._active.clear()
        self._processing_count.clear()
        self._uncommitted_messages = 0
        self._cond = asyncio.Condition()
        self._quiescence_event = asyncio.Event()
        self._total_committed = 0
        self._has_started = False
        self._force_stopped = False

    # ─────────────────────────────────────────────────────────────────────────
    # Node Lifecycle (called from _invoke_node)
    # ─────────────────────────────────────────────────────────────────────────

    async def enter(self, node_name: str) -> None:
        """Called when a node begins processing."""
        async with self._cond:
            self._has_started = True
            self._quiescence_event.clear()
            self._active.add(node_name)
            self._processing_count[node_name] += 1

    async def leave(self, node_name: str) -> None:
        """Called when a node finishes processing."""
        async with self._cond:
            self._active.discard(node_name)
            self._check_quiescence()
            self._cond.notify_all()

    # ─────────────────────────────────────────────────────────────────────────
    # Message Tracking (called from orchestrator utilities)
    # ─────────────────────────────────────────────────────────────────────────

    def on_messages_published(self, count: int = 1, source: str = "") -> None:
        """
        Called when messages are published to topics.

        Call site: publish_events() in utils.py
        """
        if count <= 0:
            return
        self._has_started = True
        self._quiescence_event.clear()
        self._uncommitted_messages += count

        logger.debug(f"Tracker: {count} messages published from {source} (uncommitted={self._uncommitted_messages})")

    def on_messages_committed(self, count: int = 1, source: str = "") -> None:
        """
        Called when messages are committed (consumed and acknowledged).

        Call site: _commit_events() in EventDrivenWorkflow
        """
        if count <= 0:
            return
        self._uncommitted_messages = max(0, self._uncommitted_messages - count)
        self._total_committed += count
        self._check_quiescence()

        logger.debug(
            f"Tracker: {count} messages committed from {source} "
            f"(uncommitted={self._uncommitted_messages}, total={self._total_committed})"
        )

    # Aliases for clarity
    def on_message_published(self) -> None:
        """Single message version."""
        self.on_messages_published(1)

    def on_message_committed(self) -> None:
        """Single message version."""
        self.on_messages_committed(1)

    # ─────────────────────────────────────────────────────────────────────────
    # Quiescence Detection
    # ─────────────────────────────────────────────────────────────────────────

    def _check_quiescence(self) -> None:
        """Check and signal quiescence if all conditions met."""
        logger.debug(
            f"Tracker: checking quiescence - active={list(self._active)}, "
            f"uncommitted={self._uncommitted_messages}, "
            f"has_started={self._has_started}, "
            f"total_committed={self._total_committed}, "
            f"is_quiescent={self.is_quiescent}"
        )
        if self.is_quiescent:
            logger.info(f"Tracker: quiescence detected (committed={self._total_committed})")
            self._quiescence_event.set()

    @property
    def is_quiescent(self) -> bool:
        """
        True when workflow is truly idle:
        - No nodes actively processing
        - No messages waiting to be committed
        - At least some work was done
        """
        return (
            not self._active
            and self._uncommitted_messages == 0
            and self._has_started
            and self._total_committed > 0
        )

    @property
    def should_terminate(self) -> bool:
        """
        True when workflow should stop iteration.
        Either natural quiescence or explicit force stop.
        """
        return self.is_quiescent or self._force_stopped

    def force_stop(self) -> None:
        """
        Force the workflow to stop immediately.
        Called when workflow.stop() is invoked.
        """
        logger.info("Tracker: force stop requested")
        self._force_stopped = True
        self._quiescence_event.set()

    def is_idle(self) -> bool:
        """Legacy: just checks if no active nodes."""
        return not self._active

    async def wait_for_quiescence(self, timeout: Optional[float] = None) -> bool:
        """Wait until quiescent. Returns False on timeout."""
        try:
            if timeout:
                await asyncio.wait_for(self._quiescence_event.wait(), timeout)
            else:
                await self._quiescence_event.wait()
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_idle_event(self) -> None:
        """Legacy compatibility."""
        await self._quiescence_event.wait()

    # ─────────────────────────────────────────────────────────────────────────
    # Metrics
    # ─────────────────────────────────────────────────────────────────────────

    def get_activity_count(self) -> int:
        """Total processing count across all nodes."""
        return sum(self._processing_count.values())

    def get_metrics(self) -> Dict:
        """Detailed metrics for debugging."""
        return {
            "active_nodes": list(self._active),
            "uncommitted_messages": self._uncommitted_messages,
            "total_committed": self._total_committed,
            "is_quiescent": self.is_quiescent,
        }