"""The forked renderer: its workers are other processes that share this one's loaded modules,
a failing task says so, a lost worker is replaced, and shutdown leaves none behind. No app,
widgets or agents."""

import asyncio
import os
import signal
import sys
from dataclasses import dataclass

import pytest

from toad.render_backend import RenderTask
from toad.render_fork import ForkedRenderer, RenderChildLost
from toad.work_preparation import PreparationRuntime, RenderPreparation

LOADED_BEFORE_FORK = object()
"""Module state only this interpreter has: a fresh interpreter importing this file would hold
a different object, so a worker that answers with the same identity was forked, not started."""


@dataclass(frozen=True)
class WhereRenderTask(RenderTask[tuple[int, ...]]):
    """Where the task ran: the worker's pid, and the identity of this module's marker there."""

    def execute(self) -> tuple[int, ...]:
        return os.getpid(), id(sys.modules[__name__].LOADED_BEFORE_FORK)


@dataclass(frozen=True)
class FailingRenderTask(RenderTask[tuple[int, ...]]):
    def execute(self) -> tuple[int, ...]:
        raise ValueError("no such row")


@dataclass(frozen=True)
class DyingRenderTask(RenderTask[tuple[int, ...]]):
    """The worker is killed mid-task, as Android kills a process."""

    def execute(self) -> tuple[int, ...]:
        os.kill(os.getpid(), signal.SIGKILL)
        return ()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def test_workers_are_forks_of_this_process_with_its_modules_loaded():
    renderer = ForkedRenderer(children=2)
    renderer.start()
    runtime = PreparationRuntime(renderer)
    started = {child.pid for child in renderer._started}
    try:
        answers = await asyncio.gather(*(runtime.submit(RenderPreparation(WhereRenderTask())) for _ in range(8)))
    finally:
        await runtime.aclose()
    workers = {pid for pid, _marker in answers}
    assert len(started) == 2 and os.getpid() not in started
    assert workers <= started
    # The same object identity: the worker never imported this module, it was born holding it.
    assert {marker for _pid, marker in answers} == {id(LOADED_BEFORE_FORK)}


async def test_a_failing_task_reports_its_failure_and_the_worker_serves_the_next():
    renderer = ForkedRenderer(children=1)
    renderer.start()
    runtime = PreparationRuntime(renderer)
    try:
        with pytest.raises(RuntimeError, match="ValueError: no such row"):
            await runtime.submit(RenderPreparation(FailingRenderTask()))
        pid, _marker = await runtime.submit(RenderPreparation(WhereRenderTask()))
        assert pid == renderer._started[0].pid
    finally:
        await runtime.aclose()


async def test_a_lost_worker_fails_its_task_and_is_replaced():
    renderer = ForkedRenderer(children=1)
    renderer.start()
    runtime = PreparationRuntime(renderer)
    lost = renderer._started[0].pid
    try:
        with pytest.raises(RenderChildLost):
            await runtime.submit(RenderPreparation(DyingRenderTask()))
        pid, _marker = await runtime.submit(RenderPreparation(WhereRenderTask()))
        assert pid != lost and pid != os.getpid()
    finally:
        await runtime.aclose()


async def test_closing_reaps_every_worker():
    renderer = ForkedRenderer(children=2)
    renderer.start()
    workers = [child.pid for child in renderer._started]
    assert all(alive(pid) for pid in workers)
    await renderer.aclose()
    assert not any(alive(pid) for pid in workers)
    assert renderer.closed
