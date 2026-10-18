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

from ui_theme.effects import PlayedText
from ui_theme.scheme import ColourScheme
from ui_theme.splash import TextEffect

if TYPE_CHECKING:
    from toad.work_preparation import PreparationRuntime, RenderPreparation, WorkKey


@dataclass(frozen=True)
class ReadOnlyDocumentRenderTask(ReusableRenderTask[WrappedDocument]):
    """The native document owns splitting, tab expansion and wrap coordinates."""
    source: str | DocumentBase
    width: int
    tab_width: int

    def result_size(self, result: WrappedDocument) -> int:
        return 256 + 4 * len(result.document.text) + 64 * result.height

    def execute(self) -> WrappedDocument:
        from textual.widgets import PreparedTextArea

        return PreparedTextArea.prepare_document(self.source, self.width, self.tab_width)

    def accept_result(self, result: object) -> WrappedDocument:
        if not isinstance(result, WrappedDocument):
            raise TypeError("Document renderer returned an invalid native view")
        return result


@dataclass(frozen=True)
class RichRenderTask(ReusableRenderTask[PreparedRichContent]):
    source: RichSource
    presentation: RichPresentation

    def result_size(self, result: PreparedRichContent) -> int:
        return result.retained_bytes

    def execute(self) -> PreparedRichContent:
        return self.source.prepare(self.presentation)

    def accept_result(self, result: object) -> PreparedRichContent:
        if not isinstance(result, PreparedRichContent):
            raise TypeError("Rich renderer returned an invalid result")
        return result


@dataclass(frozen=True)
class TextEffectRenderTask(ReusableRenderTask[PlayedText]):
    """Build a text effect's frames in a worker; building one takes tens to hundreds of ms."""

    effect: TextEffect
    scheme: ColourScheme

    def result_size(self, result: PlayedText) -> int:
        return 256 + sum(64 + sum(64 + 64 * len(line) for line in frame.lines)
                         for frame in result.frames)

    def execute(self) -> PlayedText:
        return self.effect.build(self.scheme)

    def accept_result(self, result: object) -> PlayedText:
        if not isinstance(result, PlayedText):
            raise TypeError("Text effect renderer returned an invalid result")
        return result
