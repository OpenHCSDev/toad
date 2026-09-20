from __future__ import annotations

import asyncio
from pathlib import Path

from rich.syntax import ClassNotFound, Syntax
from textual import events
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
        self.path = path

    def compose(self) -> ComposeResult:
        yield ProjectSearchButton()
        yield ProjectDirectoryTree(self.path, id="project_directory_tree")


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
    FilePreview > Markdown {
        width: 1fr;
        height: auto;
    }
    """
    MAX_BYTES = 1024 * 1024

    def __init__(self, path: Path, *, id: str) -> None:
        super().__init__(id=id)
        self.path = path

    async def on_mount(self) -> None:
        try:
            data = await asyncio.to_thread(self.path.read_bytes)
        except OSError as error:
            await self.mount(Static(f"Unable to open {self.path}: {error}"))
            return
        if len(data) > self.MAX_BYTES:
            await self.mount(
                Static(f"{self.path.name} is larger than the 1 MiB preview limit.")
            )
            return
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
