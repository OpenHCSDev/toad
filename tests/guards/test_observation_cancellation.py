"""Cancellation custody, in addition to the actual installed native swap gate."""

import asyncio

import pytest

from toad.session_observation import SessionObservation


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


def test_retired_read_does_not_cancel_its_callback():
    async def run():
        source = ReadSource()
        owner = WaitingObservation(source)
        callback = asyncio.create_task(owner.refresh())
        await owner.entered.wait()
        await owner.close()
        await callback
        assert not callback.cancelled()

    asyncio.run(run())


def test_retirement_preserves_genuine_callback_cancellation():
    async def run():
        source = ReadSource()
        owner = WaitingObservation(source)
        callback = asyncio.create_task(owner.refresh())
        await owner.entered.wait()
        callback.cancel()
        await owner.close()
        with pytest.raises(asyncio.CancelledError):
            await callback

    asyncio.run(run())
