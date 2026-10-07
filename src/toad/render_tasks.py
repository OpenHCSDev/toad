"""Typed, data-only renderer operations shared by local and persistent workers."""

from __future__ import annotations

from dataclasses import dataclass
from textual.document._document import DocumentBase
from textual.document._wrapped_document import WrappedDocument
from textual.widgets import PreparedTextArea

from toad.render_backend import ReusableRenderTask

from toad.markdown_preparation import PreparedMarkdown, prepare_tokens
from toad.widgets.patch_diff import PreparedPatch, prepare_patch
from toad.rich_preparation import (
    PreparedRichContent,
    RichPresentation,
    RichSource,
    prepare_rich,
)


@dataclass(frozen=True)
class ReadOnlyDocumentRenderTask(ReusableRenderTask[WrappedDocument]):
    """The native document owns splitting, tab expansion and wrap coordinates."""
    source: str | DocumentBase
    width: int
    tab_width: int

    def execute(self) -> WrappedDocument:
        return PreparedTextArea.prepare_document(self.source, self.width, self.tab_width)

    def accept_result(self, result: object) -> WrappedDocument:
        if not isinstance(result, WrappedDocument):
            raise TypeError("Document renderer returned an invalid native view")
        return result


@dataclass(frozen=True)
class PatchRenderTask(ReusableRenderTask[PreparedPatch]):
    source: str
    ansi: bool
    dark: bool

    def execute(self) -> PreparedPatch:
        return prepare_patch(self.source, self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedPatch:
        if not isinstance(result, PreparedPatch):
            raise TypeError("Patch renderer returned an invalid result")
        return result


@dataclass(frozen=True)
class MarkdownRenderTask(ReusableRenderTask[PreparedMarkdown]):
    """Parse and highlight one detached body before its independent delivery."""

    source: str
    ansi: bool
    dark: bool

    def execute(self) -> PreparedMarkdown:
        from toad.conversation_markdown import parse_markdown_syntax

        return prepare_tokens(parse_markdown_syntax(self.source), self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedMarkdown:
        if not isinstance(result, PreparedMarkdown):
            raise TypeError("Markdown renderer returned an invalid result")
        return result


@dataclass(frozen=True)
class RichRenderTask(ReusableRenderTask[PreparedRichContent]):
    source: RichSource
    presentation: RichPresentation

    def execute(self) -> PreparedRichContent:
        return prepare_rich(self.source, self.presentation)

    def accept_result(self, result: object) -> PreparedRichContent:
        if not isinstance(result, PreparedRichContent):
            raise TypeError("Rich renderer returned an invalid result")
        return result
