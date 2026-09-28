"""Nominal lifecycle contract for application-owned renderer clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from agent_comms.declared_family import DeclaredFamily
from toad.setting_choices import Choice
from importlib.util import find_spec
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from toad.render_tasks import RenderTask

ResultT = TypeVar("ResultT")


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


class RendererChoice(Choice, DeclaredFamily, affix="Renderer"):
    @classmethod
    @abstractmethod
    def start(cls, *, directory: Path | None = None) -> Renderer: ...


class LocalRenderer(RendererChoice):
    @classmethod
    def start(cls, *, directory: Path | None = None) -> Renderer:
        from toad.render_processes import RenderProcessPool

        return RenderProcessPool()


class PersistentRenderer(RendererChoice):
    @classmethod
    def start(cls, *, directory: Path | None = None) -> Renderer:
        if os.name != "posix":
            raise RuntimeError("The persistent renderer currently requires POSIX IPC")
        if find_spec("zmqruntime") is None:
            raise RuntimeError("Install batrachian-toad[persistent-renderer] to use the persistent renderer")
        from toad.render_runtime import PersistentRenderClient

        if directory is None:
            from platformdirs import user_runtime_path

            directory = user_runtime_path("toad-renderer")
        return PersistentRenderClient(directory)
