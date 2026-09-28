"""Retirement during worker delivery must not publish stale prepared data."""

import asyncio
from dataclasses import dataclass
from threading import Event
from unittest.mock import patch

import toad.work_preparation as preparation
from toad.work_preparation import (
    PreparationRuntime, PreparationScope, ReusableWork, ScopedWork, ThreadWork, WorkKey,
)
from work_preparation_pilot import Backend


@dataclass(frozen=True)
class SnapshotWork(ReusableWork[list[str]], ScopedWork[list[str]], ThreadWork[list[str]]):
    scope: PreparationScope

    @property
    def work_key(self) -> WorkKey:
        return WorkKey(type(self), "snapshot", self.scope)

    def prepare(self) -> list[str]:
        return ["prepared"]


async def held_delivery(*, cached: bool, shutdown: bool) -> None:
    backend = Backend()
    runtime = PreparationRuntime(backend)
    scope = PreparationScope()
    work = SnapshotWork(scope)
    if cached:
        await runtime.submit(work)
    entered, release = Event(), Event()
    original = preparation.deepcopy
    close = None

    def held_copy(value):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Test did not release delivery")
        return original(value)

    try:
        with patch.object(preparation, "deepcopy", held_copy):
            waiter = asyncio.create_task(runtime.submit(work))
            assert await asyncio.to_thread(entered.wait, 2)
            assert runtime.hits == int(cached)
            if shutdown:
                close = asyncio.create_task(runtime.aclose())
                await asyncio.sleep(0)
                assert runtime._closed and not close.done(), "Shutdown did not drain copying"
            else:
                runtime.discard_scope(scope)
            release.set()
            try:
                await waiter
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError(f"Retired result delivered: cached={cached}, shutdown={shutdown}")
    finally:
        release.set()
        if close is not None:
            await close
        await runtime.aclose()
    assert backend.closes == 1 and not runtime._pending and not runtime._thread_tasks


async def queued_thread_during_shutdown() -> None:
    runtime = PreparationRuntime(Backend())
    release = Event()
    entered = [Event() for _ in range(4)]
    late_started = Event()

    def occupy(index):
        entered[index].set()
        if not release.wait(5):
            raise TimeoutError("Test did not release thread")

    workers = [asyncio.create_task(runtime.run_thread(occupy, index)) for index in range(4)]
    close = queued = None
    try:
        for event in entered:
            assert await asyncio.to_thread(event.wait, 2)
        queued = asyncio.create_task(runtime.run_thread(late_started.set))
        await asyncio.sleep(0)
        close = asyncio.create_task(runtime.aclose())
        await asyncio.sleep(0)
        assert runtime._closed and not close.done()
        release.set()
        await asyncio.gather(*workers)
        try:
            await queued
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("Queued worker started after shutdown")
        assert not late_started.is_set()
    finally:
        release.set()
        await asyncio.gather(*workers, return_exceptions=True)
        if queued is not None:
            await asyncio.gather(queued, return_exceptions=True)
        if close is not None:
            await close
        await runtime.aclose()


async def main():
    for cached in (False, True):
        for shutdown in (False, True):
            await held_delivery(cached=cached, shutdown=shutdown)
    await queued_thread_during_shutdown()
    print("preparation delivery: fresh/cached retirement, shutdown drainage and queued-worker rejection passed")


if __name__ == "__main__":
    asyncio.run(main())
