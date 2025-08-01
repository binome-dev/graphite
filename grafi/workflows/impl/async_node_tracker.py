# ──────────────────────────────────────────────────────────────────────────────
# 1.  Processing tracker – counts active consumer cycles
# ──────────────────────────────────────────────────────────────────────────────
import asyncio
from collections import defaultdict
from typing import Dict


class AsyncNodeTracker:
    def __init__(self) -> None:
        self._active: set[str] = set()
        self._processing_count: Dict[str, int] = defaultdict(
            int
        )  # Track how many times each node processed
        self._cond = asyncio.Condition()
        self._idle_event = asyncio.Event()
        # Set the event initially since we start in idle state
        self._idle_event.set()

    def reset(self) -> None:
        """
        Reset the tracker to its initial state.
        """
        self._active = set()
        self._processing_count = defaultdict(int)
        self._cond = asyncio.Condition()
        self._idle_event = asyncio.Event()
        # Set the event initially since we start in idle state
        self._idle_event.set()

    async def enter(self, node_name: str) -> None:
        async with self._cond:
            self._idle_event.clear()
            self._active.add(node_name)
            self._processing_count[node_name] += 1

    async def leave(self, node_name: str) -> None:
        async with self._cond:
            self._active.discard(node_name)
            if not self._active:
                self._idle_event.set()
                self._cond.notify_all()

    async def wait_idle_event(self) -> None:
        """
        Wait until the tracker is idle, meaning no active nodes.
        This is useful for synchronization points in workflows.
        """
        await self._idle_event.wait()

    def is_idle(self) -> bool:
        return not self._active

    def get_activity_count(self) -> int:
        """Get total processing count across all nodes"""
        return sum(self._processing_count.values())
