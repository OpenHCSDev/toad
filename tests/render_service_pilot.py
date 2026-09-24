"""Typed command decoding and bounded server-side renderer admission."""

from concurrent.futures import Future
from collections.abc import Callable
import unittest
from unittest.mock import patch
from uuid import uuid4

from rich.text import Text
from toad.render_backend import Renderer
from toad.render_protocol import (
    AcknowledgeRender, CancelRender, PollRender, ReleaseRenderer, RenderCommand,
    RenderCommandKind, RenderStatus, SubmitRender, decode_command, encode_command,
)
from toad.render_service import RenderService, RenderServiceConfig
from toad.render_tasks import PatchRenderTask, RendererResult, RenderTask
from toad.widgets.patch_diff import PreparedPatch


class ControlledExecutor:
    def __init__(self) -> None:
        self.futures: list[Future[RendererResult]] = []

    def submit(self, function: Callable[[], RendererResult]) -> Future[RendererResult]:
        future: Future[RendererResult] = Future()
        future.set_running_or_notify_cancel()
        self.futures.append(future)
        return future

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        pass


class ServiceTests(unittest.TestCase):
    def test_nominal_abstract_contracts(self) -> None:
        for abstract in (Renderer, RenderTask, RenderCommand):
            with self.assertRaises(TypeError):
                abstract()

    def test_wire_boundary_rejects_mismatched_commands(self) -> None:
        client, request = uuid4(), uuid4()
        command = SubmitRender(client, request, PatchRenderTask("patch", False, True))
        self.assertEqual(decode_command(encode_command(command)), command)
        with self.assertRaises(TypeError):
            decode_command({"type": RenderCommandKind.CANCEL.value, "command": command})

    def test_cancel_keeps_running_capacity_until_complete_and_acknowledged(self) -> None:
        executor = ControlledExecutor()
        with patch("toad.render_service.ProcessPoolExecutor", return_value=executor):
            service = RenderService(RenderServiceConfig(max_workers=1, max_pending=1))
        client, first, second = uuid4(), uuid4(), uuid4()
        task = PatchRenderTask("patch", False, True)
        self.assertIs(service.dispatch(SubmitRender(client, first, task)).status, RenderStatus.ACCEPTED)
        self.assertIs(service.dispatch(CancelRender(client, first)).status, RenderStatus.ACKNOWLEDGED)
        self.assertIs(service.dispatch(PollRender(client, first)).status, RenderStatus.PENDING)
        self.assertIs(service.dispatch(SubmitRender(client, second, task)).status, RenderStatus.BUSY)
        executor.futures[0].set_result(PreparedPatch((False, True), None, None, Text("unused")))
        self.assertIs(service.dispatch(PollRender(client, first)).status, RenderStatus.CANCELLED)
        self.assertEqual(service.pending_count, 1)
        service.dispatch(AcknowledgeRender(client, first))
        self.assertEqual(service.pending_count, 0)
        self.assertIs(service.dispatch(SubmitRender(client, second, task)).status, RenderStatus.ACCEPTED)
        service.close()

    def test_result_retry_owner_isolation_and_abandoned_client_cleanup(self) -> None:
        executor = ControlledExecutor()
        with patch("toad.render_service.ProcessPoolExecutor", return_value=executor):
            service = RenderService(RenderServiceConfig(max_workers=1, max_pending=2))
        client, foreign, request = uuid4(), uuid4(), uuid4()
        service.dispatch(SubmitRender(client, request, PatchRenderTask("patch", False, True)))
        self.assertIs(service.dispatch(PollRender(foreign, request)).status, RenderStatus.UNKNOWN)
        expected = PreparedPatch((False, True), None, None, Text("result"))
        executor.futures[0].set_result(expected)
        for _ in range(2):
            reply = service.dispatch(PollRender(client, request))
            self.assertIs(reply.status, RenderStatus.COMPLETE)
            self.assertIs(reply.result, expected)
        service.dispatch(ReleaseRenderer(client))
        self.assertEqual(service.pending_count, 0)
        running = uuid4()
        service.dispatch(SubmitRender(client, running, PatchRenderTask("patch", False, True)))
        service.dispatch(ReleaseRenderer(client))
        self.assertEqual(service.pending_count, 1)
        executor.futures[1].set_result(expected)
        service.reap()
        self.assertEqual(service.pending_count, 0)
        service.close()

    def test_expired_lease_retains_running_capacity_then_reclaims_without_ack(self) -> None:
        executor = ControlledExecutor()
        with patch("toad.render_service.ProcessPoolExecutor", return_value=executor):
            service = RenderService(RenderServiceConfig(max_workers=1, max_pending=1, client_lease_seconds=10))
        client, request = uuid4(), uuid4()
        with patch("toad.render_service.time.monotonic", return_value=100):
            service.dispatch(SubmitRender(client, request, PatchRenderTask("patch", False, True)))
        service.reap(now=111)
        self.assertEqual(service.pending_count, 1)
        self.assertNotIn(client, service._clients)
        executor.futures[0].set_result(PreparedPatch((False, True), None, None, Text("unused")))
        service.reap(now=112)
        self.assertEqual(service.pending_count, 0)
        service.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
