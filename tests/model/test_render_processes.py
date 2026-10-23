"""The render process pool: spawned workers, errors, bounded submissions, cancellation and shutdown. No app, widgets or agents."""

from contextlib import asynccontextmanager
import asyncio
import multiprocessing
import os
from pathlib import Path
import pickle
import time
from unittest.mock import patch

import pytest

from agent_comms.launch_runtime import ThreadLaunch

from toad.render_processes import RenderProcessPool


# Construction at import time is intentional: spawn reimports this file.
IMPORT_POOL = RenderProcessPool()


def worker_info():
    return (
        os.getpid(),
        multiprocessing.get_start_method(),
        ThreadLaunch.inherited(os.environ),
    )


def fail():
    raise ValueError("worker failure")


def cpu_work(seconds, started=None, release=None, error=False):
    if started:
        Path(started).write_text(str(os.getpid()))
    deadline = time.monotonic() + seconds
    value = 1
    while time.monotonic() < deadline:
        for _ in range(10000):
            value = (value * 1664525 + 1013904223) & 0xFFFFFFFF
        if release and Path(release).exists():
            break
    if error:
        raise ValueError("abandoned worker failure")
    return os.getpid(), value


async def wait_for_file(path):
    async with asyncio.timeout(10):
        while not path.exists():
            await asyncio.sleep(0.01)


@asynccontextmanager
async def pools():
    """Yield a pool factory; every pool made is closed and no worker process outlives the test."""
    children_before = {p.pid for p in multiprocessing.active_children()}
    made = []

    def make(**kwargs):
        pool = RenderProcessPool(**kwargs)
        made.append(pool)
        return pool

    try:
        yield make
    finally:
        for pool in made:
            await pool.aclose()
    assert {p.pid for p in multiprocessing.active_children()} == children_before


async def test_workers_are_spawned_apart_from_the_parent_and_errors_propagate(monkeypatch):
    assert IMPORT_POOL._executor is None
    async with pools() as make:
        pool = make()
        assert pool._executor is None
        launch = ThreadLaunch("pilot-only", "/pilot-only", frozenset({"pilot"}), managed=True)
        for name, value in launch.encode().items():
            monkeypatch.setenv(name, value)
        assert ThreadLaunch.inherited(os.environ) == launch.encode()
        pid, method, inherited = await pool.run(worker_info)
        assert pid != os.getpid()
        assert method == "spawn"
        assert inherited == {}
        with pytest.raises(ValueError, match="worker failure"):
            await pool.run(fail)
        # Serialization errors also propagate, without executing locally.
        with pytest.raises((AttributeError, TypeError, pickle.PicklingError)):
            await pool.run(lambda: os.getpid())
        assert (await pool.run(worker_info))[0] != os.getpid()


async def test_canceled_waiter_retains_submission_capacity(tmp_path):
    async with pools() as make:
        pool = make(max_workers=2, max_pending=1)
        errors = []
        loop = asyncio.get_running_loop()
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, context: errors.append(context))
        try:
            started, release = tmp_path / "started", tmp_path / "release"
            first = asyncio.create_task(pool.run(cpu_work, 10, str(started), str(release), True))
            await wait_for_file(started)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            # Spy on actual executor admission, not just caller completion.
            with patch.object(pool._executor, "submit", wraps=pool._executor.submit) as submit:
                second = asyncio.create_task(pool.run(worker_info))
                await asyncio.sleep(0.15)
                assert submit.call_count == 0
                assert not second.done()
                second.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await second
                third = asyncio.create_task(pool.run(worker_info))
                await asyncio.sleep(0.05)
                assert submit.call_count == 0
                release.touch()
                await asyncio.wait_for(third, 10)
                assert submit.call_count == 1
            assert first.cancelled()
            await pool.aclose()
            assert not errors, errors
        finally:
            loop.set_exception_handler(old_handler)


async def test_busy_worker_does_not_stall_the_loop_and_shutdown_survives_cancellation(tmp_path):
    async with pools() as make:
        pool = make(max_workers=1, max_pending=1)
        started, release = tmp_path / "started", tmp_path / "release"
        job = asyncio.create_task(pool.run(cpu_work, 10, str(started), str(release)))
        await wait_for_file(started)
        for _ in range(20):
            await asyncio.sleep(0.01)
        assert not job.done()
        blocked = asyncio.create_task(pool.run(worker_info))
        await asyncio.sleep(0)
        close = asyncio.create_task(pool.aclose())
        await asyncio.sleep(0.05)
        assert pool.closed
        assert not close.done()
        with pytest.raises(RuntimeError, match="closed"):
            await blocked
        close.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close
        assert not pool._shutdown.cancelled()
        release.touch()
        await asyncio.wait_for(asyncio.gather(pool.aclose(), pool.aclose()), 10)
        assert (await job)[0] != os.getpid()
        assert not pool._pending
        with pytest.raises(RuntimeError, match="closed"):
            await pool.run(worker_info)


async def test_parallel_workers_and_total_submission_bound(tmp_path):
    async with pools() as make:
        pool = make(max_workers=2, max_pending=2)
        first_started, second_started, release = tmp_path / "first", tmp_path / "second", tmp_path / "release"
        first = asyncio.create_task(pool.run(cpu_work, 10, str(first_started), str(release)))
        second = asyncio.create_task(pool.run(cpu_work, 10, str(second_started), str(release)))
        await asyncio.gather(wait_for_file(first_started), wait_for_file(second_started))
        assert first_started.read_text() != second_started.read_text()
        with patch.object(pool._executor, "submit", wraps=pool._executor.submit) as submit:
            third = asyncio.create_task(pool.run(worker_info))
            await asyncio.sleep(0.05)
            assert submit.call_count == 0
            release.touch()
            await asyncio.wait_for(asyncio.gather(first, second, third), 10)
            assert submit.call_count == 1


async def test_unused_pool_closes_and_rejects_bad_limits():
    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            RenderProcessPool(max_pending=value)
        with pytest.raises(ValueError):
            RenderProcessPool(max_workers=value)
    async with pools() as make:
        pool = make()
        await pool.aclose()
        await pool.aclose()
        assert pool.closed
        assert pool._executor is None
        with pytest.raises(RuntimeError, match="closed"):
            await pool.run(worker_info)
