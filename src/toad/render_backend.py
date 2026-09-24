"""Nominal lifecycle contract for application-owned renderer clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from importlib.util import find_spec
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from toad.render_tasks import RenderTask

ResultT = TypeVar("ResultT")


class Renderer(ABC):
    @abstractmethod
    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        """Prepare one typed result, retaining admission until execution finishes."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close this client's owned work and transport resources."""


class RendererBackend(str, Enum):
    LOCAL = "local"
    PERSISTENT = "persistent"


def create_renderer(backend: RendererBackend = RendererBackend.LOCAL, *, directory: Path | None = None) -> Renderer:
    """Construct the selected client before terminal capture; CPU work stays lazy."""
    if backend is RendererBackend.LOCAL:
        from toad.render_processes import RenderProcessPool

        RenderProcessPool.prepare_spawn()
        return RenderProcessPool()
    if backend is not RendererBackend.PERSISTENT:
        raise ValueError(f"Unsupported renderer backend: {backend!r}")
    if os.name != "posix":
        raise RuntimeError("The persistent renderer currently requires POSIX IPC")
    if find_spec("zmqruntime") is None:
        raise RuntimeError("Install batrachian-toad[persistent-renderer] to use the persistent renderer")
    from toad.render_runtime import PersistentRenderer
    if directory is None:
        from platformdirs import user_runtime_path

        directory = user_runtime_path("toad-renderer")
    return PersistentRenderer(directory)
