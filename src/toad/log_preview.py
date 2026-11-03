"""Captured log availability owns its controls and preview instruction."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.widgets import Button

from toad.project_link import AcpLogLink


class LogPreviewTarget(ABC):
    @abstractmethod
    async def open_log_path(self, path: Path) -> None: ...


class LogPreview(ABC):
    def controls(self) -> ComposeResult:
        return ()

    async def open(self, target: LogPreviewTarget) -> None:
        """A source without a log has no preview to request."""


class NoLogPreview(LogPreview):
    """No process log was available when the details were captured."""


@dataclass(frozen=True)
class FileLogPreview(LogPreview):
    path: Path

    def controls(self) -> ComposeResult:
        return (Button(AcpLogLink.label, id="delivery-log"),)

    async def open(self, target: LogPreviewTarget) -> None:
        await target.open_log_path(self.path)
