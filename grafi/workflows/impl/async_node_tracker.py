# ──────────────────────────────────────────────────────────────────────────────
# 1.  Processing tracker – counts active consumer cycles
# ──────────────────────────────────────────────────────────────────────────────
import asyncio
from collections import defaultdict
from typing import Dict
from typing import Optional
from typing import Set

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

        # Force stop flag (for explicit workflow stop)
        self._force_stopped: bool = False

    def reset(self) -> None:
        """
        Reset for a new workflow run.

        Note: This is a sync reset that replaces primitives. It should only be
        called when no coroutines are waiting on the old primitives (e.g., at
        the start of a new workflow invocation before any tasks are spawned).
        """
        self._active.clear()
        self._processing_count.clear()
        self._uncommitted_messages = 0
        self._cond = asyncio.Condition()
        self._quiescence_event = asyncio.Event()
        self._force_stopped = False

    async def reset_async(self) -> None:
        """
        Reset for a new workflow run (async version).

        This version properly wakes any waiting coroutines before resetting,
        preventing deadlocks if called while the workflow is still running.
        """
        async with self._cond:
            # Wake all waiters so they can exit gracefully
            self._force_stopped = True
            self._quiescence_event.set()
            self._cond.notify_all()

        # Give waiters a chance to wake up and exit
        await asyncio.sleep(0)

        # Now safe to reset state
        async with self._cond:
            self._active.clear()
            self._processing_count.clear()
            self._uncommitted_messages = 0
            self._force_stopped = False
            self._quiescence_event.clear()

    # ─────────────────────────────────────────────────────────────────────────
    # Node Lifecycle (called from _invoke_node)
    # ─────────────────────────────────────────────────────────────────────────

    async def enter(self, node_name: str) -> None:
        """Called when a node begins processing."""
        async with self._cond:
            self._quiescence_event.clear()
            self._active.add(node_name)
            self._processing_count[node_name] += 1

    async def leave(self, node_name: str) -> None:
        """Called when a node finishes processing."""
        async with self._cond:
            self._active.discard(node_name)
            self._check_quiescence_unlocked()
            self._cond.notify_all()

    # ─────────────────────────────────────────────────────────────────────────
    # Message Tracking (called from orchestrator utilities)
    # ─────────────────────────────────────────────────────────────────────────

    async def on_messages_published(self, count: int = 1, source: str = "") -> None:
        """
        Called when messages are published to topics.

        Call site: publish_events() in utils.py
        """
        if count <= 0:
            return
        async with self._cond:
            self._quiescence_event.clear()
            self._uncommitted_messages += count

            logger.debug(
                f"Tracker: {count} messages published from {source} (uncommitted={self._uncommitted_messages})"
            )

    async def on_messages_committed(self, count: int = 1, source: str = "") -> None:
        """
        Called when messages are committed (consumed and acknowledged).

        Call site: _commit_events() in EventDrivenWorkflow
        """
        if count <= 0:
            return
        async with self._cond:
            self._uncommitted_messages = max(0, self._uncommitted_messages - count)
            self._check_quiescence_unlocked()

            logger.debug(f"Tracker: {count} messages committed from {source} ")
            self._cond.notify_all()

    # Aliases for clarity
    async def on_message_published(self) -> None:
        """Single message version."""
        await self.on_messages_published(1)

    async def on_message_committed(self) -> None:
        """Single message version."""
        await self.on_messages_committed(1)

    # ─────────────────────────────────────────────────────────────────────────
    # Quiescence Detection
    # ─────────────────────────────────────────────────────────────────────────

    def _check_quiescence_unlocked(self) -> None:
        """
        Check and signal quiescence if all conditions met.

        MUST be called with self._cond lock held.
        """
        is_quiescent = self._is_quiescent_unlocked()
        logger.debug(
            f"Tracker: checking quiescence - active={list(self._active)}, "
            f"uncommitted={self._uncommitted_messages}, "
            f"is_quiescent={is_quiescent}"
        )
        if is_quiescent:
            self._quiescence_event.set()

    def _is_quiescent_unlocked(self) -> bool:
        """
        Internal quiescence check without lock.

        MUST be called with self._cond lock held.

        True when workflow is truly idle:
        - No nodes actively processing
        - No messages waiting to be committed
        - At least some work was done
        """
        logger.debug(
            f"Tracker: _is_quiescent_unlocked check - active={list(self._active)}, "
            f"uncommitted={self._uncommitted_messages}, "
        )
        return not self._active and self._uncommitted_messages == 0

    async def is_quiescent(self) -> bool:
        """
        True when workflow is truly idle:
        - No nodes actively processing
        - No messages waiting to be committed
        - At least some work was done

        This method acquires the lock to ensure consistent reads.
        """
        async with self._cond:
            return self._is_quiescent_unlocked()

    def _should_terminate_unlocked(self) -> bool:
        """
        Internal termination check without lock.

        MUST be called with self._cond lock held.
        """
        return self._is_quiescent_unlocked() or self._force_stopped

    async def should_terminate(self) -> bool:
        """
        True when workflow should stop iteration.
        Either natural quiescence or explicit force stop.

        This method acquires the lock to ensure consistent reads.
        """
        async with self._cond:
            return self._should_terminate_unlocked()

    async def force_stop(self) -> None:
        """
        Force the workflow to stop immediately (async version with lock).
        Called when workflow.stop() is invoked from async context.
        """
        async with self._cond:
            logger.info("Tracker: force stop requested")
            self._force_stopped = True
            self._quiescence_event.set()
            self._cond.notify_all()

    def force_stop_sync(self) -> None:
        """
        Force the workflow to stop immediately (sync version).

        This is a synchronous version for use from sync contexts (e.g., stop() method).
        It sets the stop flag and event without acquiring the async lock.
        This is safe because:
        1. Setting _force_stopped to True is atomic for the stop signal
        2. asyncio.Event.set() is thread-safe
        3. Readers will see the updated state on their next lock acquisition
        """
        logger.info("Tracker: force stop requested (sync)")
        self._force_stopped = True
        self._quiescence_event.set()

    async def is_idle(self) -> bool:
        """Legacy: just checks if no active nodes."""
        async with self._cond:
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

    async def get_activity_count(self) -> int:
        """Total processing count across all nodes."""
        async with self._cond:
            return sum(self._processing_count.values())

    async def get_metrics(self) -> Dict:
        """Detailed metrics for debugging."""
        async with self._cond:
            return {
                "active_nodes": list(self._active),
                "uncommitted_messages": self._uncommitted_messages,
                "is_quiescent": self._is_quiescent_unlocked(),
            }
