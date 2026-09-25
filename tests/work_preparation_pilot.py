"""Shared preparation policies compose across models, rendering and consumers."""

import asyncio
from dataclasses import dataclass
import threading
from typing import ClassVar

from agent_comms import TranscriptEvent
from toad.render_backend import Renderer
from toad.render_tasks import MarkdownRenderTask, TranscriptRenderTask
from toad.work_preparation import (
    ContentAddressedWork, PreparationRuntime, PreparedRenderer, ReusableWork, ThreadWork,
)


@dataclass(frozen=True)
class ModelWork(ReusableWork[dict], ContentAddressedWork[dict], ThreadWork[dict]):
    revision: str
    calls: ClassVar[int] = 0
    worker_threads: ClassVar[list[int]] = []

    @property
    def inputs(self):
        return self.revision

    def prepare(self):
        type(self).calls += 1
        type(self).worker_threads.append(threading.get_ident())
        return {"rows": [self.revision]}


class Backend(Renderer):
    def __init__(self):
        self.calls = self.closes = 0

    async def submit(self, task):
        self.calls += 1
        return await asyncio.to_thread(task.execute)

    async def aclose(self):
        self.closes += 1


async def main():
    backend = Backend()
    runtime = PreparationRuntime(backend, max_entries=2, max_bytes=4096, max_pending=1)
    first, second = await asyncio.gather(runtime.submit(ModelWork("one")), runtime.submit(ModelWork("one")))
    assert ModelWork.calls == 1 and runtime.shared + runtime.hits == 1
    assert all(identity != threading.get_ident() for identity in ModelWork.worker_threads)
    first["rows"].append("consumer mutation")
    assert second == {"rows": ["one"]}
    assert await runtime.submit(ModelWork("one")) == second and ModelWork.calls == 1
    await runtime.submit(ModelWork("two"))
    await runtime.submit(ModelWork("three"))
    await runtime.submit(ModelWork("one"))
    assert ModelWork.calls == 4, "Evicted work was unexpectedly reused"
    assert len(runtime._ready) == 2 and runtime.retained_bytes <= runtime.max_bytes

    # The ordinary renderer API uses the same runtime, across unrelated callers.
    renderer = PreparedRenderer(runtime)
    task = TranscriptRenderTask((TranscriptEvent("assistant", "worker text"),))
    await asyncio.gather(renderer.submit(task), renderer.submit(task))
    await renderer.submit(task)
    assert backend.calls == 1
    fresh = MarkdownRenderTask("unchanged text", ".", False, True)
    await renderer.submit(fresh)
    await renderer.submit(fresh)
    assert backend.calls == 3, "Path-aware Markdown reused unversioned filesystem observations"

    entered, release, queued = threading.Event(), threading.Event(), threading.Event()

    @dataclass(frozen=True)
    class BlockingWork(ModelWork):
        def prepare(self):
            if self.revision == "blocked":
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release worker")
            else:
                queued.set()
            return super().prepare()

    # The identity inputs are plain data; the local test class is not serialized.
    waiter = asyncio.create_task(runtime.submit(BlockingWork("blocked")))
    assert await asyncio.to_thread(entered.wait, 2)
    waiter.cancel()
    try:
        await waiter
    except asyncio.CancelledError:
        pass
    following = asyncio.create_task(runtime.submit(BlockingWork("queued")))
    await asyncio.sleep(.05)
    assert not queued.is_set(), "Cancelled waiter released still-running work's admission"
    # Model admission does not block the rendering lane.
    await renderer.submit(TranscriptRenderTask((TranscriptEvent("assistant", "other text"),)))
    release.set()
    assert await following == {"rows": ["queued"]}
    await asyncio.gather(runtime.aclose(), renderer.aclose())
    assert backend.closes == 1 and not runtime._pending and not runtime._thread_tasks
    print("shared work: polymorphic policies, cross-consumer reuse, safe copies, revision/eviction, independent lanes, cancellation and one shutdown OK")


if __name__ == "__main__":
    asyncio.run(main())
