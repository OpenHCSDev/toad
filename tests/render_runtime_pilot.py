"""Lazy renderer construction, independent cancellation and failed-client renewal."""

import asyncio
from pathlib import Path
from threading import Event, get_ident
from typing import TypeVar
import unittest
from unittest.mock import patch

from toad.render_runtime import PersistentRenderClient
from toad.render_service import RenderServiceConfig
from toad.render_tasks import PatchRenderTask
from toad.render_backend import RenderTask
from toad.render_zmq import PersistentRendererPool, RendererEndpoint, RendererSessionFailed
from toad.work_preparation import PreparedValue

ResultT = TypeVar("ResultT")


class ControlledPool(PersistentRendererPool):
    def __init__(self, endpoint: RendererEndpoint, config: RenderServiceConfig, *, fail: bool = False) -> None:
        super().__init__(endpoint, config)
        self.fail = fail
        self.calls = 0
        self.drained = asyncio.Event()

    async def capture(self, task: RenderTask[ResultT]):
        self.calls += 1
        if self.fail:
            raise RendererSessionFailed("fixture failure")
        return task.capture_result()

    async def aclose(self) -> None:
        await super().aclose()
        self.drained.set()


class HeldValue(PreparedValue):
    size = 0

    def __init__(self, value, entered, release):
        self.value, self.entered, self.release = value, entered, release

    def materialize(self):
        self.entered.set()
        if not self.release.wait(5):
            raise AssertionError("Test did not release delivery worker")
        return self.value.materialize()


class DeliveryPool(ControlledPool):
    def __init__(self, endpoint, config, entered, release):
        super().__init__(endpoint, config)
        self.entered, self.release = entered, release

    async def capture(self, task):
        return HeldValue(await super().capture(task), self.entered, self.release)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_delivery_is_joined_before_backend_close(self):
        entered, release = Event(), Event()
        pool = DeliveryPool(RendererEndpoint(Path("/unused-render-test"), "test"),
                            RenderServiceConfig(), entered, release)
        waiting = asyncio.create_task(pool.submit(PatchRenderTask("patch", False, True)))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            waiting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiting
            closing = asyncio.create_task(pool.aclose())
            await asyncio.sleep(0)
            self.assertFalse(pool.drained.is_set())
            self.assertFalse(closing.done())
            release.set()
            await closing
            self.assertTrue(pool.drained.is_set())
            self.assertFalse(pool._submissions)
        finally:
            release.set()
            await pool.aclose()

    async def test_construct_and_unused_close_do_not_fingerprint_or_start_backend(self) -> None:
        with patch("toad.render_runtime.RendererEndpoint.for_runtime") as resolve:
            renderer = PersistentRenderClient(Path("/unused-render-test"))
            self.assertIsNone(renderer.resolved_pool)
            await renderer.aclose()
            with self.assertRaisesRegex(RuntimeError, "closed"):
                await renderer.submit(PatchRenderTask("patch", False, True))
            resolve.assert_not_called()

    async def test_off_loop_resolution_survives_cancelled_waiter_and_closes_owned_pool(self) -> None:
        entered, proceed = Event(), Event()
        main_thread = get_ident()
        endpoint = RendererEndpoint(Path("/unused-render-test"), "test")
        config = RenderServiceConfig()
        pool = ControlledPool(endpoint, config)

        def resolve(directory: Path, supplied: RenderServiceConfig) -> RendererEndpoint:
            self.assertNotEqual(get_ident(), main_thread)
            entered.set()
            if not proceed.wait(5):
                raise AssertionError("Test did not release identity resolution")
            return endpoint

        with (patch("toad.render_runtime.RendererEndpoint.for_runtime", side_effect=resolve),
              patch("toad.render_runtime.PersistentRendererPool", return_value=pool)):
            renderer = PersistentRenderClient(endpoint.directory, config)
            waiting = asyncio.create_task(renderer.submit(PatchRenderTask("patch", False, True)))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                waiting.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await waiting
                closing = asyncio.create_task(renderer.aclose())
                await asyncio.sleep(0)
                self.assertFalse(closing.done())
                proceed.set()
                await closing
            finally:
                proceed.set()
                await renderer.aclose()
        self.assertTrue(pool.drained.is_set())
        self.assertEqual(pool.calls, 0)

    async def test_failed_request_is_not_replayed_and_next_request_uses_new_client(self) -> None:
        endpoint = RendererEndpoint(Path("/unused-render-test"), "test")
        config = RenderServiceConfig()
        failed, successor = ControlledPool(endpoint, config, fail=True), ControlledPool(endpoint, config)
        with (patch("toad.render_runtime.RendererEndpoint.for_runtime", return_value=endpoint),
              patch("toad.render_runtime.PersistentRendererPool", side_effect=[failed, successor])):
            renderer = PersistentRenderClient(endpoint.directory, config)
            task = PatchRenderTask("patch", False, True)
            try:
                with self.assertRaises(RendererSessionFailed):
                    await renderer.submit(task)
                result = await renderer.submit(task)
                self.assertTrue(failed.drained.is_set())
                self.assertEqual(failed.calls, 1)
                self.assertEqual(successor.calls, 1)
                self.assertEqual(result, task.execute())
                self.assertIs(renderer.resolved_pool, successor)
            finally:
                await renderer.aclose()
        self.assertTrue(successor.drained.is_set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
