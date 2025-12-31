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
        """Tracker starts idle with no work recorded."""
        assert await tracker.is_idle()
        assert await tracker.is_quiescent() is False
        assert await tracker.get_activity_count() == 0
        assert (await tracker.get_metrics())["uncommitted_messages"] == 0

    @pytest.mark.asyncio
    async def test_enter_and_leave_updates_activity(self, tracker):
        """Entering and leaving nodes updates activity counts."""
        await tracker.enter("node1")

        assert not await tracker.is_idle()
        assert await tracker.get_activity_count() == 1
        assert "node1" in tracker._active

        await tracker.leave("node1")

        assert await tracker.is_idle()
        # No commits yet so quiescence is still False
        assert await tracker.is_quiescent() is False
        assert await tracker.get_activity_count() == 1

    @pytest.mark.asyncio
    async def test_message_tracking_and_quiescence(self, tracker):
        """Published/committed message tracking drives quiescence detection."""
        await tracker.on_messages_published(2)
        assert await tracker.is_quiescent() is False
        assert (await tracker.get_metrics())["uncommitted_messages"] == 2

        await tracker.on_messages_committed(1)
        assert await tracker.is_quiescent() is False
        assert (await tracker.get_metrics())["uncommitted_messages"] == 1

        await tracker.on_messages_committed(1)
        assert await tracker.is_quiescent() is True
        assert (await tracker.get_metrics())["uncommitted_messages"] == 0

    @pytest.mark.asyncio
    async def test_wait_for_quiescence(self, tracker):
        """wait_for_quiescence resolves when work finishes."""
        await tracker.on_messages_published(1)

        async def finish_work():
            await asyncio.sleep(0.01)
            await tracker.on_messages_committed(1)

        asyncio.create_task(finish_work())

        result = await tracker.wait_for_quiescence(timeout=0.5)
        assert result is True
        assert await tracker.is_quiescent() is True

    @pytest.mark.asyncio
    async def test_wait_for_quiescence_timeout(self, tracker):
        """wait_for_quiescence returns False on timeout."""
        result = await tracker.wait_for_quiescence(timeout=0.01)
        assert result is False
        assert await tracker.is_quiescent() is False

    @pytest.mark.asyncio
    async def test_reset(self, tracker):
        """Reset clears activity and quiescence state."""
        await tracker.enter("node1")
        await tracker.on_messages_published(1)
        await tracker.on_messages_committed(1)

        tracker.reset()

        assert await tracker.is_idle()
        assert await tracker.is_quiescent() is False
        assert await tracker.get_activity_count() == 0
        assert (await tracker.get_metrics())["total_committed"] == 0

    @pytest.mark.asyncio
    async def test_force_stop(self, tracker):
        """Force stop terminates workflow even with uncommitted messages."""
        await tracker.on_messages_published(2)
        assert await tracker.is_quiescent() is False
        assert await tracker.should_terminate() is False

        await tracker.force_stop()

        # Not quiescent (uncommitted messages still exist)
        assert await tracker.is_quiescent() is False
        # But should_terminate is True due to force stop
        assert await tracker.should_terminate() is True
        assert tracker._force_stopped is True

    @pytest.mark.asyncio
    async def test_should_terminate_on_quiescence(self, tracker):
        """should_terminate is True when naturally quiescent."""
        await tracker.on_messages_published(1)
        await tracker.on_messages_committed(1)

        assert await tracker.is_quiescent() is True
        assert await tracker.should_terminate() is True
        assert tracker._force_stopped is False

    @pytest.mark.asyncio
    async def test_force_stop_triggers_quiescence_event(self, tracker):
        """Force stop sets the quiescence event so waiters can proceed."""
        await tracker.on_messages_published(1)

        # Event should not be set yet
        assert not tracker._quiescence_event.is_set()

        await tracker.force_stop()

        # Event should now be set
        assert tracker._quiescence_event.is_set()

    @pytest.mark.asyncio
    async def test_reset_clears_force_stop(self, tracker):
        """Reset clears the force stop flag."""
        await tracker.force_stop()
        assert tracker._force_stopped is True

        tracker.reset()

        assert tracker._force_stopped is False
        assert await tracker.should_terminate() is False
