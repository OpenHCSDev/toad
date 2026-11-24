"""Textual's file previews: one viewer per file kind it shows.

`toad.file_kind` declares what a path is; this family decides how Textual previews it.
A viewer declares the kinds it shows (`shows=(ImageFileKind,)`), and `for_kind` walks the
kind's MRO, so a PNG resolves to the image viewer and an unknown kind to the code viewer
with no type test at the caller. Only Textual imports this module, so the preview
libraries it reaches (textual_image, PIL) never load on a frontend that has no preview.
"""
from __future__ import annotations

from typing import ClassVar

from formbridge.forms.declared_fields import DeclaredViews
from textual.widgets import Static

from toad.file_kind import FileKind, ImageFileKind, MarkdownFileKind
from toad.widgets.line_markdown import LineMarkdown
from toad.widgets.process_text_area import ProcessTextArea


class FileViewer(DeclaredViews):
    """How Textual loads and shows one kind of file in a preview view."""

    MAX_BYTES: ClassVar[int] = 1024 * 1024
    OVERSIZED_PREVIEW_BYTES: ClassVar[int] = 64 * 1024

    @classmethod
    def for_kind(cls, kind: type[FileKind]) -> type[FileViewer]:
        return cls.showing(kind.__mro__)

    @classmethod
    def load(cls, path):
        with path.open("rb") as source:
            return source.read(cls.MAX_BYTES + 1)

    @classmethod
    async def text(cls, view, data):
        if b"\0" in data:
            raise ValueError(f"{view.path.name} is a binary file.")
        if len(data) > cls.MAX_BYTES:
            data = data[:cls.OVERSIZED_PREVIEW_BYTES]
            await view.body.mount(Static("File exceeds 1 MiB; showing only the first 64 KiB."))
        return data.decode("utf-8", errors="replace")


class CodeViewer(FileViewer, shows=(FileKind,)):
    """Any file Textual has no richer view for: highlighted source."""

    @classmethod
    async def show(cls, view, data):
        from toad.widgets.worker_static import WorkerStatic
        content = WorkerStatic.code(await cls.text(view, data), filename=str(view.path))
        await view.body.mount(content)
        await content.wait_ready()

    @classmethod
    async def show_at(cls, view, data, position):
        content = ProcessTextArea(soft_wrap=False, show_line_numbers=True)
        content.styles.height = "1fr"
        await view.body.mount(content)
        await content.load_text_prepared(await cls.text(view, data)).wait()
        position.reveal(content)


class MarkdownViewer(CodeViewer, shows=(MarkdownFileKind,)):
    """Markdown renders; a reveal at a position still opens the source."""

    @classmethod
    async def show(cls, view, data):
        await view.body.mount(LineMarkdown(await cls.text(view, data)))


class ImageViewer(FileViewer, shows=(ImageFileKind,)):
    """An image, drawn through the terminal's graphics protocol."""

    @staticmethod
    def prepare_terminal():
        # The library owns detection; its queries must precede Textual's driver.
        import textual_image.widget  # noqa: F401

    @classmethod
    def load(cls, path):
        from PIL import Image as PillowImage
        with PillowImage.open(path) as image:
            image.thumbnail((1600, 1600))
            return image.copy()

    @classmethod
    async def show(cls, view, image, position=None):
        from textual_image.widget import Image
        content = Image(image)
        content.styles.width = "auto"
        content.styles.height = "auto"
        await view.body.mount(content)

    # Images have no source cursor: both declared entry points use this behavior.
    show_at = show
