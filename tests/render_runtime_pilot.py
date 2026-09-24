"""Lazy renderer construction, independent cancellation and failed-client renewal."""

import asyncio
from pathlib import Path
from threading import Event, get_ident
from typing import TypeVar
import unittest
from unittest.mock import patch

from toad.render_runtime import PersistentRenderer
from toad.render_service import RenderServiceConfig
from toad.render_tasks import PatchRenderTask, RenderTask
from toad.render_zmq import PersistentRendererPool, RendererEndpoint, RendererSessionFailed

ResultT = TypeVar("ResultT")


class ControlledPool(PersistentRendererPool):
    def __init__(self, endpoint: RendererEndpoint, config: RenderServiceConfig, *, fail: bool = False) -> None:
        super().__init__(endpoint, config)
        self.fail = fail
        self.calls = 0
        self.drained = asyncio.Event()

    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        self.calls += 1
        if self.fail:
            raise RendererSessionFailed("fixture failure")
        return task.execute()

    async def aclose(self) -> None:
        await super().aclose()
        self.drained.set()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_construct_and_unused_close_do_not_fingerprint_or_start_backend(self) -> None:
        with patch("toad.render_runtime.RendererEndpoint.for_runtime") as resolve:
            renderer = PersistentRenderer(Path("/unused-render-test"))
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
            renderer = PersistentRenderer(endpoint.directory, config)
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
            renderer = PersistentRenderer(endpoint.directory, config)
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
