"""A conversation's history as Qt draws it.

The shared pager (toad.client.history_pager) reads, keeps and evicts the pages and
follows the end; the shared ReadMarkedHistory marks read what the reader was shown.
Qt draws the loaded pages as pyqt-reactive virtual rows: one row per shown fragment,
its line blocks rendered as rich text on the delegate's thread pool while the row
paints plain, and only the rows on screen laid out. Heights are pixels, so the pager's
rows are pixels here.
"""

from __future__ import annotations

import asyncio
from abc import ABC
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import partial
from weakref import WeakSet

from agent_comms.messaging.messages import ConversationRole, Membership, NoticeRole
from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QWidget
from pyqt_reactive.widgets.shared.touch_scrolled import TouchScrolled
from pyqt_reactive.widgets.virtual_rows import HtmlRow, RowDocumentDelegate, RowFormatting, VirtualRowView
from ui_theme.scheme import ColourScheme

from toad.client.fragments import EvidencedFragment, HistoryFragment, MembershipText, Shown, WireMessage
from toad.client.history import ReadMarkedHistory
from toad.client.history_notifications import SourceNotifications
from toad.client.history_pager import (
    ConversationPager,
    DirectionalPreparation,
    NativePager,
    OffScreenRunway,
    PagingWindow,
    PresentationBudget,
    ReaderPlacement,
    Runway,
)
from toad.client.history_preparation import HistorySourceSnapshot
from toad.client.history_state import LiveTranscript
from toad.client.prepared_pages import ClosedHistory, PreparedTranscriptPage
from toad.client.reader_position import FragmentLocation, ReaderPage, RowPosition, TailPosition
from toad.qt.lines import QtLineRenderer
from toad.transcript_filter import FilterState


class QtWireFragment(EvidencedFragment, ABC):
    """A wire message drawn by Qt, and the root of Qt's wire fragments: a message's role
    selects the member declared under it."""


class QtMembershipFragment(MembershipText, QtWireFragment, shows=(Membership,)):
    """Someone joined or left, drawn by Qt."""


class QtMessageFragment(WireMessage, QtWireFragment, shows=(ConversationRole, NoticeRole)):
    """A bus message drawn by Qt."""


class QtPage(ReaderPage):
    """One prepared page, drawn as the rows of the fragments in its range that its history
    shows. The rows themselves live in the window's model, read from the pages."""

    arrivals: frozenset = frozenset()
    rows_measured = True

    def __init__(self, prepared: PreparedTranscriptPage, history: QtConversationHistory) -> None:
        self.prepared = prepared
        self.history = history
        self.display = False
        prepared.configure(batch_size=PresentationBudget.batch_items)

    @classmethod
    def drawn_for(cls, owner: QtConversationHistory, prepared: PreparedTranscriptPage) -> QtPage:
        return cls(prepared, owner)

    @property
    def shown_fragments(self) -> tuple[HistoryFragment, ...]:
        selected = self.history.selected_categories
        return tuple(fragment for fragment in self.prepared.fragments_in_range if fragment.shown_in(selected))

    @property
    def line_count(self) -> int:
        """The pixels this page's rows take in the window."""
        return sum(self.history.fragment_height(fragment) for fragment in self.shown_fragments)

    def range_changed(self) -> None:
        self.history.window.show_pages()

    def set_categories(self, selected) -> None:
        """A filter change: the history's selection decides which rows show."""
        self.range_changed()

    def remove(self) -> None:
        """An evicted page's rows go with the next row reset."""
        self.display = False

    def drawn_height(self, fragment: HistoryFragment) -> int:
        return self.history.fragment_height(fragment)

    def fragment_row(self, key, block: int) -> FragmentLocation:
        return self.history.window.fragment_location(key)


