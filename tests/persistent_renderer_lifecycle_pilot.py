"""Deterministic transport failure/cancellation tests for the real async adapter."""

import asyncio
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch
from uuid import UUID

from toad.render_protocol import (
    AcknowledgeRender, CancelRender, PollRender, RenderReply, RendererCommand,
    RenderStatus, SubmitRender,
)
from toad.render_service import RenderServiceConfig, _initialize_render_worker
from toad.render_tasks import PatchRenderTask
from toad.render_zmq import (
    PersistentRendererPool, RendererConnection, RendererEndpoint, RendererServer, RendererSessionFailed,
)


class ControlledConnection(RendererConnection):
    def __init__(self, endpoint: RendererEndpoint, config: RenderServiceConfig, *, fail: bool) -> None:
        super().__init__(endpoint, config)
        self.polling = Event()
        self.proceed = Event()
        self.fail = fail
        self.cancelled = False
        self.acknowledged = False
        self.released = False
        self.closed = False
        self.calls = 0

    def exchange(self, command: RendererCommand) -> RenderReply:
        self.calls += 1
        if isinstance(command, SubmitRender):
            return RenderReply(RenderStatus.ACCEPTED, command.request_id)
        if isinstance(command, PollRender):
            if not self.polling.is_set():
                self.polling.set()
                if not self.proceed.wait(5):
                    raise AssertionError("Test did not release the controlled RPC")
            if self.fail:
                raise TimeoutError("Lost poll reply after accepted work")
            return RenderReply(RenderStatus.CANCELLED if self.cancelled else RenderStatus.PENDING,
                               command.request_id)
        if isinstance(command, CancelRender):
            self.cancelled = True
            return RenderReply(RenderStatus.ACKNOWLEDGED, command.request_id)
        if isinstance(command, AcknowledgeRender):
            self.acknowledged = True
            return RenderReply(RenderStatus.ACKNOWLEDGED, command.request_id)
        raise AssertionError(f"Unexpected command: {command}")

    def release(self, client_id: UUID) -> None:
        self.released = True

    def close(self) -> None:
        self.closed = True


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_rpc_wakes_admission_waiters_and_stops_lease_renewal(self) -> None:
        endpoint = RendererEndpoint(Path("/unused-render-test"), "test")
        config = RenderServiceConfig(max_workers=1, max_pending=1)
        connection = ControlledConnection(endpoint, config, fail=True)
        with patch("toad.render_zmq.RendererConnection", return_value=connection):
            pool = PersistentRendererPool(endpoint, config)
        task = PatchRenderTask("patch", False, True)
        first = asyncio.create_task(pool.submit(task))
        try:
            self.assertTrue(await asyncio.to_thread(connection.polling.wait, 2))
            waiting = asyncio.create_task(pool.submit(task))
            connection.proceed.set()
            for result in await asyncio.gather(first, waiting, return_exceptions=True):
                self.assertIsInstance(result, RendererSessionFailed)
            calls = connection.calls
            with self.assertRaises(RendererSessionFailed):
                await pool.submit(task)
            self.assertEqual(connection.calls, calls)
        finally:
            connection.proceed.set()
            await pool.aclose()
        self.assertFalse(pool._pending)
        self.assertTrue(connection.released and connection.closed)

    async def test_cancelled_caller_and_close_waiter_do_not_abandon_owned_teardown(self) -> None:
        endpoint = RendererEndpoint(Path("/unused-render-test"), "test")
        config = RenderServiceConfig(max_workers=1, max_pending=1)
        connection = ControlledConnection(endpoint, config, fail=False)
        with patch("toad.render_zmq.RendererConnection", return_value=connection):
            pool = PersistentRendererPool(endpoint, config)
        request = asyncio.create_task(pool.submit(PatchRenderTask("patch", False, True)))
        try:
            self.assertTrue(await asyncio.to_thread(connection.polling.wait, 2))
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            self.assertEqual(len(pool._pending), 1)
            closing = asyncio.create_task(pool.aclose())
            await asyncio.sleep(0)
            self.assertTrue(pool._closed)
            closing.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await closing
            connection.proceed.set()
            await pool.aclose()
        finally:
            connection.proceed.set()
            await pool.aclose()
        self.assertTrue(connection.cancelled and connection.acknowledged)
        self.assertTrue(connection.released and connection.closed)
        self.assertFalse(pool._pending)

    async def test_nonfinite_poll_intervals_rejected(self) -> None:
        endpoint = RendererEndpoint(Path("/unused-render-test"), "test")
        for interval in (0, -1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                PersistentRendererPool(endpoint, poll_interval=interval)

    async def test_startup_rejects_stale_build_before_constructing_service(self) -> None:
        endpoint = RendererEndpoint(Path("/unused-render-test"), "stale")
        with patch("toad.render_zmq.RenderService") as service:
            with self.assertRaisesRegex(RuntimeError, "changed before service startup"):
                await asyncio.to_thread(RendererServer, endpoint, RenderServiceConfig())
            service.assert_not_called()

    async def test_lazy_worker_rechecks_service_build_before_accepting_work(self) -> None:
        with patch("toad.render_service._initialize_worker") as initialize:
            with self.assertRaisesRegex(RuntimeError, "changed before worker startup"):
                await asyncio.to_thread(_initialize_render_worker, RenderServiceConfig(), "stale")
            initialize.assert_called_once_with()

    async def test_ipc_directory_is_private_and_existing_public_directory_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            endpoint = RendererEndpoint(root / "private", "test")
            endpoint.prepare_directory()
            self.assertEqual(endpoint.directory.stat().st_mode & 0o777, 0o700)
            endpoint.directory.chmod(0o755)
            with self.assertRaises(PermissionError):
                endpoint.prepare_directory()


if __name__ == "__main__":
    unittest.main(verbosity=2)
