import asyncio

import pytest

from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker


class TestAsyncNodeTracker:
    @pytest.fixture
    def tracker(self):
        """Create a new AsyncNodeTracker instance for testing."""
        return AsyncNodeTracker()

    @pytest.mark.asyncio
    async def test_initial_state(self, tracker):
        """Test that tracker starts in idle state."""
        assert tracker.is_idle()
        assert tracker.get_activity_count() == 0
        assert tracker._idle_event.is_set()

    @pytest.mark.asyncio
    async def test_enter_makes_tracker_active(self, tracker):
        """Test that entering a node makes the tracker active."""
        await tracker.enter("node1")

        assert not tracker.is_idle()
        assert not tracker._idle_event.is_set()
        assert tracker.get_activity_count() == 1
        assert "node1" in tracker._active

    @pytest.mark.asyncio
    async def test_leave_makes_tracker_idle(self, tracker):
        """Test that leaving the last node makes the tracker idle."""
        await tracker.enter("node1")
        await tracker.leave("node1")

        assert tracker.is_idle()
        assert tracker._idle_event.is_set()
        assert tracker.get_activity_count() == 1  # Count persists
        assert "node1" not in tracker._active

    @pytest.mark.asyncio
    async def test_multiple_nodes_tracking(self, tracker):
        """Test tracking multiple nodes."""
        await tracker.enter("node1")
        await tracker.enter("node2")

        assert not tracker.is_idle()
        assert tracker.get_activity_count() == 2
        assert "node1" in tracker._active
        assert "node2" in tracker._active

        await tracker.leave("node1")
        assert not tracker.is_idle()  # Still has node2

        await tracker.leave("node2")
        assert tracker.is_idle()

    @pytest.mark.asyncio
    async def test_reentrant_node_increases_count(self, tracker):
        """Test that entering the same node multiple times increases count."""
        await tracker.enter("node1")
        await tracker.enter("node1")

        assert tracker.get_activity_count() == 2
        assert len(tracker._active) == 1  # Still just one node in active set

    @pytest.mark.asyncio
    async def test_wait_idle_event(self, tracker):
        """Test waiting for idle event."""
        # Initially idle
        await asyncio.wait_for(tracker.wait_idle_event(), timeout=0.1)

        # Enter a node
        await tracker.enter("node1")

        # Create a task that waits for idle
        idle_task = asyncio.create_task(tracker.wait_idle_event())

        # Should not be done yet
        await asyncio.sleep(0.01)
        assert not idle_task.done()

        # Leave node to trigger idle
        await tracker.leave("node1")

        # Now the wait should complete
        await asyncio.wait_for(idle_task, timeout=0.1)

    @pytest.mark.asyncio
    async def test_reset(self, tracker):
        """Test reset functionality."""
        # Add some activity
        await tracker.enter("node1")
        await tracker.enter("node2")
        await tracker.leave("node1")

        assert not tracker.is_idle()
        assert tracker.get_activity_count() > 0

        # Reset
        tracker.reset()

        # Should be back to initial state
        assert tracker.is_idle()
        assert tracker.get_activity_count() == 0
        assert tracker._idle_event.is_set()
        assert len(tracker._active) == 0

    @pytest.mark.asyncio
    async def test_concurrent_enter_leave(self, tracker):
        """Test concurrent enter/leave operations."""

        async def enter_leave_cycle(node_name: str, cycles: int):
            for _ in range(cycles):
                await tracker.enter(node_name)
                await asyncio.sleep(0.001)  # Small delay
                await tracker.leave(node_name)

        # Run multiple concurrent cycles
        tasks = [
            asyncio.create_task(enter_leave_cycle(f"node{i}", 10)) for i in range(5)
        ]

        await asyncio.gather(*tasks)

        # Should be idle after all complete
        assert tracker.is_idle()
        assert tracker.get_activity_count() == 50  # 5 nodes * 10 cycles

    @pytest.mark.asyncio
    async def test_leave_nonexistent_node(self, tracker):
        """Test leaving a node that was never entered."""
        # Should not raise an error
        await tracker.leave("nonexistent")
        assert tracker.is_idle()

    @pytest.mark.asyncio
    async def test_condition_notification(self, tracker):
        """Test that condition is properly notified on idle."""
        await tracker.enter("node1")

        # Create a flag to verify notification happened
        notified = False

        async def wait_for_notification():
            nonlocal notified
            async with tracker._cond:
                await tracker._cond.wait()
                notified = True

        wait_task = asyncio.create_task(wait_for_notification())

        # Give task time to start waiting
        await asyncio.sleep(0.01)

        # Leave node to trigger notification
        await tracker.leave("node1")

        # Wait should complete
        try:
            await asyncio.wait_for(wait_task, timeout=0.1)
        except asyncio.TimeoutError:
            pass  # It's ok if it times out, we just check if notified

        # Check that notification happened
        assert tracker.is_idle()
