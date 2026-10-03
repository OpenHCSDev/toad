"""Nominal lifecycle contract for application-owned renderer clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
import os
from pathlib import Path
from typing import TypeVar, Generic

from agent_comms.declared_family import DeclaredFamily

ResultT = TypeVar("ResultT", covariant=True)

class RenderExecution(ABC, Generic[ResultT]):
    @abstractmethod
    def execute(self) -> ResultT:
        """Execute pure preparation in the renderer process."""

    @abstractmethod
    def accept_result(self, result: object) -> ResultT:
        """Validate the result at a transport boundary."""


class RenderTask(RenderExecution[ResultT], DeclaredFamily, affix="RenderTask"):
    """A nominal operation with an exact input and result contract."""

    def reusable_inputs(self) -> object | None:
        """None means external state prevents sharing or retaining this capture."""
        return None

class ReusableRenderTask(RenderTask[ResultT]):
    def reusable_inputs(self) -> object:
        return self


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
    async def warm_up(self, *, project: Path, ansi: bool, dark: bool) -> None:
        """Optional off-loop preparation after the application presents its UI."""

    @abstractmethod
    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        """Prepare one typed result, retaining admission until execution finishes."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close this client's owned work and transport resources."""