class HistoryRows(QAbstractListModel):
    """The shown fragments of a history's loaded pages, one row each."""

    FRAGMENT = Qt.ItemDataRole.UserRole

    def __init__(self) -> None:
        super().__init__()
        self.fragments: tuple[HistoryFragment, ...] = ()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self.fragments)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        """The fragment itself, or its plain text to display; a row answers no other role."""
        fragment = self.fragments[index.row()]
        return {self.FRAGMENT: fragment, Qt.ItemDataRole.DisplayRole: fragment.clipboard_text}.get(role)

    def show(self, fragments: tuple[HistoryFragment, ...]) -> None:
        self.beginResetModel()
        self.fragments = fragments
        self.endResetModel()

    def row_of(self, key) -> int:
        return next((row for row, fragment in enumerate(self.fragments) if fragment.key == key), -1)


class HistoryRowDelegate(RowDocumentDelegate):
    """Each fragment's line blocks as Qt rich text, rendered on the pool at the row's width
    (dividers fill it); a row paints its plain text until then. A painted row tells the
    window, which marks what the reader saw."""

    def __init__(self, scheme: ColourScheme) -> None:
        super().__init__()
        self.renderer = QtLineRenderer(scheme)
        """Draws on the pool thread only: the renderer keeps the width it last drew at."""

    def preparation_key(self, index: QModelIndex, font: QFont, width: int):
        return self.fragment_key(index.data(HistoryRows.FRAGMENT), font, width)

    def preparation(self, index: QModelIndex, font: QFont, width: int) -> Callable[[], RowFormatting]:
        return self.rendering(index.data(HistoryRows.FRAGMENT), font, width)

    def fragment_key(self, fragment: HistoryFragment, font: QFont, width: int):
        """A fragment's row as shown, in this font at this width: dividers fill the width."""
        return (fragment.key, fragment.shown), font.family(), font.pointSize(), width

    def rendering(self, fragment: HistoryFragment, font: QFont, width: int) -> Callable[[], RowFormatting]:
        return partial(self.html, fragment.line_blocks, width, QFont(font))

    def html(self, blocks, width: int, font: QFont) -> RowFormatting:
        return HtmlRow(self.renderer.at_width(width - 8, font).html(blocks))

    def fragment_height(self, fragment: HistoryFragment, font: QFont, width: int) -> int:
        """How tall a fragment's row is at this width, before the model holds it. The shared
        row measurement caches this by key and width, so a pager summing its rows' pixels
        every scrolled frame lays each row out once, not afresh on every frame."""
        key = self.fragment_key(fragment, font, width)
        formatting = self.keyed_formatting(key, fragment.clipboard_text, self.rendering(fragment, font, width))
        return self.measured_height(key, font, width, formatting)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        super().paint(painter, option, index)
        self.view.row_painted(index.data(HistoryRows.FRAGMENT), option.rect)


class NoTask:
    """No read or read-ahead has started yet."""

    def done(self) -> bool:
        return True

    def cancel(self) -> None:
        """Nothing runs to cancel."""


class SourceTask(asyncio.Task):
    """Source work running on the Qt event loop; the pager's states join it with wait()."""

    async def wait(self) -> None:
        await asyncio.gather(self, return_exceptions=True)


