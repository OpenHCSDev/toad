"""Bounded, selectable ACP diagnostics with useful errors visible first."""

import asyncio
import os
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import ItemGrid, Vertical
from textual.widgets import Button, Static, TextArea
from textual.worker import Worker, get_current_worker

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
    AcpLogPreview > .log-path { height: 1; text-wrap: nowrap; text-overflow: ellipsis; color: $text-muted; }
    AcpLogPreview > .log-controls { height: auto; grid-rows: 3; }
    AcpLogPreview Button { min-width: 0; width: 1fr; height: 3; }
    AcpLogPreview > TextArea { height: 1fr; border: none; }
    AcpLogPreview > .log-status { height: 1; text-wrap: nowrap; text-overflow: ellipsis; color: $text-muted; }
    """

    def __init__(self, path: Path, *, id: str) -> None:
        super().__init__(id=id)
        self.path = path
        self.page: LogPage | None = None
        self.view: LogView = ErrorsLogView()
        self._ready = asyncio.Event()
        self._read_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        path = Static(str(self.path), classes="log-path", markup=False)
        path.tooltip = str(self.path)
        yield path
        with ItemGrid(classes="log-controls", min_column_width=12, regular=True):
            for kind in LogView.members_with(LogView):
                yield Button(kind.label(), id=f"log-{kind.declared_name}", classes="log-view")
            yield Button("Wrap: on", id="log-wrap")
            yield Button("Earlier", id="log-earlier")
            yield Button("Latest ↻", id="log-latest")
        yield TextArea(
            "Loading log…",
            read_only=True,
            soft_wrap=True,
            id="log-text",
            tooltip="Select text to copy. Wrap off: Home/End, arrows or horizontal scrollbar.",
        )
        yield Static("", classes="log-status", markup=False)

    def on_mount(self) -> None:
        self.load_page()
        self.query_one(TextArea).focus()

    def on_unmount(self) -> None:
        self._ready.set()

    async def wait_ready(self) -> None:
        await self._ready.wait()

    def load_page(self, before: int | None = None) -> None:
        self._ready.clear()
        self.query_one(".log-status", Static).update("Reading log…")
        self._read_worker = self._read_page(before)

    @work(group="acp-log-read", exclusive=True)
    async def _read_page(self, before: int | None = None) -> None:
        try:
            self.page = await asyncio.to_thread(LogPage.read, self.path, FilePreview.MAX_BYTES, before)
            if self.is_attached:
                self.show_page()
        except OSError as error:
            if self.is_attached:
                self.page = None
                self.query_one(TextArea).load_text(f"Unable to read log: {error}")
                self.query_one(".log-status", Static).update("Log read failed. Select Latest to try reading again.")
                self.query_one("#log-earlier", Button).disabled = True
        finally:
            if get_current_worker() is self._read_worker:
                self._ready.set()

    def show_page(self) -> None:
        if self.page is None:
            return
        self.query_one(TextArea).load_text(self.view.render(self.page))
        self.query_one(".log-status", Static).update(
            f"{self.view.label()} · bytes {self.page.start:,}–{self.page.end:,} of {self.page.total:,} · "
            "Select text to copy. Wrap off: Home/End, arrows or horizontal scrollbar."
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
