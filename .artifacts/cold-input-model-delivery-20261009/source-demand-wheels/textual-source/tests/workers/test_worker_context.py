"""Finished workers must not stay rooted by task or executor-thread contexts."""

import asyncio
import gc
import platform
import weakref
from concurrent.futures import ThreadPoolExecutor

import pytest

from textual.app import App
from textual.worker import Worker, WorkerState, active_worker, get_current_worker


@pytest.mark.parametrize(
    "outcome, expected_state",
    [("success", WorkerState.SUCCESS), ("error", WorkerState.ERROR), ("cancel", WorkerState.CANCELLED)],
)
async def test_worker_restores_enclosing_context(outcome, expected_state):
    async def work():
        assert get_current_worker() is child
        if outcome == "error":
            raise ValueError("work failed")
        if outcome == "cancel":
            raise asyncio.CancelledError()
        return 42

    app = App()
    async with app.run_test():
        parent = Worker(app, work, name="enclosing")
        child = Worker(app, work, exit_on_error=False)
        token = active_worker.set(parent)
        try:
            await child._run(app)
            assert child.state is expected_state
            assert get_current_worker() is parent
        finally:
            active_worker.reset(token)


@pytest.mark.parametrize("fail", [False, True])
async def test_executor_thread_does_not_keep_completed_worker(fail):
    def work():
        assert get_current_worker().name == "threaded"
        if fail:
            raise ValueError("thread work failed")
        return 42

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as executor:
        loop.set_default_executor(executor)
        app = App()
        async with app.run_test():
            worker = Worker(app, work, name="threaded", thread=True, exit_on_error=False)
            await worker._run(app)
            assert worker.state is (WorkerState.ERROR if fail else WorkerState.SUCCESS)
            # Reuse the exact executor thread, outside any Worker. An unrelated
            # job must neither see nor retain the preceding worker and its node.
            assert await loop.run_in_executor(executor, active_worker.get, None) is None


@pytest.mark.skipif(platform.python_implementation() != "CPython", reason="Reference-count lifetime check")
@pytest.mark.parametrize("kind", ["async", "callable", "coroutine", "awaitable"])
async def test_completed_workers_are_released_without_cyclic_collection(kind):
    def sync_work():
        assert get_current_worker().name == "lifetime"
        return 42

    async def async_work():
        return sync_work()

    app = App()
    async with app.run_test() as pilot:
        await pilot.pause()
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            workers = [
                app.run_worker(
                    sync_work if kind == "callable" else async_work() if kind == "awaitable" else async_work,
                    name="lifetime", thread=kind != "async",
                )
                for _ in range(20)
            ]
            assert await asyncio.gather(*(worker.wait() for worker in workers)) == [42] * 20
            references = [weakref.ref(worker) for worker in workers]
            del workers
            await pilot.pause()
            assert not app.workers
            assert not any(reference() is not None for reference in references)
        finally:
            if was_enabled:
                gc.enable()
