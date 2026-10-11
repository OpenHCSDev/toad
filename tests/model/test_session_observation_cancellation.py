"""A retired observation read cancels neither its caller nor the callback that awaits it."""

import asyncio

import pytest

from toad.session_observation import SessionObservation


async def reached(event):
    async with asyncio.timeout(10):
        await event.wait()


class ReadSource:
    is_attached = True
    agent = object()


class WaitingObservation(SessionObservation):
    def __init__(self, source):
        super().__init__(source)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def read(self, agent):
        self.entered.set()
        await self.release.wait()

    def publish(self, view, result):
        pass

    def failed(self, view, error):
        raise error


async def test_retired_read_does_not_cancel_its_callback():
    source = ReadSource()
    owner = WaitingObservation(source)
    callback = asyncio.create_task(owner.refresh())
    await reached(owner.entered)
    await owner.close()
    await callback
    assert not callback.cancelled()


async def test_retirement_preserves_genuine_callback_cancellation():
    source = ReadSource()
    owner = WaitingObservation(source)
    callback = asyncio.create_task(owner.refresh())
    await reached(owner.entered)
    callback.cancel()
    await owner.close()
    with pytest.raises(asyncio.CancelledError):
        await callback
