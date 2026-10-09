import asyncio

import pytest

from textual._queue import Queue


async def test_get_rechecks_after_nowait_consumer_drains_wakeup():
    queue = Queue()
    waiting = asyncio.create_task(queue.get())
    try:
        await asyncio.sleep(0)
        queue.put_nowait("first")
        assert queue.get_nowait() == "first"
        await asyncio.sleep(0)
        assert not waiting.done()
        queue.put_nowait("second")
        assert await asyncio.wait_for(waiting, 1) == "second"
        assert queue.empty()
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)


async def test_one_item_does_not_satisfy_two_waiting_consumers():
    queue = Queue()
    first = asyncio.create_task(queue.get())
    second = asyncio.create_task(queue.get())
    try:
        await asyncio.sleep(0)
        queue.put_nowait("first")
        assert await asyncio.wait_for(first, 1) == "first"
        assert not second.done()
        queue.put_nowait("second")
        assert await asyncio.wait_for(second, 1) == "second"
        assert queue.empty()
    finally:
        first.cancel()
        second.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


async def test_cancelled_waiter_does_not_lose_wakeup():
    queue = Queue()
    first = asyncio.create_task(queue.get())
    second = asyncio.create_task(queue.get())
    try:
        await asyncio.sleep(0)
        queue.put_nowait(None)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert await asyncio.wait_for(second, 1) is None
        with pytest.raises(asyncio.QueueEmpty):
            queue.get_nowait()
        assert not queue.ready_event.is_set()
    finally:
        first.cancel()
        second.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
