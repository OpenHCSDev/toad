"""Nominal lifecycle contract for application-owned renderer clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable
import os
from pathlib import Path
from typing import TypeVar, Generic, TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily

ResultT = TypeVar("ResultT", covariant=True)

if TYPE_CHECKING:
    from toad.work_preparation import PreparationRuntime, RenderPreparation, WorkKey, PreparationWork

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
    async def prepare(self, task: RenderTask[ResultT]) -> None:
        """Warm a task; retained clients need no consumer delivery copy.

        A renderer without retained resources still owns execution and result
        validation through submit. PreparedRenderer supplies the bounded
        preparation lifetime while foreground consumers continue to submit.
        """
        await self.submit(task)

    async def warm_up(self, *, project: Path, ansi: bool, dark: bool) -> None:
        """Optional off-loop preparation after the application presents its UI."""

    @abstractmethod
    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        """Prepare one typed result, retaining admission until execution finishes."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close this client's owned work and transport resources."""
