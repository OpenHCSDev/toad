"""Typed, data-only renderer operations shared by local and persistent workers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from textual.document._document import DocumentBase
from textual.document._wrapped_document import WrappedDocument
from textual.selection import Selection
from textual.style import Style

from toad.render_backend import ReusableRenderTask

from toad.rich_preparation import (
    PreparedRichContent,
    RichPresentation,
    RichSource,
)

if TYPE_CHECKING:
    from toad.widgets.patch_diff import PreparedPatch
    from toad.work_preparation import PreparationRuntime, RenderPreparation, WorkKey


@dataclass(frozen=True)
class ReadOnlyDocumentRenderTask(ReusableRenderTask[WrappedDocument]):
    """The native document owns splitting, tab expansion and wrap coordinates."""
    source: str | DocumentBase
    width: int
    tab_width: int

    def execute(self) -> WrappedDocument:
        from textual.widgets import PreparedTextArea

        return PreparedTextArea.prepare_document(self.source, self.width, self.tab_width)

    def accept_result(self, result: object) -> WrappedDocument:
        if not isinstance(result, WrappedDocument):
            raise TypeError("Document renderer returned an invalid native view")
        return result


@dataclass(frozen=True)
class PatchRenderTask(ReusableRenderTask["PreparedPatch"]):
    source: str
    ansi: bool
    dark: bool

    def execute(self) -> PreparedPatch:
        from toad.widgets.patch_diff import prepare_patch

        return prepare_patch(self.source, self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedPatch:
        from toad.widgets.patch_diff import PreparedPatch

        if not isinstance(result, PreparedPatch):
            raise TypeError("Patch renderer returned an invalid result")
        return result


@dataclass(frozen=True)
class RichRenderTask(ReusableRenderTask[PreparedRichContent]):
    source: RichSource
    presentation: RichPresentation

    def execute(self) -> PreparedRichContent:
        return self.source.prepare(self.presentation)

    def accept_result(self, result: object) -> PreparedRichContent:
        if not isinstance(result, PreparedRichContent):
            raise TypeError("Rich renderer returned an invalid result")
        return result
