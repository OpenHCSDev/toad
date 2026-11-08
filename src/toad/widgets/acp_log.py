"""Bounded, selectable ACP diagnostics with useful errors visible first, following the log as it is written."""

import asyncio
from collections.abc import Callable
from functools import partial
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import ItemGrid, Vertical
from textual.widgets import Static, TextArea
from textual.worker import Worker, get_current_worker

from toad.widgets.acting_button import ActingButton
from toad.acp.log_records import ErrorsLogView, LogPage, LogView
from toad.file_kind import FileKind
from toad.native_style import (
    AutoHeight,
    Borderless,
    EllipsisOverflow,
    FillWidth,
    MutedText,
    NoWrap,
    OneRow,
)
from textual.events import Mount
from textual import on
from textual.events import Unmount


class LogLine(MutedText, OneRow, NoWrap, EllipsisOverflow, Static):
    """One muted, single-row line above or below the log."""




class LogStatus(LogLine):
    """What the shown page holds, or why it could not be read."""


class LogControls(AutoHeight, ItemGrid):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.grid_rows = "3"


class LogButton(FillWidth, ActingButton):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.min_width = 0


class LogViewButton(LogButton):
    """Shows the log through its view kind."""

    def __init__(self, kind: type[LogView]) -> None:
        super().__init__(kind.label())
        self.kind = kind

    async def act(self) -> None:
        self.query_ancestor(AcpLogPreview).select_view(self.kind)


class LogWrapButton(LogButton):
    """Switches soft wrap."""

    async def act(self) -> None:
        self.query_ancestor(AcpLogPreview).toggle_wrap(self)


class LogEarlierButton(LogButton):
    """Reads the page before the shown one."""

    async def act(self) -> None:
        self.query_ancestor(AcpLogPreview).earlier()


class LogLatestButton(LogButton):
    """Reads the newest page again."""

    async def act(self) -> None:
        self.query_ancestor(AcpLogPreview).latest()
        self.styles.height = 3


class LogText(Borderless, TextArea):
    """Its look is its bases."""


class AcpLogPreview(Vertical):
    """One page of an agent's log, kept up to date while its latest record is in view.

    The file is read off the UI thread. Text enters the text area a slice per
    loop turn, so a full page never holds a frame.
    """

    # Characters drawn per loop turn (about 2 ms of wrapping).
    SLICE = 8 * 1024
    FOLLOW_INTERVAL = 1.0

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.page: LogPage | None = None
        self.view: LogView = ErrorsLogView()
        # The text the area holds in full; empty while a draw is under way.
        self._drawn = ""
        self._ready = asyncio.Event()
        self._read_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        path = LogLine(str(self.path), markup=False)
        path.tooltip = str(self.path)
        yield path
        with LogControls(min_column_width=12, regular=True):
            for kind in LogView.members_with(LogView):
                yield LogViewButton(kind)
            yield LogWrapButton("Wrap: on")
            yield LogEarlierButton("Earlier")
            yield LogLatestButton("Latest ↻")
        yield LogText(
            "Loading log…",
            read_only=True,
            soft_wrap=True,
            tooltip="Select text to copy. Wrap off: Home/End, arrows or horizontal scrollbar.",
        )
        yield LogStatus("", markup=False)

    @on(Mount)
    def on_mount(self) -> None:
        self.load_page()
        self.query_one(TextArea).focus()
        self.set_interval(self.FOLLOW_INTERVAL, self.read_new_lines)

    @on(Unmount)
    def on_unmount(self) -> None:
        self._ready.set()

    async def wait_ready(self) -> None:
        await self._ready.wait()

    async def reveal(self, position):
        await self.wait_ready()
        if self.is_attached:
            position.reveal(self.query_one(TextArea))

    def load_page(self, before: int | None = None) -> None:
        self.query_one(LogStatus).update("Reading log…")
        self._present(partial(LogPage.read, self.path, FileKind.MAX_BYTES, before))

    def read_new_lines(self) -> None:
        """Read what was written since, while the log's end is shown and its latest record is in view."""
        page = self.page
        if page is not None and page.end == page.total and self._ready.is_set() and self._at_newest():
            self._present(partial(page.extended, self.path, FileKind.MAX_BYTES), following=True)

    def _present(self, read: Callable[[], LogPage] | None, *, following: bool = False) -> None:
        """Draw the page `read` returns; without `read`, draw the page already held again."""
        self._ready.clear()
        self._read_worker = self._read_and_draw(read, following)

    @work(group="acp-log-read", exclusive=True)
    async def _read_and_draw(self, read: Callable[[], LogPage] | None, following: bool) -> None:
        try:
            page = self.page if read is None else await asyncio.to_thread(read)
            if not self.is_attached or page is None or (following and page is self.page):
                return
            await self._draw(page, following)
        except OSError as error:
            if self.is_attached:
                self.page, self._drawn = None, ""
                self.query_one(TextArea).load_text(f"Unable to read log: {error}")
                self.query_one(LogStatus).update("Log read failed. Select Latest to try reading again.")
                self.query_one(LogEarlierButton).disabled = True
        finally:
            if get_current_worker() is self._read_worker:
                self._ready.set()

    async def _draw(self, page: LogPage, following: bool) -> None:
        area = self.query_one(TextArea)
        in_view = following and self._at_newest()
        text = self.view.render(page)
        drawn, self._drawn, self.page = self._drawn, "", page
        if drawn and text.startswith(drawn):
            rest = text[len(drawn):]
        else:
            area.load_text(text[:self.SLICE])
            rest = text[self.SLICE:]
        self.query_one(LogStatus).update(
            f"{self.view.label()} · bytes {page.start:,}–{page.end:,} of {page.total:,} · "
            "Select text to copy. Wrap off: Home/End, arrows or horizontal scrollbar."
        )
        self.query_one(LogEarlierButton).disabled = page.start == 0
        for button in self.query(LogViewButton):
            button.variant = ("default", "primary")[button.kind is type(self.view)]
        for start in range(0, len(rest), self.SLICE):
            # Other work, input and paint run between slices.
            await asyncio.sleep(0)
            area.insert(rest[start:start + self.SLICE], area.document.end)
        # Drawing is not an edit to undo.
        area.history.clear()
        self._drawn = text
        if not following:
            # While following, the reader's cursor and selection stay where they are.
            area.move_cursor((0, 0) if self.view.newest_first else area.document.end)
        if not following or in_view:
            (area.scroll_home if self.view.newest_first else area.scroll_end)(animate=False)

    def _at_newest(self) -> bool:
        area = self.query_one(TextArea)
        return area.scroll_y <= 0 if self.view.newest_first else area.scroll_y >= area.max_scroll_y

    def select_view(self, kind: type[LogView]) -> None:
        self.view = kind()
        if self.page is not None:
            self._present(None)
        self.query_one(TextArea).focus()

    def toggle_wrap(self, button: LogWrapButton) -> None:
        text = self.query_one(TextArea)
        text.soft_wrap = not text.soft_wrap
        button.label = "Wrap: on" if text.soft_wrap else "Wrap: off"
        text.focus()

    def earlier(self) -> None:
        if self.page is not None:
            self.load_page(self.page.start)

    def latest(self) -> None:
        self.load_page()
