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
from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QPushButton, QWidget
from pyqt_reactive.widgets.shared.touch_scrolled import TouchScrolled
from pyqt_reactive.widgets.virtual_rows import HtmlRow, RowDocumentDelegate, RowFormatting, VirtualRowView
from toad.client.fragments import EvidencedFragment, HistoryFragment, MembershipText, Shown, WireMessage
from toad.client.history import ReadMarkedHistory
from toad.client.history_notifications import SourceNotifications
from toad.client.history_pager import (
    ConversationPager,
    DirectionalPreparation,
    DrawsBusMessages,
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
from toad.qt.action_shortcuts import bind_action_shortcuts
from toad.reader_actions import ReaderAction
from toad.view_actions import BackToBottomAction
from toad.client.transcript_fragments import (
    BusMessageFragment,
    ContextTranscriptFragment,
    FragmentClasses,
    SentMessageFragment,
    ToolTranscriptFragment,
    TranscriptFragment,
)
from toad.history_jump import JumpsToLatest
from toad.widget_view import WorkspaceHosted
from toad.workspace_frame import WorkspaceFrame
from toad.qt.lines import QtLineRenderer
from toad.transcript_filter import FilterState
from ui_theme.scheme import ColourScheme, ForegroundColour, PrimaryColour, SurfaceHoverColour


class QtWireFragment(EvidencedFragment, TranscriptFragment, ABC):
    """A wire message drawn by Qt, and the root of Qt's wire fragments: a message's role
    selects the member declared under it. Also a `TranscriptFragment`, so a transcript
    source feeding this family decodes the same shape Textual's `WireFragment` does in
    `src/toad/widgets/wire_history.py:30`."""


class QtMembershipFragment(MembershipText, QtWireFragment, shows=(Membership,)):
    """Someone joined or left, drawn by Qt."""


class QtMessageFragment(WireMessage, BusMessageFragment, QtWireFragment,
                        shows=(ConversationRole, NoticeRole)):
    """A bus message drawn by Qt. Also a `BusMessageFragment`, so the same type answers whether
    it was decoded from a wire read or from a transcript event — same bridge Textual's
    `MessageFragment` makes at `src/toad/widgets/wire_history.py:50`."""


class QtToolTranscriptFragment(ToolTranscriptFragment):
    """A tool call drawn by Qt: the canonical blocks derivation is enough; the row delegate
    paints through `line_blocks`, so Qt adds no row acquisition. Textual's sibling in
    `toad.widgets.transcript_fragments.ToolTranscriptFragment` layers on row acquisition."""


class QtContextTranscriptFragment(ContextTranscriptFragment):
    """The coordination context an agent was given, drawn by Qt."""


@dataclass(kw_only=True)
class QtSentMessageFragment(SentMessageFragment, EvidencedFragment):
    """A sent bus message drawn by Qt — the Qt flavor Qt's QtPage uses as
    `sent_message` in `QT_FRAGMENT_CLASSES`. Also an `EvidencedFragment` so
    `QtHistoryWindow.row_painted → self.history.retain_painted(fragment)` can
    read `fragment.evidence` without `AttributeError`. The client's bare
    `SentMessageFragment` lacks that field; Textual pairs it with its own
    EvidencedFragment-bearing bases at `widgets/transcript_fragments.py:170`.
    `@dataclass(kw_only=True)` so EvidencedFragment's `evidence` field
    actually lands on the instance; without it the two bases' dataclass
    declarations don't combine and `fragment.evidence` raises AttributeError."""
    evidence: object | None = None


QT_FRAGMENT_CLASSES = FragmentClasses(
    transcript=TranscriptFragment,
    context=QtContextTranscriptFragment,
    bus_message=QtMessageFragment,
    sent_message=QtSentMessageFragment,
    tool=QtToolTranscriptFragment,
)
"""The Qt flavor of the shared fragment family. A render pipeline that reaches Qt (a future
Qt entry for `AcpTab`/`MailboxTab`) passes this to `transcript_fragments(..., classes=...)`;
the current CommsTab path still goes through `WireSource` with the Qt wire fragments, since
bus messages have no transcript builder in the loop."""


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


class QtConversationHistory(DrawsBusMessages, SourceNotifications, ReadMarkedHistory, ConversationPager, NativePager):
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
                         page_source=self._initial_page_source(prepared, app))
        self.budget = self.DEFAULT_BUDGET
        self._fragment_budget = self.budget.max_items
        self.pages = deque([QtPage(prepared, self)])
        self.filter = FilterState.for_selection(self)
        window.history = self

    def _initial_page_source(self, prepared, app):
        """The page source this history binds at construction. `QtConversationHistory`
        starts closed — the shared pager replaces this through `initialize_source` when a
        wire source lands. Overridden by `QtTranscriptHistory` to bind a `SavedTranscript`
        over the view's `TranscriptPresentation`, so tool-call/sent/chunk events feed the
        history without waiting for a wire bind that never arrives on the ACP tab."""
        return ClosedHistory(prepared.page.after, app.preparation)

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
    def selected_categories(self):
        """The view owns which message categories show; the pager reads them here, as the
        Textual history reads its view's reactive. There is no second copy of the selection."""
        return self.view.visible_categories

    def apply_filter(self) -> None:
        """A category toggle changed the view's selection: draw the shown rows again."""
        self.window.show_pages()

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
        """Repaint only the rows the pager named. The shared contract already says which
        fragments changed; dropping that and calling viewport().update() repaints every
        visible row on every clock tick, so the message header flickered under scroll."""
        window = self.window
        model_rows = window.model_rows
        for fragment in (*fragments, *continuing):
            row = model_rows.row_of(fragment.key)
            if row >= 0:
                window.update(model_rows.index(row, 0))

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


