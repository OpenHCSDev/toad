from dataclasses import dataclass
from sys import getsizeof
from typing import ClassVar

import pytest

from toad.render_backend import Renderer, RenderTask, ReusableRenderTask
from toad.work_preparation import PreparationRuntime, RenderPreparation


@dataclass(frozen=True)
class CacheProbeRenderTask(ReusableRenderTask[int]):
    value: int
    calls: ClassVar[int] = 0

    def execute(self) -> int:
        type(self).calls += 1
        return self.value

    def result_size(self, result: int) -> int:
        return getsizeof(result)


@dataclass(frozen=True)
class IngressProbeRenderTask(RenderTask[int]):
    value: int
    calls: ClassVar[int] = 0

    def execute(self) -> int:
        type(self).calls += 1
        return self.value


class InlineRenderer(Renderer):
    async def capture(self, task):
        return task.capture_result()

    async def aclose(self):
        await self._close_submissions()


@pytest.mark.asyncio
async def test_task_owns_the_representation_cost_and_reuse():
    CacheProbeRenderTask.calls = IngressProbeRenderTask.calls = 0
    runtime = PreparationRuntime(InlineRenderer())
    cached = CacheProbeRenderTask(7)
    work = RenderPreparation(cached)
    try:
        assert await runtime.submit(work) == 7
        assert await runtime.submit(work) == 7
        assert CacheProbeRenderTask.calls == 1
        key, (prepared, size) = next(iter(runtime._ready.items()))
        assert size == prepared.size + getsizeof(key) + key.revision.size
        assert cached.finish_prepared(key, prepared) == (prepared, size, cached)
        ingress = RenderPreparation(IngressProbeRenderTask(9))
        assert await runtime.submit(ingress) == 9
        assert await runtime.submit(ingress) == 9
        assert IngressProbeRenderTask.calls == 2
        assert len(runtime._ready) == 1
    finally:
        await runtime.aclose()
