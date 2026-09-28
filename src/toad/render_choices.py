"""UI-selected renderer declarations, outside the worker import boundary."""

from __future__ import annotations

from abc import abstractmethod
from importlib.util import find_spec
import os
from pathlib import Path

from agent_comms.declared_family import DeclaredFamily
from toad.setting_choices import Choice
from toad.render_backend import Renderer


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
