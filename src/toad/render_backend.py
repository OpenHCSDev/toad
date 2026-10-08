"""Nominal lifecycle contract for application-owned renderer clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable
import asyncio
from contextvars import Context, copy_context
import os
from typing import TypeVar, Generic, TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily

ResultT = TypeVar("ResultT", covariant=True)

if TYPE_CHECKING:
    from toad.work_preparation import PreparationRuntime, RenderPreparation, WorkKey, PreparationWork, PreparedValue

class RenderExecution(ABC, Generic[ResultT]):
    async def complete(self, execution: Awaitable[object]) -> ResultT:
        """Accept the actual completed worker result through this task's contract."""
        return self.accept_result(await execution)

    @abstractmethod
    def execute(self) -> ResultT:
        """Execute pure preparation in the renderer process."""

    @abstractmethod
    def accept_result(self, result: object) -> ResultT:
        """Validate the result at a transport boundary."""


class RenderTask(RenderExecution[ResultT], DeclaredFamily, affix="RenderTask"):
    """A nominal operation with an exact input and result contract."""

    def capture_result(self) -> PreparedValue[ResultT]:
        """Validate and store the result in the worker which produced it.

        The existing task storage declaration selects the representation carried
        by both renderer transports and retained by preparation. No intermediate
        consumer graph is needed merely to encode that same result again.
        """
        from toad.work_preparation import RenderPreparation

        return RenderPreparation(self).store_result(self.accept_result(self.execute()))

    async def complete_capture(self, execution: Awaitable[object]) -> PreparedValue[ResultT]:
        from toad.work_preparation import PreparedValue

        return PreparedValue.accept(await execution)

    async def preparation_identity(self, work: RenderPreparation, runtime: PreparationRuntime) -> WorkKey:
        """External state requires independent work for each submission."""
        from toad.work_preparation import WorkKey

        return WorkKey(type(work), object(), work.scope)

    @property
    def preparation_storage(self) -> type[PreparationWork]:
        from toad.work_preparation import PreparationWork

        return PreparationWork

class ReusableRenderTask(RenderTask[ResultT]):
    async def preparation_identity(self, work: RenderPreparation, runtime: PreparationRuntime) -> WorkKey:
        from dataclasses import replace
        from toad.work_preparation import ContentAddressedWork

        return replace(await ContentAddressedWork.identity(work, runtime), scope=work.scope)

    @property
    def preparation_storage(self) -> type[PreparationWork]:
        from toad.work_preparation import SerializedWork

        return SerializedWork


class RendererSpawn(ABC):
    @staticmethod
    def start_workers(executor) -> None:
        """Start the owned pool without occupying admission with a dummy job.

        ProcessPoolExecutor has no public prestart operation. Its original
        launch hook starts the configured workers before the manager thread;
        submission, worker replacement and shutdown remain executor-owned.
        """
        try:
            executor._launch_processes()
            executor._start_executor_manager_thread()
        except BaseException:
            executor.shutdown(wait=True, cancel_futures=True)
            raise

    @staticmethod
    def prepare_spawn() -> None:
        """Initialize POSIX spawn bookkeeping before a UI captures stderr.

        Python 3.14's resource tracker inherits stderr's file descriptor on
        first startup. Textual captures can report -1 instead of raising
        UnsupportedOperation, which is invalid in spawn's pass-fd list. An
        application calls this before entering terminal mode; CPU worker
        creation remains lazy. The tracker is multiprocessing-owned and is
        shared with any other process pools in this interpreter.
        """
        if os.name == "posix":
            from multiprocessing import resource_tracker

            resource_tracker.ensure_running()

class Renderer(RendererSpawn):
    def __init__(self) -> None:
        self._submissions: set[asyncio.Task] = set()

    def start(self) -> None:
        """Begin owned startup; remote clients retain on-demand connection."""
        self.prepare_spawn()

    @staticmethod
    def execution_context() -> Context:
        """Detached work borrows ambient facts, never its waiter's native owner.

        Preparation can outlive an evicted widget. App/backend context remains
        available, but native pump and Worker custody belongs to the consumer,
        not to shared data preparation or its completion callbacks.
        """
        from textual._context import active_message_pump
        from textual.worker import active_worker

        context = Context()
        for variable, value in copy_context().items():
            if variable is not active_message_pump and variable is not active_worker:
                context.run(variable.set, value)
        return context

    @staticmethod
    async def wait_for_work(pending: asyncio.Future) -> None:
        """A cancelled consumer releases its wait, not admitted execution.

        Python 3.14 wait removes its callback on cancellation but leaves the
        awaited-by edge on a pending job. Close that original edge at the same
        boundary; otherwise shared work retains completed native consumers.
        """
        waiter = asyncio.current_task()
        try:
            await asyncio.wait((pending,))
        finally:
            asyncio.future_discard_from_awaited_by(pending, waiter)

    def _submission_finished(self, task: asyncio.Task) -> None:
        self._submissions.discard(task)
        if not task.cancelled():
            task.exception()

    async def prepare(self, task: RenderTask[ResultT]) -> None:
        """Warm a task; retained clients need no consumer delivery copy.

        A renderer without retained resources still owns execution and result
        validation through capture. PreparedRenderer supplies the bounded
        preparation lifetime while foreground consumers continue to submit.
        """
        await self.capture(task)

    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        """Deliver one independent result from the worker's captured value."""
        context = self.execution_context()
        running = asyncio.create_task(self._submit(task), name="renderer-delivery", context=context)
        self._submissions.add(running)
        running.add_done_callback(self._submission_finished, context=context)
        try:
            await self.wait_for_work(running)
            return running.result()
        except asyncio.CancelledError:
            running.cancel()
            raise

    async def _submit(self, task: RenderTask[ResultT]) -> ResultT:
        prepared = await self.capture(task)
        delivery = asyncio.create_task(
            asyncio.to_thread(lambda: task.accept_result(prepared.materialize())),
            name="renderer-materialize",
        )
        try:
            await self.wait_for_work(delivery)
        except asyncio.CancelledError:
            # Cancelling a consumer cannot stop an already-running decoder.
            # Keep this submission owned until its actual delivery worker exits.
            await self.wait_for_work(delivery)
            if not delivery.cancelled():
                delivery.exception()
            raise
        return delivery.result()

    async def _close_submissions(self) -> None:
        if self._submissions:
            await asyncio.gather(*tuple(self._submissions), return_exceptions=True)

    @abstractmethod
    async def capture(self, task: RenderTask[ResultT]) -> PreparedValue[ResultT]:
        """Prepare one typed result, retaining admission until execution finishes."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close this client's owned work and transport resources."""