class QtConversationHistory(SourceNotifications, ReadMarkedHistory, ConversationPager, NativePager):
    """A wire conversation's pages, read marks and message statuses in a Qt window: the
    shared pager, read marking and notifications, answering their hooks with the window's
    rows and the Qt event loop."""

    page_view_type = QtPage
    newer = None
    """Where a page mounted at the newer end goes: Qt rows have no edge widget."""

    def __init__(self, window: QtHistoryWindow, view, app) -> None:
        self._window = window
        self.view = view
        self.notification_view = view
        self.app = app
        self.attached = True
        self.lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._read_task: asyncio.Task | NoTask = NoTask()
        self._read_ahead: asyncio.Task | NoTask = NoTask()
        prepared = self.empty_page()
        super().__init__(source_state=LiveTranscript(),
                         page_source=ClosedHistory(prepared.page.after, app.preparation))
        self.budget = self.DEFAULT_BUDGET
        self._fragment_budget = self.budget.max_items
        self.pages = deque([QtPage(prepared, self)])
        self.filter = FilterState.for_selection(self)
        window.history = self

    # Where the pager draws

    @property
    def window(self) -> QtHistoryWindow:
        return self._window

    @property
    def is_attached(self) -> bool:
        return self.attached

    @property
    def is_leaving(self) -> bool:
        return not self.attached

    @property
    def can_draw_on_screen(self) -> bool:
        return self.state.can_draw and self.window.presenting

    def source_snapshot(self) -> HistorySourceSnapshot:
        return HistorySourceSnapshot(self._generation, self.window, self.window, self.source_identity)

    def followed_here(self) -> None:
        self.window.histories.add(self)

    def request_preparation(self) -> None:
        self.window.request_preparation()

    def prepare_visible_pages(self) -> None:
        """Qt rows lay themselves out where drawn: no page holds committed geometry."""

    def visible_fragments(self) -> tuple[HistoryFragment, ...]:
        return self.window.visible_fragments()

    def fragment_height(self, fragment: HistoryFragment) -> int:
        return self.window.fragment_height(fragment)

    async def prepare_fragments(self, fragments, current, *, selected, target) -> None:
        """Rows render on the delegate's pool when first drawn: nothing to prepare first."""

    def hold_arrival(self, arrivals: tuple[HistoryFragment, ...]) -> None:
        """Qt draws arrivals at once: no rows are held below a following reader."""

    async def _show(self, changes: list[tuple[HistoryFragment, Shown]]) -> None:
        """A status change lays the rows out again: a row's cache key carries how its fragment
        is shown, so the changed rows render anew."""
        changed = [fragment for fragment, shown in changes if fragment.request_show(shown)]
        if changed:
            self.window.rows_changed()

    def repaint(self, fragments: tuple[HistoryFragment, ...] = (), *, continuing=()) -> None:
        self.window.viewport().update()

    def _update_edges(self) -> None:
        """Older and newer rows load as the reader nears an edge: Qt shows no edge controls."""

    async def mount(self, view: QtPage, *, before) -> None:
        """A page's rows join the window when its publication resets them."""

    async def remove_children(self, pages) -> None:
        """Retired pages' rows go with the publication's row reset."""

    def call_after_refresh(self, callback: Callable, *arguments: object) -> None:
        QTimer.singleShot(0, partial(callback, *arguments))

    def publish_core(self, event: object) -> None:
        """No Qt listener waits on a history's source work."""

    # Running source work on the Qt event loop

    def run_worker(self, work: Callable[[], Awaitable[object]], **_options: object) -> SourceTask:
        task = SourceTask(work(), loop=asyncio.get_event_loop())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def read_ahead(self, work: Callable[[], Awaitable[object]]) -> None:
        self._read_ahead.cancel()
        self._read_ahead = self.run_worker(work)

    def cancel_work(self) -> list:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        return tasks

    def joined(self, workers: list) -> Awaitable[None]:
        return asyncio.ensure_future(asyncio.gather(*workers, return_exceptions=True))

    # Read marking

    def read_running(self) -> bool:
        return not self._read_task.done()

    def start_read(self, work: Awaitable[None]) -> asyncio.Task:
        self._read_task = asyncio.ensure_future(work)
        return self._read_task

    def read_postponed(self, error: Exception) -> None:
        """Core held the acknowledgement; the next painted frame tries again."""

    def mark_visible_after_paint(self) -> None:
        QTimer.singleShot(0, self.mark_visible)

    def withdraw_view(self) -> None:
        self.view.hide()

    async def refresh_source(self) -> None:
        await self.view._refresh()

    def close(self) -> None:
        self.attached = False
        super().close()


@dataclass(frozen=True)
class QtTopRow:
    """The row under a Qt window's top edge: Qt keeps its reader by scroll row."""

    def reader_position(self, window: QtHistoryWindow) -> RowPosition:
        return RowPosition(window.scroll_y)


