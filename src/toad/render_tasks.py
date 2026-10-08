"""Typed, data-only renderer operations shared by local and persistent workers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from textual.document._document import DocumentBase
from textual.document._wrapped_document import WrappedDocument

from toad.render_backend import ReusableRenderTask

from toad.markdown_preparation import PreparedMarkdown, PreparedMarkdownPart, prepare_tokens
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
class MarkdownRenderTask(ReusableRenderTask[PreparedMarkdown]):
    """Acquire syntax once, then highlight before independent delivery."""

    source: str | PreparedMarkdownPart
    ansi: bool
    dark: bool

    async def preparation_identity(self, work: RenderPreparation, runtime: PreparationRuntime) -> WorkKey:
        if isinstance(self.source, PreparedMarkdownPart):
            from toad.work_preparation import WorkKey

            # Acquired syntax owns its revision; accounting and delivery copies
            # cannot change the original preparation identity.
            return WorkKey(type(work), (type(self), self.source.revision, self.ansi, self.dark), work.scope)
        return await super().preparation_identity(work, runtime)

    def execute(self) -> PreparedMarkdown:
        part = (PreparedMarkdownPart.capture(self.source)
                if isinstance(self.source, str) else self.source)
        return prepare_tokens(part.acquire_tokens(), self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedMarkdown:
        if not isinstance(result, PreparedMarkdown):
            raise TypeError("Markdown renderer returned an invalid result")
        return result


@dataclass(frozen=True)
class MarkdownPartsTask(ReusableRenderTask[tuple[PreparedMarkdownPart, ...]]):
    """Partition one original message with the shared Markdown block budget."""

    source: str | PreparedMarkdownPart

    async def preparation_identity(self, work: RenderPreparation, runtime: PreparationRuntime) -> WorkKey:
        if isinstance(self.source, PreparedMarkdownPart):
            from toad.work_preparation import WorkKey

            return WorkKey(type(work), (type(self), self.source.revision), work.scope)
        return await super().preparation_identity(work, runtime)

    def execute(self) -> tuple[PreparedMarkdownPart, ...]:
        from toad.widgets.transcript_fragments import RenderBudget

        part = (PreparedMarkdownPart.capture(self.source)
                if isinstance(self.source, str) else self.source)
        parts = tuple(RenderBudget().split(part))
        for part in parts:
            part.retained_bytes
        return parts

    def accept_result(self, result: object) -> tuple[PreparedMarkdownPart, ...]:
        if not isinstance(result, tuple) or not all(isinstance(part, PreparedMarkdownPart) for part in result):
            raise TypeError("Markdown renderer returned invalid source parts")
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
