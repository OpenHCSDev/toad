"""Bounded, selectable ACP diagnostics with useful errors visible first."""

import asyncio
import os
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static, TextArea

from toad import paths
from toad.acp.log_records import ErrorsLogView, LogPage, LogView
from toad.widgets.project_panel import FilePreview


def file_preview(path: Path) -> FilePreview | "AcpLogPreview":
    selected = os.environ.get("TOAD_LOG")
    if path.parent == paths.get_log() or (selected and path == Path(selected).resolve()):
        return AcpLogPreview(path, id="file-preview")
    return FilePreview(path, id="file-preview")


class AcpLogPreview(Vertical):
    DEFAULT_CSS = """
    AcpLogPreview { height: 1fr; }
    AcpLogPreview > .log-path { height: auto; color: $text-muted; }
    AcpLogPreview > .log-controls { height: 3; }
    AcpLogPreview Button { min-width: 8; width: auto; }
    AcpLogPreview > TextArea { height: 1fr; border: none; }
    AcpLogPreview > .log-status { height: auto; color: $text-muted; }
    """

    def __init__(self, path: Path, *, id: str) -> None:
        super().__init__(id=id)
        self.path = path
        self.page: LogPage | None = None
        self.view: LogView = ErrorsLogView()
        self._ready = asyncio.Event()

    def compose(self) -> ComposeResult:
        yield Static(str(self.path), classes="log-path", markup=False)
        with Horizontal(classes="log-controls"):
            for kind in LogView.members_with(LogView):
                yield Button(kind.label(), id=f"log-{kind.declared_name}", classes="log-view")
            yield Button("Wrap: on", id="log-wrap")
            yield Button("Earlier", id="log-earlier")
            yield Button("Latest ↻", id="log-latest")
        yield TextArea("Loading log…", read_only=True, soft_wrap=True, id="log-text")
        yield Static("", classes="log-status", markup=False)

    def on_mount(self) -> None:
        self.load_page()
        self.query_one(TextArea).focus()

    async def wait_ready(self) -> None:
        await self._ready.wait()

    @work(group="acp-log-read", exclusive=True)
    async def load_page(self, before: int | None = None) -> None:
        self._ready.clear()
        try:
            self.page = await asyncio.to_thread(LogPage.read, self.path, FilePreview.MAX_BYTES, before)
            self.show_page()
        except OSError as error:
            self.query_one(TextArea).load_text(f"Unable to read log: {error}")
        finally:
            self._ready.set()

    def show_page(self) -> None:
        if self.page is None:
            return
        self.query_one(TextArea).load_text(self.view.render(self.page.records))
        self.query_one(".log-status", Static).update(
            f"{self.view.label()} · bytes {self.page.start:,}–{self.page.end:,} of {self.page.total:,} · "
            "Select text to copy. Wrap off: Left/Right or horizontal scrollbar."
        )
        self.query_one("#log-earlier", Button).disabled = self.page.start == 0
        for button in self.query(".log-view").results(Button):
            button.variant = "primary" if button.id == f"log-{self.view.declared_name}" else "default"

    @on(Button.Pressed, ".log-view")
    def select_view(self, event: Button.Pressed) -> None:
        event.stop()
        self.view = LogView.decode(event.button.id.removeprefix("log-"))()
        self.show_page()
        self.query_one(TextArea).focus()

    @on(Button.Pressed, "#log-wrap")
    def toggle_wrap(self, event: Button.Pressed) -> None:
        event.stop()
        text = self.query_one(TextArea)
        text.soft_wrap = not text.soft_wrap
        event.button.label = "Wrap: on" if text.soft_wrap else "Wrap: off"
        text.focus()

    @on(Button.Pressed, "#log-earlier")
    def earlier(self, event: Button.Pressed) -> None:
        event.stop()
        if self.page is not None:
            self.load_page(self.page.start)

    @on(Button.Pressed, "#log-latest")
    def latest(self, event: Button.Pressed) -> None:
        event.stop()
        self.load_page()