class QtHistoryWindow(TouchScrolled, VirtualRowView, ReaderPlacement, PagingWindow):
    """The reader window of one Qt conversation: pyqt-reactive's virtual rows of the
    history's shown fragments, scrolled by pixel. It answers the shared pager's window
    contract: reaching the top reads older pages, the bottom newer ones, End and the
    reader at the end follow the newest row, and rows that arrive or are evicted above the
    reader leave the row they are reading where it was."""

    history: QtConversationHistory
    scroll_revision = 0

    def __init__(self, scheme: ColourScheme, parent: QWidget | None = None) -> None:
        super().__init__(HistoryRowDelegate(scheme), parent)
        self.model_rows = HistoryRows()
        self.setModel(self.model_rows)
        self.histories: WeakSet = WeakSet()
        self.history_lock = asyncio.Lock()
        self.presentation_budget = PresentationBudget()
        self.lookahead = DirectionalPreparation(self)
        self.reader_position = TailPosition()
        self._anchored = True
        self._restoring = False
        self._preparing = False
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._settle)
        self.verticalScrollBar().valueChanged.connect(self.scrolled)

    # Geometry, in pixels

    @property
    def scroll_y(self) -> float:
        return self.verticalScrollBar().value()

    @scroll_y.setter
    def scroll_y(self, value: float) -> None:
        self.verticalScrollBar().setValue(int(value))

    @property
    def scroll_target_y(self) -> float:
        """Qt scrolls at once: its target is where it is."""
        return self.scroll_y

    @property
    def max_scroll_y(self) -> float:
        return self.verticalScrollBar().maximum()

    @property
    def tail_scroll_y(self) -> float:
        return self.max_scroll_y

    @property
    def viewport_rows(self) -> int:
        return self.viewport().height()

    @property
    def content_rows(self) -> int:
        return self.viewport().height()

    @property
    def unfilled_rows(self) -> int:
        rows = self.model_rows.rowCount()
        if not rows:
            return self.viewport().height()
        return max(0, self.viewport().height() - self.visualRect(self.model_rows.index(rows - 1, 0)).bottom())

    @property
    def animated_travel(self) -> float:
        return 0

    @property
    def presenting(self) -> bool:
        return self.isVisible()

    def runway(self, history) -> OffScreenRunway:
        if not self.presenting:
            return OffScreenRunway()
        return Runway(int(self.scroll_y), int(self.max_scroll_y - self.scroll_y))

    def fragment_height(self, fragment: HistoryFragment) -> int:
        return self.rows.fragment_height(fragment, self.font(), self.viewport_width())

    def visible_fragments(self) -> tuple[HistoryFragment, ...]:
        area = self.viewport().rect()
        top, bottom = self.indexAt(area.topLeft()), self.indexAt(area.bottomLeft())
        if not top.isValid():
            return ()
        last = bottom.row() if bottom.isValid() else self.model_rows.rowCount() - 1
        return self.model_rows.fragments[top.row():last + 1]

    def fragment_location(self, key) -> FragmentLocation:
        raise LookupError(key)

    # The reader

    @property
    def follows_tail(self) -> bool:
        return self._anchored

    def anchor(self, anchor: bool = True) -> None:
        changed = self._anchored != anchor
        if not self._restoring and changed:
            self.scroll_revision += 1
        self._anchored = anchor
        if anchor:
            self.reader_position = self.reader_position.joined_tail()
            with self.layout_scroll():
                self.follow_end()
        else:
            self.reader_position = RowPosition(self.scroll_y)

    def release_anchor(self) -> None:
        if self.follows_tail:
            self.anchor(False)

    def check_follow(self) -> bool:
        if not self.follows_tail:
            return False
        previous = self.scroll_y
        with self.layout_scroll():
            self.scroll_y = self.tail_scroll_y
        return previous != self.scroll_y

    @contextmanager
    def layout_scroll(self) -> Iterator[None]:
        """Scrolling inside is the window keeping the reader in place, not the reader moving."""
        restoring = self._restoring
        previous = self.scroll_y
        self._restoring = True
        try:
            yield
        finally:
            if not restoring:
                self.lookahead.relocated(self.scroll_y - previous)
            self._restoring = restoring

    @asynccontextmanager
    async def preserve_history(self):
        """Pages change inside; then the rows are read again from the pages, and the reader
        stays on the row it was reading, or at the end when following it."""
        top = self.indexAt(self.viewport().rect().topLeft())
        key = top.data(HistoryRows.FRAGMENT).key if top.isValid() else None
        offset = self.visualRect(top).top() if top.isValid() else 0
        try:
            yield
        finally:
            self.show_pages()
            self.keep_reader(key, offset)

    def show_pages(self) -> None:
        """Read the rows again from the history's shown pages."""
        history = self.history
        self.model_rows.show(tuple(fragment for page in history.pages if page.display
                                   for fragment in page.shown_fragments))
        self.doItemsLayout()

    def rows_changed(self) -> None:
        """Prepared rows changed height: lay them out again, keeping the reader's row."""
        top = self.indexAt(self.viewport().rect().topLeft())
        key = top.data(HistoryRows.FRAGMENT).key if top.isValid() else None
        offset = self.visualRect(top).top() if top.isValid() else 0
        self.doItemsLayout()
        self.keep_reader(key, offset)
        self.viewport().update()

    def keep_reader(self, key, offset: int) -> None:
        """After a layout: at the end when following it, else the row `key` back at `offset`."""
        with self.layout_scroll():
            if self.follows_tail:
                self.follow_end()
            elif (row := self.model_rows.row_of(key)) >= 0:
                moved = self.visualRect(self.model_rows.index(row, 0)).top() - offset
                self.scroll_y = self.scroll_y + moved
        if not self.follows_tail:
            self.reader_position = RowPosition(self.scroll_y)

    def scrolled(self, value: int) -> None:
        """The reader moved: measure the travel, join or leave the end, read toward it."""
        if self._restoring:
            return
        self.lookahead.observe(value)
        if self.at_end and not self.follows_tail:
            self.anchor()
        elif not self.at_end and self.follows_tail:
            self.release_anchor()
        elif not self.follows_tail:
            self.reader_position = RowPosition(value)
        self._schedule_settle()
        self.request_preparation()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """A wheel at an edge with nowhere left to scroll still asks for the next page."""
        rows = -event.angleDelta().y() / 120 * QFontMetrics(self.font()).lineSpacing() * 3
        if not self.lookahead.request_boundary(rows):
            super().wheelEvent(event)

    def row_painted(self, fragment: HistoryFragment, rect: QRect) -> None:
        """A row whose text is on screen, beyond its header line, was seen."""
        shown = rect.intersected(self.viewport().rect())
        if shown == rect or shown.height() > 2 * QFontMetrics(self.font()).lineSpacing():
            self.history.retain_painted(fragment)

    # Frames

    def request_preparation(self) -> None:
        if not self._preparing:
            self._preparing = True
            QTimer.singleShot(0, self.prepare_viewport)

    def prepare_viewport(self) -> None:
        self._preparing = False
        for history in tuple(self.histories):
            history.prepare_viewport()

    def _schedule_settle(self) -> None:
        self._settle_timer.start(int(self.lookahead.idle_seconds * 1000))

    def after_source_presented(self, callback, *arguments) -> None:
        QTimer.singleShot(0, partial(callback, *arguments))

    def request_reader_layout(self) -> None:
        self.place_reader()

    # The reader window contract's measurements Qt keeps by row instead

    def top_page(self) -> QtTopRow:
        return QtTopRow()

    def placements(self, bodies) -> Iterator[tuple[object, int]]:
        return iter(())

    def placed_live_blocks(self) -> Iterator[tuple[object, int]]:
        """Qt draws no live blocks: every row is a saved fragment."""
        return iter(())

    def holds(self, item) -> bool:
        return False

    def row_of(self, item) -> int:
        raise LookupError(item)

    def drawn_pages(self) -> Iterator[QtPage]:
        return (page for history in self.histories for page in history.pages if page.display)

    def message_too_tall(self, height: int) -> bool:
        return height > self.viewport_rows

    def message_head_hidden(self, height: int, head_y: int) -> bool:
        return self.message_too_tall(height) and head_y < 0
