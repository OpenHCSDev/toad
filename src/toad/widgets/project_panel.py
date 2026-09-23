from __future__ import annotations

import asyncio
from pathlib import Path

from rich.syntax import ClassNotFound, Syntax
from textual import events, work
from textual.reactive import reactive
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Markdown, Static

from toad.widgets.project_directory_tree import ProjectDirectoryTree


class ProjectSearchButton(Static, can_focus=True):
    DEFAULT_CSS = """
    ProjectSearchButton {
        height: 1;
        color: $text-muted;
        pointer: pointer;
    }
    ProjectSearchButton:hover,
    ProjectSearchButton:focus {
        color: $text;
        background: $surface-lighten-2;
        text-style: bold;
    }
    """
    BINDINGS = [Binding("enter", "search", "Search files", show=False)]

    class Requested(Message):
        pass

    def __init__(self) -> None:
        super().__init__("⌕ Search files")

    def action_search(self) -> None:
        self.post_message(self.Requested())

    def on_click(self, event: events.Click) -> None:
        if event.button == 1:
            event.stop()
            self.action_search()


class ProjectPanel(Vertical):
    path = reactive(Path, init=False)
    DEFAULT_CSS = """
    ProjectPanel {
        height: 1fr;
    }
    ProjectPanel ProjectDirectoryTree {
        height: 1fr;
    }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.directory_tree: ProjectDirectoryTree | None = None
        self.path = path
        self._tree_requested = False

    def compose(self) -> ComposeResult:
        yield ProjectSearchButton()

    def on_show(self) -> None:
        self.call_after_refresh(self._ensure_tree)

    def _ensure_tree(self) -> None:
        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        if self.query_ancestor(SideBar).collapsed or self.query_ancestor(SideBarCollapsible).collapsed:
            return
        if self.is_on_screen and not self._tree_requested:
            self._tree_requested = True
            self._mount_tree()

    @work(group="project-tree")
    async def _mount_tree(self) -> None:
        self.directory_tree = ProjectDirectoryTree(self.path, id="project_directory_tree")
        await self.mount(self.directory_tree)

    def watch_path(self, path: Path) -> None:
        if self.directory_tree is not None:
            self.directory_tree.path = path

    def invalidate(self) -> None:
        if self.directory_tree is not None:
            self.directory_tree.invalidate()

    def refresh_if_visible(self) -> None:
        if self.directory_tree is not None:
            self.directory_tree.refresh_if_visible()


class FilePreview(VerticalScroll):
    """Bounded, read-only preview for one project file."""

    DEFAULT_CSS = """
    FilePreview {
        height: 1fr;
        padding: 0 1;
    }
    FilePreview > Static {
        width: auto;
        height: auto;
    }
    FilePreview > .file-preview-path {
        width: 1fr;
        color: $text-muted;
        border-bottom: solid $panel;
        margin-bottom: 1;
    }
    FilePreview > Markdown {
        width: 1fr;
        height: auto;
    }
    """
    MAX_BYTES = 1024 * 1024
    OVERSIZED_PREVIEW_BYTES = 64 * 1024

    @staticmethod
    def _read_prefix(path: Path, limit: int) -> bytes:
        """Bound the read even for unexpectedly large project files."""
        with path.open("rb") as source:
            return source.read(limit)

    def __init__(self, path: Path, *, id: str) -> None:
        super().__init__(id=id)
        self.path = path

    async def on_mount(self) -> None:
        await self.mount(Static(str(self.path), classes="file-preview-path"))
        try:
            data = await asyncio.to_thread(self._read_prefix, self.path, self.MAX_BYTES + 1)
        except OSError as error:
            await self.mount(Static(f"Unable to open {self.path}: {error}"))
            return
        if len(data) > self.MAX_BYTES:
            data = data[:self.OVERSIZED_PREVIEW_BYTES]
            await self.mount(
                Static(f"{self.path.name} exceeds 1 MiB; showing only the first 64 KiB.")
            )
        if b"\0" in data:
            await self.mount(Static(f"{self.path.name} is a binary file."))
            return
        text = data.decode("utf-8", errors="replace")
        if self.path.suffix.lower() in {".md", ".markdown", ".mdown"}:
            await self.mount(Markdown(text))
            return
        try:
            lexer = Syntax.guess_lexer(str(self.path), text)
        except ClassNotFound:
            lexer = "text"
        await self.mount(
            Static(
                Syntax(
                    text,
                    lexer,
                    line_numbers=True,
                    word_wrap=False,
                    background_color="default",
                )
            )
        )
