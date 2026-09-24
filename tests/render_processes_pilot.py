"""Headless process-service pilot; no App, widgets, agents, or UI is launched."""

import asyncio
import multiprocessing
import os
from pathlib import Path
import pickle
import tempfile
import time
import unittest
from unittest.mock import patch

from toad.render_processes import RenderProcessPool


# Construction at import time is intentional: spawn reimports this file.
IMPORT_POOL = RenderProcessPool()


def worker_info():
    return (
        os.getpid(),
        multiprocessing.get_start_method(),
        os.environ.get("PI_AGENT_ID"),
        os.environ.get("AGENT_COMMS_THREAD"),
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


class RenderProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.children_before = {p.pid for p in multiprocessing.active_children()}
        self.pools = []

    def pool(self, **kwargs):
        pool = RenderProcessPool(**kwargs)
        self.pools.append(pool)
        return pool

    async def asyncTearDown(self):
        for pool in self.pools:
            await pool.aclose()
        self.assertEqual(
            {p.pid for p in multiprocessing.active_children()}, self.children_before
        )

    async def test_spawn_identity_errors_and_import_safety(self):
        self.assertIsNone(IMPORT_POOL._executor)
        pool = self.pool()
        self.assertIsNone(pool._executor)
        with patch.dict(os.environ, PI_AGENT_ID="pilot-only", AGENT_COMMS_THREAD="pilot-only"):
            pid, method, agent, thread = await pool.run(worker_info)
            self.assertEqual(os.environ["PI_AGENT_ID"], "pilot-only")
        self.assertNotEqual(pid, os.getpid())
        self.assertEqual(method, "spawn")
        self.assertIsNone(agent)
        self.assertIsNone(thread)
        with self.assertRaisesRegex(ValueError, "worker failure"):
            await pool.run(fail)
        # Serialization errors also propagate, without executing locally.
        with self.assertRaises((AttributeError, TypeError, pickle.PicklingError)):
            await pool.run(lambda: os.getpid())
        self.assertNotEqual((await pool.run(worker_info))[0], os.getpid())

    async def test_canceled_waiter_retains_submission_capacity(self):
        pool = self.pool(max_workers=2, max_pending=1)
        errors = []
        loop = asyncio.get_running_loop()
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, context: errors.append(context))
        try:
            with tempfile.TemporaryDirectory() as directory:
                started = Path(directory) / "started"
                release = Path(directory) / "release"
                first = asyncio.create_task(pool.run(cpu_work, 10, str(started), str(release), True))
                await wait_for_file(started)
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                # Spy on actual executor admission, not just caller completion.
                with patch.object(pool._executor, "submit", wraps=pool._executor.submit) as submit:
                    second = asyncio.create_task(pool.run(worker_info))
                    await asyncio.sleep(0.15)
                    self.assertEqual(submit.call_count, 0)
                    self.assertFalse(second.done())
                    second.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await second
                    third = asyncio.create_task(pool.run(worker_info))
                    await asyncio.sleep(0.05)
                    self.assertEqual(submit.call_count, 0)
                    release.touch()
                    await asyncio.wait_for(third, 10)
                    self.assertEqual(submit.call_count, 1)
                self.assertTrue(first.cancelled())
                await pool.aclose()
                self.assertFalse(errors, errors)
        finally:
            loop.set_exception_handler(old_handler)

    async def test_cpu_responsiveness_and_cancel_resistant_shutdown(self):
        pool = self.pool(max_workers=1, max_pending=1)
        with tempfile.TemporaryDirectory() as directory:
            started = Path(directory) / "started"
            release = Path(directory) / "release"
            job = asyncio.create_task(pool.run(cpu_work, 10, str(started), str(release)))
            await wait_for_file(started)
            ticks = []
            for _ in range(20):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.01)
            self.assertFalse(job.done())
            max_gap = max(b - a for a, b in zip(ticks, ticks[1:]))
            self.assertLess(max_gap, 0.2)
            blocked = asyncio.create_task(pool.run(worker_info))
            await asyncio.sleep(0)
            close = asyncio.create_task(pool.aclose())
            await asyncio.sleep(0.05)
            self.assertTrue(pool.closed)
            self.assertFalse(close.done())
            with self.assertRaisesRegex(RuntimeError, "closed"):
                await blocked
            close.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await close
            self.assertFalse(pool._shutdown.cancelled())
            release.touch()
            await asyncio.wait_for(asyncio.gather(pool.aclose(), pool.aclose()), 10)
            self.assertNotEqual((await job)[0], os.getpid())
            self.assertFalse(pool._pending)
            with self.assertRaisesRegex(RuntimeError, "closed"):
                await pool.run(worker_info)
            print(f"CPU heartbeat: {len(ticks)} ticks, maximum gap {max_gap:.3f}s")

    async def test_parallel_workers_and_total_submission_bound(self):
        pool = self.pool(max_workers=2, max_pending=2)
        with tempfile.TemporaryDirectory() as directory:
            first_started = Path(directory) / "first"
            second_started = Path(directory) / "second"
            release = Path(directory) / "release"
            first = asyncio.create_task(pool.run(cpu_work, 10, str(first_started), str(release)))
            second = asyncio.create_task(pool.run(cpu_work, 10, str(second_started), str(release)))
            await asyncio.gather(wait_for_file(first_started), wait_for_file(second_started))
            self.assertNotEqual(first_started.read_text(), second_started.read_text())
            with patch.object(pool._executor, "submit", wraps=pool._executor.submit) as submit:
                third = asyncio.create_task(pool.run(worker_info))
                await asyncio.sleep(0.05)
                self.assertEqual(submit.call_count, 0)
                release.touch()
                await asyncio.wait_for(asyncio.gather(first, second, third), 10)
                self.assertEqual(submit.call_count, 1)

    async def test_unused_close_and_validation(self):
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                RenderProcessPool(max_pending=value)
            with self.assertRaises(ValueError):
                RenderProcessPool(max_workers=value)
        pool = self.pool()
        await pool.aclose()
        await pool.aclose()
        self.assertTrue(pool.closed)
        self.assertIsNone(pool._executor)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await pool.run(worker_info)


if __name__ == "__main__":
    unittest.main(verbosity=2)