class QtJumpBar(QPushButton):
    """A floating "back to bottom" button over the history's viewport: shown while the reader
    has scrolled off the tail, hidden once the end is in view. Clicking it jumps the window
    back to the latest row. The Textual sibling is `JumpBar`/`BackToBottom` in
    `src/toad/widgets/conversation.py`; both backends drive the same visibility contract
    (`JumpsToLatest.can_jump_to_latest`)."""

    def __init__(self, parent: QWidget, scheme: ColourScheme) -> None:
        # Label mirrors the Textual sibling: single source is the BackToBottomAction
        # declaration (title + key_display). Textual uses the same two attributes in
        # widgets/conversation.py's Window.__init__. Text and border take PrimaryColour
        # to match Textual's PrimaryText mixin on BackToBottom.
        super().__init__(f"{BackToBottomAction.title}  ↓ {BackToBottomAction.key_display}", parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        primary = PrimaryColour.rgb(scheme).hex
        self.setStyleSheet(
            "QPushButton {"
            f"  background: {SurfaceHoverColour.rgb(scheme).hex};"
            f"  color: {primary};"
            f"  border: 1px solid {primary};"
            "  border-radius: 14px;"
            "  padding: 6px 14px;"
            "  font-weight: bold;"
            "}"
        )
        self.hide()


class QtHistoryWindow(JumpsToLatest, WorkspaceHosted, TouchScrolled, VirtualRowView,
                      ReaderPlacement, PagingWindow):
    """The reader window of one Qt conversation: pyqt-reactive's virtual rows of the
    history's shown fragments, scrolled by pixel. It answers the shared pager's window
    contract: reaching the top reads older pages, the bottom newer ones, End and the
    reader at the end follow the newest row, and rows that arrive or are evicted above the
    reader leave the row they are reading where it was."""

    # Emitted when the viewer right-clicks or long-presses a message row; carries the
    # fragment under that point. Consumers (ConversationView) build a block menu from
    # the shared `MenuCommand` family and offer it through the host's offer panel.
    block_menu_requested = Signal(object, name="blockMenuRequested")

    history: QtConversationHistory
    # `scroll_revision` + `history_change` are declared on JumpsToLatest (shared with Textual).

    @property
    def screen(self) -> WorkspaceFrame:
        """Qt's workspace frame is the top-level `QtToadApp` (which inherits
        `QtWorkspaceFrame`). Qt widgets reach it through `window()`, not through a
        Textual `Widget.screen` chain, so `WorkspaceHosted`'s `super().screen` is
        replaced here."""
        return self.window()

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
        # The floating "jump to latest" button: child of the window (not the viewport), so
        # QScroller's gesture grab on the viewport (from TouchScrolled) can't swallow the
        # tap and prevent `clicked` from firing on Android. Positioned over the viewport
        # by `_place_jump_bar`. Show/hide is driven by `tail_follow_changed` from `scrolled`.
        self.jump_bar = QtJumpBar(self, scheme)
        self.jump_bar.clicked.connect(self.jump_to_latest)
        self.viewport().installEventFilter(self)
        # Block menu: right-click (desktop) and long-press (Android) on a message row
        # emit `block_menu_requested` with the row's fragment. ConversationView mounts
        # the handler and runs the resulting commands.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_block_menu_at)
        self.viewport().grabGesture(Qt.GestureType.TapAndHoldGesture)
        # Reader keys (ctrl+d / ctrl+u / shift+g) come from the `ReaderAction` family
        # declared in `src/toad/reader_actions.py`. Both backends drive from that one
        # declaration: Textual through the Action/BindingsMap path, Qt through
        # `bind_action_shortcuts` which iterates members and installs a QShortcut per
        # declared key firing `apply(self)` (which calls `action_page_down` /
        # `action_page_up` / `jump_to_latest` on this window).
        self._reader_shortcuts = bind_action_shortcuts(self, ReaderAction, self)

    def action_page_down(self) -> None:
        """Move the reader one page toward the latest message (Textual's `ReaderAction`
        family calls the Textual-named `action_page_down` on the window; Qt exposes the
        same method here and drives the scroll bar by one viewport."""
        bar = self.verticalScrollBar()
        bar.setValue(min(bar.maximum(), bar.value() + self.viewport().height()))

    def action_page_up(self) -> None:
        """One viewport-height's scroll toward older history, the Qt mirror of
        Textual's `PageUpAction`."""
        bar = self.verticalScrollBar()
        bar.setValue(max(bar.minimum(), bar.value() - self.viewport().height()))

    # `can_jump_to_latest` body (returns `not self.follows_tail`) is shared on JumpsToLatest.

    def _jump_bar_shown(self) -> bool:
        return self.jump_bar.isVisible()

    def _set_jump_bar_shown(self, shown: bool) -> None:
        self.jump_bar.setVisible(shown)

    def _after_jump_bar_change(self, shown: bool) -> None:
        if shown:
            self._place_jump_bar()

    def _place_jump_bar(self) -> None:
        """Position the floating bar over the viewport's bottom-center. The bar is a child
        of the window, not the viewport, so coordinates map through `viewport().mapTo(self)`
        — that way QScroller's gesture grab on the viewport can't swallow a tap on the bar."""
        vp = self.viewport()
        hint = self.jump_bar.sizeHint()
        self.jump_bar.resize(hint)
        point_in_vp = QPoint((vp.width() - hint.width()) // 2, vp.height() - hint.height() - 12)
        self.jump_bar.move(vp.mapTo(self, point_in_vp))
        self.jump_bar.raise_()

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:  # type: ignore[override]
        if obj is self.viewport():
            if event.type() == QEvent.Type.Resize and self.jump_bar.isVisible():
                self._place_jump_bar()
            elif event.type() == QEvent.Type.Gesture:
                held = event.gesture(Qt.GestureType.TapAndHoldGesture)
                if held is not None and held.state() == Qt.GestureState.GestureFinished:
                    self._emit_block_menu_at(self.viewport().mapFromGlobal(held.position().toPoint()))
                    return True
        return super().eventFilter(obj, event)

    def _emit_block_menu_at(self, point: QPoint) -> None:
        """Right-click or long-press at ``point`` (viewport coordinates): emit the
        fragment under that row so ConversationView can open the block menu."""
        index = self.indexAt(point)
        if not index.isValid():
            return
        fragment = self.model_rows.data(index, HistoryRows.FRAGMENT)
        if fragment is None:
            return
        self.block_menu_requested.emit(fragment)

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

    def jump_to_latest(self) -> None:
        """`JumpsToLatest.jump_to_latest` is abstract; the QtJumpBar click is wired to this
        at `__init__` (`self.jump_bar.clicked.connect(self.jump_to_latest)`). Without the
        override, clicking the Back-to-Bottom button ran the abstract docstring-only body
        and did nothing. Snapping back to the tail via `anchor(True)` runs `follow_end`
        which scrolls the viewport to the latest row, mirroring Textual's
        `WindowAction.scroll_end` path."""
        self.anchor(True)

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
        """The reader moved: join or leave the end, then delegate the post-anchor response
        (lookahead, settle timer, preparation, tail-follow) to the shared template on
        `JumpsToLatest.respond_to_scroll` — same gate Textual uses, so no-travel ticks
        from QScroller don't restart the settle timer during Android touch scrolls."""
        if self._restoring:
            return
        if self.at_end and not self.follows_tail:
            self.anchor()
        elif not self.at_end and self.follows_tail:
            self.release_anchor()
        elif not self.follows_tail:
            self.reader_position = RowPosition(value)
        self.respond_to_scroll(value)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """A wheel at an edge with nowhere left to scroll still asks for the next page."""
        rows = -event.angleDelta().y() / 120 * self._font_line_spacing() * 3
        if not self.lookahead.request_boundary(rows):
            super().wheelEvent(event)

    def row_painted(self, fragment: HistoryFragment, rect: QRect) -> None:
        """A row whose text is on screen, beyond its header line, was seen.

        Reads a cached `lineSpacing` so the delegate's per-row `paint` doesn't allocate
        a fresh `QFontMetrics` on every visible row during scroll — on a long transcript
        this was hundreds of allocations per frame."""
        shown = rect.intersected(self.viewport().rect())
        if shown == rect or shown.height() > 2 * self._font_line_spacing():
            self.history.retain_painted(fragment)

    def _font_line_spacing(self) -> int:
        """Cached `QFontMetrics(self.font()).lineSpacing()`; refreshed on a font change."""
        font = self.font()
        cached = getattr(self, "_cached_font_line_spacing", None)
        if cached is None or cached[0] != font:
            spacing = QFontMetrics(font).lineSpacing()
            self._cached_font_line_spacing = (QFont(font), spacing)
            return spacing
        return cached[1]

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
