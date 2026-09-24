"""Real typed ZMQ renderer reuse, cancellation and app-style data preparation."""

import asyncio
from pathlib import Path
import tempfile
import time

from toad.render_service import RenderServiceConfig
from toad.render_protocol import RenderReply, RendererCommand, RenderStatus, SubmitRender
from toad.render_tasks import PatchRenderTask
from toad.render_zmq import PersistentRendererPool, RendererEndpoint


class ObservedPool(PersistentRendererPool):
    def __init__(self, endpoint: RendererEndpoint, config: RenderServiceConfig) -> None:
        super().__init__(endpoint, config)
        self.accepted = asyncio.Event()

    async def _exchange(self, command: RendererCommand) -> RenderReply:
        reply = await super()._exchange(command)
        if isinstance(command, SubmitRender) and reply.status is RenderStatus.ACCEPTED:
            self.accepted.set()
        return reply


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-render-service-") as directory:
        config = RenderServiceConfig(max_workers=2, max_pending=2)
        endpoint = await asyncio.to_thread(RendererEndpoint.for_runtime, Path(directory), config)
        first = PersistentRendererPool(endpoint, config)
        second: PersistentRendererPool | None = None
        source = "--- x.py\n+++ x.py\n@@ -1,80 +1,80 @@\n" + "-old = 123\n+new = 456\n" * 80
        task = PatchRenderTask(source, False, True)
        try:
            results = await asyncio.gather(first.submit(task), first.submit(task))
            assert results[0].patch == results[1].patch
            client = first._connection.client
            assert client is not None and client.connected_endpoint is not None
            identity = client.connected_endpoint.process_identity
            await first.aclose()
            second = ObservedPool(endpoint, config)
            started = time.perf_counter()
            result = await second.submit(task)
            warm_ms = (time.perf_counter() - started) * 1000
            other = second._connection.client
            assert other is not None and other.connected_endpoint is not None
            assert other.connected_endpoint.process_identity == identity
            assert result.patch == results[0].patch
            second.accepted.clear()
            large = "--- x.py\n+++ x.py\n@@ -1,4000 +1,4000 @@\n" + "-old = 123\n+new = 456\n" * 4000
            waiting = asyncio.create_task(second.submit(PatchRenderTask(large, False, True)))
            await asyncio.wait_for(second.accepted.wait(), 5)
            waiting.cancel()
            try:
                await waiting
            except asyncio.CancelledError:
                pass
            await second.aclose()
            assert not second._pending
            print({"same_renderer_after_client_close": True, "reattach_and_patch_ms": round(warm_ms, 2),
                   "typed_data_parity": True, "cancelled_requests_drained": True,
                   "boundary": "real persistent renderer RPC; not terminal pixels"})
        finally:
            await first.aclose()
            if second is not None:
                await second.aclose()
            assert await first.shutdown_service()


if __name__ == "__main__":
    asyncio.run(main())
