"""A conversation's history as Qt draws it.

The shared pager (toad.client.history_pager) reads, keeps and evicts the pages and
follows the end; the shared ReadMarkedHistory marks read what the reader was shown.
Qt draws the loaded pages as pyqt-reactive virtual rows: one row per shown fragment,
its line blocks rendered as rich text on the delegate's thread pool while the row
paints plain, and only the rows on screen laid out. Heights are pixels, so the pager's
rows are pixels here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncio

import shiboken6
from abc import ABC
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import ClassVar
from weakref import WeakSet

from agent_comms.messaging.messages import ConversationRole, Membership, NoticeRole
from metaclass_registry.mro_dispatch import handles
from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPoint, QPointF, QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QDesktopServices, QFont, QFontMetrics, QPainter, QPixmap, QTextDocument
from PySide6.QtWidgets import QApplication, QPushButton, QScroller, QStyleOptionViewItem, QWidget
from pyqt_reactive.widgets.virtual_rows import HtmlRow, PlainRow, RowDocumentDelegate, RowFormatting, VirtualRowView
from toad.client.pending import AwaitsFirstPage
from toad.qt.finger_press import FingerPress, Press
from toad.client.fragments import EvidencedFragment, FragmentDetails, HistoryFragment, MembershipText, Shown, WireMessage
from toad.core.projection import MroProjection
from toad.link_opening import OpensLineLinks
from toad.navigation_target import NavigationTarget
from toad.project_link import ExternalProjectLink, ProjectFileLink, ProjectLink
from toad.client.history import ReadMarkedHistory
from toad.client.history_notifications import OneHistoryNotifications, SourceNotifications
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
from toad.client.line_blocks import Divider
from toad.client.history_changes import FragmentRowUnderTop, HeaderPin, PinnedHeader, PinsMessageHeader, TopPage
from toad.client.history_preparation import HistorySourceSnapshot
from toad.client.history_state import LiveTranscript
from toad.client.prepared_pages import ClosedHistory, PreparedTranscriptPage
from toad.client.reader_position import FragmentLocation, ReaderPage, RowPosition, TailPosition
from toad.qt.float_layer import QtFloatLayer
from toad.reader_actions import ReaderAction
from toad.view_actions import LatestJumpBar
from toad.client.transcript_fragments import (
    BusMessageFragment,
    ContextTranscriptFragment,
    FragmentClasses,
    SentMessageFragment,
    ToolTranscriptFragment,
    TranscriptFragment,
)
from toad.history_jump import FollowsTail, JumpsToLatest, ReaderWindow
from toad.widget_view import WorkspaceHosted
from toad.workspace_frame import WorkspaceFrame
from toad.markdown_links import LinkContext
from toad.qt.lines import QtLineRenderer
from toad.transcript_filter import DrawnFilter, FilterState
from toad.frame_presentation import ARRIVAL
from toad.motion import FOLLOW_ARRIVAL, HEAD_REVEAL, TransitionTarget
from toad.qt.widget_animation import WidgetAnimation
from ui_theme.scheme import BackgroundColour, ForegroundColour, PrimaryColour, SurfaceHoverColour

if TYPE_CHECKING:
    from toad.qt.live_turn import QtLiveBlock


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
        self.history.window.committed_pages_changed()

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
    ROLE_ANSWERS: ClassVar[dict[int, Callable[[HistoryFragment], object]]] = {
        FRAGMENT: lambda fragment: fragment,
        Qt.ItemDataRole.DisplayRole: lambda fragment: fragment.clipboard_text,
    }

    def __init__(self) -> None:
        super().__init__()
        self.fragments: tuple[HistoryFragment, ...] = ()
        self._rows: dict = {}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self.fragments)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        """The fragment itself, or its plain text to display; a row answers no other role.
        Only the asked role's answer is read: Qt asks a row for many roles each time it sizes
        or paints it, and the plain text is built from the message, not stored."""
        answer = self.ROLE_ANSWERS.get(role)
        return None if answer is None else answer(self.fragments[index.row()])

    def show(self, fragments: tuple[HistoryFragment, ...]) -> None:
        self.beginResetModel()
        self.fragments = fragments
        # Every row a key names, built with the rows: a lookup is asked per changed row on
        # each receipt update, arrival, glide and reader restore, and a scan compared every
        # row's key each time.
        rows: dict = {}
        for row, fragment in enumerate(fragments):
            rows.setdefault(fragment.key, row)
        self._rows = rows
        self.endResetModel()

    def row_of(self, key) -> int:
        return self._rows.get(key, -1)


class ArrivalFade(WidgetAnimation):
    """Rows that arrived together, rising as the TUI's `ARRIVAL` cascade raises them: each fades
    from the background into its own colours, row after row, on the app's clock. A row's
    opacity is the cascade's `Mix` amount at the row's place in the burst, the frame Textual's
    `TranscriptHistory` paints, so `TEXTUAL_ANIMATIONS=none` shows them at once in both."""

    def __init__(self, window: QtHistoryWindow, keys: tuple) -> None:
        self.window = window
        self.bind_widget(window, window.animation_clock)
        last = max(1, len(keys) - 1)
        self.positions = {key: index / last for index, key in enumerate(keys)}
        self.animation = window.animation_clock.start(ARRIVAL, self)

    def opacity(self, key) -> float | None:
        position = self.positions.get(key)
        return None if position is None else self.animation.at(position).amount

    def repaint(self) -> None:
        """Only the rising rows: a whole-viewport update every tick flickers the pinned header."""
        window = self.window
        if self.animation.finished:
            window.arrival_landed(self)
        model_rows = window.model_rows
        for key in self.positions:
            if (row := model_rows.row_of(key)) >= 0:
                window.update(model_rows.index(row, 0))


class ArrivalGlide(WidgetAnimation, TransitionTarget):
    """A reader following the end glides down to rows that arrived (`FOLLOW_ARRIVAL`) instead of
    jumping their height in one frame; it lands on the end however far the rows grew meanwhile."""

    def __init__(self, window: QtHistoryWindow, start: float) -> None:
        self.window, self.start = window, start
        self.at = start
        self.bind_widget(window, window.animation_clock)
        self.start_transition(window.animation_clock, FOLLOW_ARRIVAL)

    def apply_amount(self, amount: float) -> None:
        window = self.window
        if not window.follows_tail:
            self.animation.stop()
            window.glide = None
            return
        # Only ever down: a row that lands mid-glide moves the end, never the reader back up.
        self.at = max(self.at, window.scroll_y, self.start + (window.tail_scroll_y - self.start) * amount)
        with window.layout_scroll():
            window.scroll_y = self.at

    def land(self) -> None:
        window = self.window
        window.glide = None
        if window.follows_tail:
            with window.layout_scroll():
                window.follow_end()


class HeadReveal(WidgetAnimation, TransitionTarget):
    """A tapped message whose head is above the viewport glides its head up to the top
    (`HEAD_REVEAL`), as Textual's clicked-head reveal scrolls it into view. A finger that
    takes the rows again stops it where it is."""

    def __init__(self, window: QtHistoryWindow, start: float, target: float) -> None:
        self.window, self.start, self.target = window, start, target
        self.bind_widget(window, window.animation_clock)
        self.start_transition(window.animation_clock, HEAD_REVEAL)

    def apply_amount(self, amount: float) -> None:
        window = self.window
        window.scroll_y = self.start + (self.target - self.start) * amount

    def land(self) -> None:
        window = self.window
        if window.head_reveal is self:
            window.head_reveal = None
            window.scroll_y = self.target

    def cancel(self) -> None:
        """Stop where it is: the reader's own scrolling owns the rows now."""
        self.window.head_reveal = None
        self.animation.stop()


class HistoryRowDelegate(RowDocumentDelegate):
    """Each fragment's line blocks as Qt rich text, rendered on the pool at the row's width
    (dividers fill it); a row paints its plain text until then. A painted row tells the
    window, which marks what the reader saw."""

    ROW_PADDING = 0
    """The blocks own their spacing (`Gap`), as Textual's rows do: the parts of one message
    meet, so its accent bar runs unbroken from part to part."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        # Each drawn row's last prepared look (`styled_formatting`), by `row_identity`.
        self.last_shown: dict = {}
        self.app_renderer = renderer
        """The app's renderer, which follows `ui.theme` and the `diff` settings."""
        self.renderer = renderer
        """Replaced, never mutated, when the link context settles or the app's renderer
        restyles: a preparation already on the pool keeps the binding it was handed."""
        self.links_revision = 0
        # A rising row's picture while it fades in, by fragment key: (look, pixmap).
        self.fading: dict = {}

    def link(self, links: LinkContext) -> None:
        """Rows draw with these names from now on; rows prepared before are stale."""
        self.renderer = self.app_renderer.with_links(links)
        self.links_revision += 1

    def restyle(self) -> None:
        """The app's renderer took a new scheme or diff marks: rows draw by it from now on,
        with the names they had; rows prepared before are stale."""
        self.link(self.renderer.links)

    def preparation_key(self, index: QModelIndex, font: QFont, width: int):
        return self.fragment_key(index.data(HistoryRows.FRAGMENT), font, width)

    def preparation(self, index: QModelIndex, font: QFont, width: int) -> Callable[[], RowFormatting]:
        return self.rendering(index.data(HistoryRows.FRAGMENT), font, width)

    def fragment_key(self, fragment: HistoryFragment, font: QFont, width: int):
        """A fragment's row as shown, with these links, in this font at this width: dividers
        fill the width. A draft or live row grows, so its revision is part of the key."""
        shown = fragment.key, fragment.shown, fragment.revision
        return shown, self.links_revision, font.family(), font.pointSize(), width

    def rendering(self, fragment: HistoryFragment, font: QFont, width: int) -> Callable[[], RowFormatting]:
        return partial(self.html, self.renderer, fragment.line_blocks, width, QFont(font))

    @staticmethod
    def html(renderer: QtLineRenderer, blocks, width: int, font: QFont) -> RowFormatting:
        return HtmlRow(renderer.at_width(width - 8, font).html(blocks))

    def fragment_height(self, fragment: HistoryFragment, font: QFont, width: int) -> int:
        """How tall a fragment's row is at this width, before the model holds it. The shared
        row measurement caches this by key and width, so a pager summing its rows' pixels
        every scrolled frame lays each row out once, not afresh on every frame."""
        key = self.fragment_key(fragment, font, width)
        # The formatting is asked for only when the height is not yet measured at this width.
        formatting = PreparedOnFill(lambda: self.styled_formatting(key, fragment, font, width))
        return self.measured_height(key, font, width, formatting)

    def block_row(self, fragment: HistoryFragment, font: QFont, width: int, y: int) -> tuple[int, int]:
        """Which of `fragment`'s line blocks its row draws at pixel `y`, and which line of that
        block: the unit the fragment's own header decision (`sticky_header`) reads. A block's
        height is its own rows laid out at this width, cached as the row's height is. Only the
        header blocks are measured: past them the pin is the same in every block
        (`header_blocks`), so a `y` below them answers the first block after them."""
        blocks = fragment.line_blocks
        line = QFontMetrics(font).lineSpacing() or 1
        key = self.fragment_key(fragment, font, width)
        top = 0
        decided = fragment.header_blocks
        for index, block in enumerate(blocks):
            if index == decided and index < len(blocks) - 1:
                return index, 0
            # The pin asks on every scroll offset: a block's html is built only when its height
            # is not yet measured at this width, not on every frame that reads the height.
            height = self.measured_height((key, index), font, width,
                                          PreparedOnFill(partial(self.html, self.renderer, (block,), width, font)))
            if y < top + height or index == len(blocks) - 1:
                return index, max(0, int((y - top) // line))
            top += height
        return 0, 0

    def header_document(self, header: Divider, font: QFont, width: int) -> QTextDocument:
        """A message's header block laid out as its row lays it out at this width."""
        document = self.new_document(font, width)
        self.html(self.renderer, (header,), width, font).fill(document)
        return document

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # type: ignore[override]
        """A history row's style option is the view's own: the row's document draws its text,
        and the model answers no styling role. Qt's default reads the row's display text into
        the option on every paint and size, which built the plain text each time; the plain
        text is read only where it is drawn (`row_text`, while the row is being prepared)."""
        option.index = index

    def formatting(self, index: QModelIndex, font: QFont, width: int) -> RowFormatting:
        fragment = index.data(HistoryRows.FRAGMENT)
        return self.styled_formatting(self.fragment_key(fragment, font, width), fragment, font, width)

    def styled_formatting(self, key, fragment: HistoryFragment, font: QFont, width: int) -> RowFormatting:
        """The row's formatting under `key`; while a new look of a drawn row is still being
        prepared, the look it last showed. A sent message's receipt answers several times
        just after it lands (checking, then each recipient): each answer is a new key, and
        drawing the row as plain text until the answer was styled rewrapped it to another
        height and back, the message snapping in, out and in again."""
        formatting = self.keyed_formatting(key, fragment.clipboard_text, self.rendering(fragment, font, width))
        if isinstance(formatting, PlainRow):
            shown = self.last_shown.get(self.row_identity(key))
            if shown in self._prepared:
                return self._prepared[shown]
        return formatting

    @staticmethod
    def row_identity(key):
        """Which drawn row a preparation key is for, whatever look: the fragment, links, font
        and width, without how it is shown."""
        (fragment_key, _shown, _revision), *drawn = key
        return fragment_key, *drawn

    def _row_prepared(self, key, prepared: RowFormatting) -> None:
        super()._row_prepared(key, prepared)
        if key in self._prepared:
            self.last_shown[self.row_identity(key)] = key
        if len(self.last_shown) > 2 * self.MAX_PREPARED_ROWS:
            # Looks the prepared cache let go of name nothing to draw.
            self.last_shown = {row: shown for row, shown in self.last_shown.items() if shown in self._prepared}

    def is_prepared(self, key) -> bool:
        return key in self._prepared

    def adopt(self, key, formatting: RowFormatting) -> None:
        """A row's formatting prepared before the row was drawn takes its place in the cache, as
        one prepared on the pool does when it lands."""
        self._row_prepared(key, formatting)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        fragment = index.data(HistoryRows.FRAGMENT)
        opacity = self.view.arrival_opacity(fragment.key) if self.view.arrivals else None
        if opacity is None:
            self.fading.pop(fragment.key, None)
            super().paint(painter, option, index)
        else:
            painter.save()
            painter.setOpacity(opacity)
            painter.drawPixmap(option.rect.topLeft(), self.fading_picture(painter, option, index, fragment.key))
            painter.restore()
        self.view.row_painted(fragment, option.rect)

    def fading_picture(self, painter: QPainter, option, index, key) -> QPixmap:
        """A rising row drawn once into a picture, which each frame of its fade paints at that
        frame's opacity: its look does not change while it rises, and laying its rich text out
        and drawing every glyph again each frame was most of a burst's repaint on the phone
        (2026-11-18). A new width, height, pixel ratio or document draws it again."""
        ratio = painter.device().devicePixelRatioF()
        rect = option.rect
        local = QStyleOptionViewItem(option)
        local.rect = QRect(0, 0, rect.width(), rect.height())
        look = (rect.width(), rect.height(), ratio, id(self.painted_document(index, local)))
        kept = self.fading.get(key)
        if kept is not None and kept[0] == look:
            return kept[1]
        picture = QPixmap(max(1, round(rect.width() * ratio)), max(1, round(rect.height() * ratio)))
        picture.setDevicePixelRatio(ratio)
        picture.fill(Qt.GlobalColor.transparent)
        drawing = QPainter(picture)
        super().paint(drawing, local, index)
        drawing.end()
        self.fading[key] = (look, picture)
        return picture


@dataclass(frozen=True)
class PreparedOnFill(RowFormatting):
    """A row's formatting prepared only when a measurement needs it: one that answers from its
    cache never resolves it, so it never pays for the preparation. What it resolves to may be
    the row's pending stand-in, which the measurement estimates instead of laying out."""

    prepare: Callable[[], RowFormatting]

    def resolved(self) -> RowFormatting:
        return self.prepare().resolved()

    def fill(self, document: QTextDocument) -> None:
        self.prepare().fill(document)


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

    # A restricted category selection is drawn from the pages already held: each page shows
    # only its selected categories' rows, so no projection is read or mounted.
    restricted_filter = DrawnFilter

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
        # A failed read raises through the loop's exception handler, never into a dropped task.
        self.run_worker(partial(window.acquire_links, app)).add_done_callback(
            lambda task: task.cancelled() or task.result())

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
        """Styled before drawn, as the shared pager asks (`ReaderPage.acquire`): each shown
        fragment's row is formatted at the window's width and font before the pager publishes
        it. A row first drawn plain and then rewrapped when its styled formatting landed moved
        every row under it, which on the phone read as a message snapping in, out and back."""
        window = self.window
        rows, font, width = window.rows, window.font(), window.viewport_width()
        if width <= 0:
            return  # Not laid out yet: the first paint prepares them at the real width.
        jobs = [(key, rows.rendering(fragment, font, width)) for fragment in fragments
                if fragment.shown_in(selected)
                and not rows.is_prepared(key := rows.fragment_key(fragment, font, width))]
        if not jobs:
            return
        prepared = await asyncio.to_thread(lambda: [(key, prepare()) for key, prepare in jobs])
        if current():
            for key, formatting in prepared:
                rows.adopt(key, formatting)

    def hold_arrival(self, arrivals: tuple[HistoryFragment, ...]) -> None:
        """Qt holds no rows below a following reader: arrivals rise where `repaint` names them."""

    async def _show(self, changes: list[tuple[HistoryFragment, Shown]]) -> None:
        """A status change repaints only the rows it changed. A row's cache key carries how
        its fragment is shown, so the repaint asks the delegate for the new look, which keeps
        drawing the last one until it is prepared, and that arrival lays the rows out
        (`RowDocumentDelegate._row_prepared`). Laying every row out here on each receipt
        update cost the whole history's measurement while the new looks were not even ready."""
        changed = tuple(fragment for fragment, shown in changes if fragment.request_show(shown))
        if changed:
            self.repaint(continuing=changed)

    def repaint(self, fragments: tuple[HistoryFragment, ...] = (), *, continuing=()) -> None:
        """Repaint only the rows the pager named. The shared contract already says which
        fragments changed; dropping that and calling viewport().update() repaints every
        visible row on every clock tick, so the message header flickered under scroll."""
        window = self.window
        model_rows = window.model_rows
        if fragments and window.isVisible():
            # Where Textual's `repaint` starts `ARRIVAL` (`EffectPhase.on_new_arrival`), on every
            # publish path: an edge extended under the reader, or a newest page replacing the source.
            window.arrive(tuple(fragment.key for fragment in fragments))
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


class QtWireHistory(AwaitsFirstPage, QtConversationHistory):
    """A channel or direct conversation's history, as Textual's `WireHistory`: until its
    first page is drawn the reader is told it is loading, floating over the window so
    nothing moves when it goes."""

    def __init__(self, window: QtHistoryWindow, view, app) -> None:
        super().__init__(window, view, app)
        self.waiting = QtFloatLayer(app.theme.color_scheme, app.renderer, window)
        QTimer.singleShot(int(self.waiting.pending_delay * 1000), self.waiting, self.show_first_page)

    def show_first_page(self) -> None:
        if self.undrawn:
            self.waiting.show_pending(self.first_page)

    def first_page_drawn(self) -> None:
        self.waiting.clear_pending(self.first_page)


class QtHistoryNotifications(OneHistoryNotifications):
    """Every Qt view that draws a `QtConversationHistory` (a wire tab, a mailbox, an ACP
    transcript) on the Qt event loop, so a sent message's status and "N read" line resolve."""

    notification_work = NoTask()

    def report_queue_evidence(self) -> None:
        """New queue evidence repaints the composer's queue rows, as Textual's
        `Conversation.queue_evidence_changed` does through its submissions."""
        self.submissions.publish_pending()

    def run_notification_work(self, work: Awaitable[None]) -> None:
        self.notification_work.cancel()
        self.notification_work = asyncio.ensure_future(work)

    def check_notifications_after_refresh(self) -> None:
        QTimer.singleShot(0, self.check_notifications)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self.check_notifications)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        super().hideEvent(event)
        self.app.coordination_access.stop_notifications(self)


class QtLinkPreview(MroProjection[None]):
    """A tapped project link in Qt: an address opens in the system browser; a file has no
    Qt preview view, and the reader is told so."""

    @handles(ExternalProjectLink)
    def address(self, link: ExternalProjectLink, window: QtHistoryWindow) -> None:
        QDesktopServices.openUrl(QUrl(link.href))

    @handles(ProjectFileLink)
    def file(self, link: ProjectFileLink, window: QtHistoryWindow) -> None:
        window.warn_link(f"{link.href} has no Qt preview view.")


QT_LINK_PREVIEW = QtLinkPreview()


@dataclass(frozen=True)
class QtTopRow(TopPage):
    """No row under a Qt window's top edge: Qt keeps its reader by scroll row."""

    def reader_position(self, window: QtHistoryWindow) -> RowPosition:
        return RowPosition(window.scroll_y)


@dataclass(frozen=True)
class QtRowUnderTop(QtTopRow):
    """A fragment's row holds the top edge; its fragment decides the pinned header."""

    under: FragmentRowUnderTop

    def pinned_header(self, window: QtHistoryWindow) -> PinnedHeader:
        return self.under.pinned_header()


class QtStickyHeader(HeaderPin, QWidget):
    """`HeaderPin` floated over the history's top edge, drawn by the history rows' own
    delegate. A child of the window, not the viewport, as `QtJumpBar` is: the viewport's
    children scroll with its contents, and QScroller's grab on the viewport would take its
    taps. Opaque, so the row it covers does not show through, as Textual's overlay is. Taps
    pass through to the row beneath, except on a burst's stacked headers, which open their
    messages."""

    def __init__(self, window: QtHistoryWindow) -> None:
        super().__init__(window)
        # It fills its rectangle (paintEvent), so the rows it covers are not painted under it: a
        # glide repaints only the band it floats over (`VirtualRowView.scrollContentsBy`).
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.history_window = window
        self.documents: tuple[QTextDocument, ...] = ()
        self.drawn: tuple = ()
        # Each pinned header's laid-out document, while the pin's width, font, link context and
        # renderer stay the same.
        self.laid_out: dict[Divider, QTextDocument] = {}
        self.layout_context: tuple = ()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def draw_pinned(self, headers: tuple[Divider, ...], x: int, width: int) -> None:
        """Every scroll offset pins; only different headers, column, font, link context or
        renderer (a theme) lay anything out again, and then only the headers not already laid
        out: a burst's stack changes as each head glides past the top, and laying every stacked
        header out again from its html (its theme's colours resolved span by span) was a third
        of the phone's UI thread during a burst (2026-11-18)."""
        window = self.history_window
        # Taps reach the stacked headers whenever a stack is pinned, even when its drawing is
        # unchanged: equal headers can stand for other messages (one sender, one second).
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not self.stacked.keys)
        context = (width, window.font().key(), window.rows.links_revision, id(window.rows.renderer))
        drawn = (headers, x, context)
        if drawn == self.drawn:
            return
        self.drawn = drawn
        kept = self.laid_out if context == self.layout_context else {}
        self.layout_context = context
        self.laid_out = {header: kept.get(header) or window.rows.header_document(header, window.font(), width)
                         for header in headers}
        self.documents = tuple(self.laid_out[header] for header in headers)
        self.resize(width, sum(int(document.size().height()) for document in self.documents))
        self.move(window.viewport().mapTo(window, QPoint(x, 0)))
        self.raise_()
        self.update()

    def show_pin(self, shown: bool) -> None:
        if self.isVisible() != shown:
            self.setVisible(shown)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        """A tap on a stacked header opens its message; the top row's own passes through."""
        y, top = event.position().y(), 0
        for index, document in enumerate(self.documents):
            top += int(document.size().height())
            if y < top:
                if self.history_window.open_pinned(index):
                    event.accept()
                    return
                break
        event.ignore()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if not self.documents:
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(BackgroundColour.rgb(self.history_window.rows.renderer.scheme).hex))
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette = self.palette()
        for document in self.documents:
            document.documentLayout().draw(painter, context)
            painter.translate(0, document.size().height())
        painter.end()


class QtJumpBar(LatestJumpBar, QPushButton):
    """The shared `LatestJumpBar` as a floating button over the history's viewport; clicking
    it jumps the window back to the latest row. Text and border take PrimaryColour, as
    Textual's `BackToBottom` takes `PrimaryText`."""

    def __init__(self, parent: QWidget, renderer: QtLineRenderer) -> None:
        super().__init__(self.label, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        renderer.themed(self, partial(self.paint_colours, renderer))
        self.hide()

    def paint_colours(self, renderer: QtLineRenderer) -> None:
        scheme = renderer.scheme
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

    @property
    def jump_shown(self) -> bool:
        return self.isVisible()

    def show_jump(self, shown: bool) -> None:
        self.setVisible(shown)


class QtHistoryWindow(FollowsTail, ReaderWindow, WorkspaceHosted, VirtualRowView,
                      ReaderPlacement, PagingWindow, OpensLineLinks, PinsMessageHeader):
    """The reader window of one Qt conversation: pyqt-reactive's virtual rows of the
    history's shown fragments, scrolled by pixel. It answers the shared pager's window
    contract: reaching the top reads older pages, the bottom newer ones, End and the
    reader at the end follow the newest row, and rows that arrive or are evicted above the
    reader leave the row they are reading where it was."""

    # Emitted when the viewer right-clicks or long-presses a message row; carries the
    # fragment under that point. Consumers (ConversationView) build a block menu from
    # the shared `MenuCommand` family and offer it through the host's offer panel.
    #: The row's fragment, and where it was pressed in the window's coordinates.
    block_menu_requested = Signal(object, QPoint, name="blockMenuRequested")

    history: QtConversationHistory
    # `scroll_revision` + `history_change` are declared on JumpsToLatest (shared with Textual).

    @property
    def is_attached(self) -> bool:
        """Whether the window is still in its view, as Textual's `Widget.is_attached`
        answers for `HistoryWindow`: `BoundView` publishes only into an attached window."""
        return shiboken6.isValid(self) and self.parent() is not None

    @property
    def configuration_state(self):
        """The settings of the view this window reads in (its override, else the app's)."""
        return self._scope.configuration_state

    @property
    def screen(self) -> WorkspaceFrame:
        """Qt's workspace frame is the top-level `QtToadApp` (which inherits
        `QtWorkspaceFrame`). Qt widgets reach it through `window()`, not through a
        Textual `Widget.screen` chain, so `WorkspaceHosted`'s `super().screen` is
        replaced here."""
        return self.window()

    def __init__(self, renderer: QtLineRenderer, scope, parent: QWidget | None = None) -> None:
        super().__init__(HistoryRowDelegate(renderer), parent)
        self._scope = scope
        # Rows draw by the app's renderer: a new scheme or diff marks draws them again.
        renderer.follows_theme(self, self.restyle_rows)
        self.model_rows = HistoryRows()
        self.draft: tuple[HistoryFragment, ...] = ()  # after the pages, as Textual's `CliDraft`
        self.live_blocks: list[QtLiveBlock] = []  # after the draft, as Textual's live blocks
        self.setModel(self.model_rows)
        self.histories: WeakSet = WeakSet()
        self.history_lock = asyncio.Lock()
        # The view's settings are read once it is shown (`QtViewSettings`): a thread view
        # is built before its tab is listed, which names the settings it reads.
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
        # Touch-down scroll throttle: QScroller emits valueChanged at touch rate
        # (90Hz on Pixel 8a, up to 240Hz on higher-rate panels) while the finger
        # is dragging. The post-scroll chain (`respond_to_scroll` →
        # `lookahead.observe` + `request_preparation` + `tail_follow_changed` +
        # `_after_jump_bar_change → refresh_bindings`) is sized for frame-rate
        # inertia ticks, not touch rate. Track QScroller's Dragging state and
        # skip `respond_to_scroll` while the finger is down; `_on_scroller_state`
        # fires it once when the drag ends (and Scrolling/Inactive ticks still
        # run it as before). Leaves at_end/follows_tail transitions in `scrolled`
        # alone — those are cheap and only do work when the state actually flips.
        # A finger pulling past an edge is the one drag that asks for rows at once
        # (`overshot`): no scroll travel measures it.
        self._scroller_dragging = False
        self._overshoot = 0.0
        _scroller = QScroller.scroller(self.viewport())
        _scroller.stateChanged.connect(self._on_scroller_state)
        # The floating "jump to latest" button: child of the window (not the viewport), so
        # QScroller's gesture grab on the viewport (from FingerScrolling) can't swallow the
        # tap and prevent `clicked` from firing on Android. Positioned over the viewport
        # by `_place_jump_bar`. Show/hide is driven by `tail_follow_changed` from `scrolled`.
        self.jump_bar = QtJumpBar(self, renderer)
        self.jump_bar.clicked.connect(self.jump_to_latest)
        self.sticky_header = QtStickyHeader(self)
        # Arriving rows fading in, and the glide down to them (`arrive`).
        self.arrivals: list[ArrivalFade] = []
        self.glide: ArrivalGlide | None = None
        # A tapped message's head gliding to the top (`reveal_head_at`).
        self.head_reveal: HeadReveal | None = None
        # A press that stops a fling is not a tap on a row (Android's lists do the same).
        self._fling_stopped = False
        # Rows that arrived at the end the reader follows, not yet glided to (`glide_to_end`).
        self._arrived: tuple = ()
        # A press makes its row Qt's current index, and autoScroll would then scroll that
        # row into view at once (QAbstractItemView.currentChanged → scrollTo): a jump on
        # every tap, and one that fights a drag starting on a row. A tap's reveal is the
        # explicit `reveal_head_at`.
        self.setAutoScroll(False)
        self.viewport().installEventFilter(self)
        # Block menu: a right-click, or a held finger (`FingerPress` delivers it as one), on a
        # message row emits `block_menu_requested` with the row's fragment. ConversationView
        # mounts the handler and runs the resulting commands.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_block_menu_at)
        # A tap on a link opens it, and a tap on a message reveals its head, in place of the
        # row's own click (`FingerPress.tapped`).
        FingerPress.install(QApplication.instance()).tapped.connect(self._row_tapped)
        # Reader keys (ctrl+d / ctrl+u / shift+g) come from the `ReaderAction` family
        # declared in `src/toad/reader_actions.py`. Both backends drive from that one
        # declaration: Textual through the Action/BindingsMap path, Qt through
        # `ActionKeys.bind_family`, a QShortcut per member answering its keys in the current
        # key mode and keymap, firing `apply(self)` (which calls `action_page_down` /
        # `action_page_up` / `jump_to_latest` on this window).
        self._reader_shortcuts = scope.app.action_keys.bind_family(self, ReaderAction, self)

    @property
    def animation_clock(self):
        return self._scope.app.animation_clock

    def arrive(self, keys: tuple) -> None:
        """Rows `keys` just arrived: they fade in row after row, and a reader following the
        end glides down to them rather than jumping their height (`glide_to_end`)."""
        if not (keys and self.animation_clock.enabled):
            return
        if not (self.draft or self.live_blocks):
            # Rows committed while a draft or live block stood in for them were already seen:
            # they replace it in place (`publish_snapshot` clears the draft in the same turn).
            self.arrivals.append(ArrivalFade(self, keys))
        if self.follows_tail:
            self._arrived += keys
            self.glide_to_end()

    def glide_to_end(self) -> bool:
        """Glide to the end from where it was before the arrived rows, once they are laid out
        (a page published after `repaint` lays them out in `keep_reader`). A glide already
        running turns toward the new end from where it is, so it never lands by jumping."""
        model_rows = self.model_rows
        rows = [row for key in self._arrived if (row := model_rows.row_of(key)) >= 0]
        if not rows:
            return False
        self._arrived = ()
        self.executeDelayedItemsLayout()
        tail = self.tail_scroll_y
        start = max(0, tail - sum(self.visualRect(model_rows.index(row, 0)).height() for row in rows))
        if self.glide is not None:
            self.glide.animation.stop()
            start = max(start, self.glide.at)
        with self.layout_scroll():
            self.scroll_y = min(start, tail)
            self.glide = ArrivalGlide(self, self.scroll_y)
        return True

    def gliding_to_end(self) -> bool:
        """Whether a glide owns the way to the end, so whatever follows the end for a following
        reader (`anchor`, `check_follow`, `keep_reader`) leaves it to the glide, which lands there.
        Rows that arrived start their glide here once laid out; arrivals this view never draws
        are let go, so following the end is never held for them."""
        if self._arrived and not self.glide_to_end():
            self._arrived = ()
        return self.glide is not None

    def arrival_landed(self, fade: ArrivalFade) -> None:
        if fade in self.arrivals:
            self.arrivals.remove(fade)
        for key in fade.positions:
            self.rows.fading.pop(key, None)

    def arrival_opacity(self, key) -> float | None:
        """How far the row `key` has risen, while it is still rising."""
        for fade in self.arrivals:
            if (opacity := fade.opacity(key)) is not None:
                return opacity
        return None

    async def acquire_links(self, app) -> None:
        """The names this conversation's bodies link through; the rows draw again with them."""
        self.rows.link(await LinkContext.observed(app.renderer.links.root, app.coordination_access))
        self.show_pages()

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
            if event.type() == QEvent.Type.Resize:
                if self.jump_bar.isVisible():
                    self._place_jump_bar()
                self.repin_header()
            elif event.type() == QEvent.Type.Scroll:
                self.overshot(event.overshootDistance().y())
        return super().eventFilter(obj, event)

    def _row_tapped(self, press: Press) -> None:
        """A tap on a row: a link drawn there opens; otherwise a message whose head is above
        the viewport glides its head to the top (`reveal_head_at`). Either way the row
        doesn't also take the tap. A tap on rows still moving (a fling, a reveal) only stops
        them, as Android's lists do: the reader was catching the rows, not choosing one."""
        viewport = self.viewport()
        if not press.within(viewport):
            return
        stopped, self._fling_stopped = self._fling_stopped, False
        scroller = QScroller.scroller(viewport)
        if stopped or scroller.state() == QScroller.State.Scrolling:
            scroller.stop()
            press.claim()
            return
        point = press.at(viewport)
        href = self.anchor_at(point)
        if href:
            press.claim()
            self.open_link(href)
        elif self.reveal_head_at(point):
            press.claim()

    def anchor_at(self, point: QPoint) -> str:
        """The href of the link drawn at `point` (viewport coordinates), or "" over plain text."""
        index = self.indexAt(point)
        if not index.isValid():
            return ""
        rect = self.visualRect(index)
        document = self.rows.row_document(index, self.font(), rect.width())
        return document.documentLayout().anchorAt(QPointF(point - rect.topLeft()))

    # The shared link handlers (`OpensLineLinks`) open through this app and warn on this view.

    @property
    def app(self):
        return self.history.app

    def select_target(self, target: NavigationTarget) -> None:
        self.app.open_target(target)

    def select_historical(self, name: str, source: str) -> None:
        self.warn_link(f"@{name}'s recorded identity in {source} has no Qt view.")

    def preview_link(self, link: ProjectLink) -> None:
        QT_LINK_PREVIEW.project_value(link, self)

    def warn_link(self, text: str) -> None:
        self.history.view.flash_error(text)

    def run_link(self, work: Callable[[], Awaitable[None]]) -> None:
        self.history.run_worker(work)

    def show_file(self, path: Path) -> None:
        """A kept file opens in the application the system names for it."""
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.warn_link(f"No application opens {path.name}; it is kept at {path}.")

    @handles(FragmentDetails)
    def toggle_details(self, link: FragmentDetails) -> None:
        """A tap on a ▶ row opens or closes that fragment's details, as Textual's page does."""
        for fragment in self.model_rows.fragments:
            if fragment.key == link.key:
                self.history.run_worker(lambda: self.history._show([(fragment, fragment.shown.toggled())]))
                return

    def _emit_block_menu_at(self, point: QPoint) -> None:
        """Right-click or long-press at ``point`` (viewport coordinates): emit the
        fragment under that row so ConversationView can open the block menu."""
        index = self.indexAt(point)
        if not index.isValid():
            return
        fragment = self.model_rows.data(index, HistoryRows.FRAGMENT)
        if fragment is None:
            return
        self.block_menu_requested.emit(fragment, self.viewport().mapTo(self.window(), point))

    # Geometry, in pixels

    @property
    def scroll_y(self) -> float:
        return self._safe_qt_read(lambda: self.verticalScrollBar().value(), 0.0)

    @scroll_y.setter
    def scroll_y(self, value: float) -> None:
        self._safe_qt_read(lambda: self.verticalScrollBar().setValue(int(value)), None)

    @property
    def scroll_target_y(self) -> float:
        """Qt scrolls at once: its target is where it is."""
        return self.scroll_y

    @property
    def max_scroll_y(self) -> float:
        return self._safe_qt_read(lambda: self.verticalScrollBar().maximum(), 0.0)

    @property
    def tail_scroll_y(self) -> float:
        return self.max_scroll_y

    def _safe_qt_read(self, read, default):
        """Any attribute read that ultimately touches the shiboken-backed Qt
        widget raises RuntimeError ("Internal C++ object (...) already
        deleted") once the view has been torn down. Late pager tasks still
        ask us for geometry, visibility and fragment heights after the view
        closes; those should answer a benign default so the publish
        short-circuits instead of flooding logcat. A live widget returns its
        real value — same code path as before for all other callers."""
        try:
            return read()
        except RuntimeError:
            return default

    def _viewport_height_safe(self) -> int:
        return self._safe_qt_read(lambda: self.viewport().height(), 0)

    @property
    def viewport_rows(self) -> int:
        return self._viewport_height_safe()

    @property
    def content_rows(self) -> int:
        return self._viewport_height_safe()

    @property
    def unfilled_rows(self) -> int:
        height = self._viewport_height_safe()
        if height == 0:
            return 0
        rows = self.model_rows.rowCount()
        if not rows:
            return height
        return max(0, height - self.visualRect(self.model_rows.index(rows - 1, 0)).bottom())

    @property
    def animated_travel(self) -> float:
        return 0

    @property
    def presenting(self) -> bool:
        return self._safe_qt_read(lambda: self.isVisible(), False)

    def runway(self, history) -> OffScreenRunway:
        if not self.presenting:
            return OffScreenRunway()
        return Runway(int(self.scroll_y), int(self.max_scroll_y - self.scroll_y))

    def fragment_height(self, fragment: HistoryFragment) -> int:
        return self._safe_qt_read(
            lambda: self.rows.fragment_height(fragment, self.font(), self.viewport_width()),
            0,
        )

    def visible_fragments(self) -> tuple[HistoryFragment, ...]:
        try:
            area = self.viewport().rect()
            top, bottom = self.indexAt(area.topLeft()), self.indexAt(area.bottomLeft())
        except RuntimeError:
            return ()
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

    def apply_anchor(self, anchor: bool) -> None:
        self._anchored = anchor
        if anchor:
            self.reader_position = self.reader_position.joined_tail()
            # A publication restoring a following reader (`FollowTailCommit.restore_reader`)
            # glides to rows that just arrived; a running glide lands on the end itself.
            if self.gliding_to_end():
                return
            try:
                with self.layout_scroll():
                    self.follow_end()
            except RuntimeError:
                # View torn down between scheduling and anchor() running —
                # scrollToBottom() inside follow_end hits the dead C++ widget.
                # Nothing to scroll; the user already closed the view.
                return
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
        if not self.follows_tail or self.gliding_to_end():
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
        stays on the row it was reading, or at the end when following it. If the widget
        has been torn down, the Qt reads raise RuntimeError; yield as a no-op so the
        page-change work still runs but the reader-restore is skipped on a dead view."""
        try:
            key, offset = self.reader_place()
        except RuntimeError:
            yield
            return
        try:
            yield
        finally:
            self.show_pages()
            self.keep_reader(key, offset)

    def reader_place(self) -> tuple[object, int]:
        """The viewport's top row and its offset, where a relayout puts the reader back."""
        top = self.indexAt(self.viewport().rect().topLeft())
        if not top.isValid():
            return None, 0
        return top.data(HistoryRows.FRAGMENT).key, self.visualRect(top).top()

    def show_pages(self) -> None:
        """Read the rows again from the history's shown pages, then the draft after them."""
        history = self.history
        self.model_rows.show(tuple(fragment for page in history.pages if page.display
                                   for fragment in page.shown_fragments) + self.draft
                             + tuple(block.fragment() for block in self.live_blocks))
        self.doItemsLayout()
        self.repin_header()

    def show_draft(self, fragments: tuple[HistoryFragment, ...]) -> None:
        """Core's CLI draft as rows after the history (none clears it); the reader keeps their place."""
        if not fragments and not self.draft:
            return
        key, offset = self.reader_place()
        self.draft = fragments
        self.show_pages()
        self.keep_reader(key, offset)

    def show_live(self, block: QtLiveBlock) -> None:
        """A turn's live block as a row after the history and the draft."""
        self.live_blocks.append(block)
        self.live_changed()

    def live_changed(self) -> None:
        """A live block grew or left: read the rows again, following the end if the reader was."""
        key, offset = self.reader_place()
        self.show_pages()
        self.keep_reader(key, offset)

    def drop_live(self, block: QtLiveBlock) -> None:
        if block in self.live_blocks:
            self.live_blocks.remove(block)
            self.live_changed()

    def committed_pages_changed(self) -> None:
        """Saved rows arrived: they now carry the output of every finished live block."""
        self.live_blocks = [block for block in self.live_blocks if not block.finished]
        self.show_pages()

    def restyle_rows(self) -> None:
        self.rows.restyle()
        self.rows_changed()

    def rows_changed(self) -> None:
        """Prepared rows changed height: lay them out again, keeping the reader's row.
        If the widget has been torn down, Qt reads raise RuntimeError; skip the
        reader-restore and the viewport update — there is no viewer to serve."""
        try:
            key, offset = self.reader_place()
            self.doItemsLayout()
            self.keep_reader(key, offset)
            self.repin_header()
            self.viewport().update()
        except RuntimeError:
            return

    def keep_reader(self, key, offset: int) -> None:
        """After a layout: at the end when following it, else the row `key` back at `offset`."""
        if self.follows_tail and self.gliding_to_end():
            return
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
        from QScroller don't restart the settle timer during Android touch scrolls.

        Touch-down throttle: while QScroller is in Dragging state the finger is
        tracking the viewport and valueChanged fires at touch rate. The
        post-scroll chain is deferred until drag ends; `_on_scroller_state`
        fires `respond_to_scroll` once on the transition out of Dragging. The
        at_end/follows_tail transitions here stay — they're cheap state flips
        and consumers (jump bar + anchor) need to see them during drag."""
        # Every offset pins, the window's own as well as the reader's: a glide down into a tall
        # arrival moves the top row into it, and returning before this left the arrival's header
        # unpinned until the reader scrolled (Tristan, Android, 2026-11-18).
        self.repin_header()
        if self._restoring:
            return
        if self.at_end and not self.follows_tail:
            self.anchor()
        elif not self.at_end and self.follows_tail:
            self.release_anchor()
        elif not self.follows_tail:
            self.reader_position = RowPosition(value)
        if self._scroller_dragging:
            return
        self.respond_to_scroll(value)

    _flinging = False

    def reveal_head_at(self, point: QPoint) -> bool:
        """A tap at ``point`` (viewport coordinates): when the tapped message's head is above
        the viewport, glide it up to the top. A head already on screen stays where it is,
        as in Textual (`reveal_message_head`). Whether it moved the rows."""
        index = self.indexAt(point)
        if not index.isValid():
            return False
        model_rows = self.model_rows
        head = index.data(HistoryRows.FRAGMENT).message_head(model_rows.fragments)
        row = model_rows.row_of(head.key)
        if row < 0:
            return False
        top = self.visualRect(model_rows.index(row, 0)).top()
        if top >= 0:
            return False
        if self.head_reveal is not None:
            self.head_reveal.cancel()
        start = self.scroll_y
        self.head_reveal = HeadReveal(self, start, max(0.0, start + top))
        return True

    def _on_scroller_state(self, state) -> None:
        """On the drag → not-drag edge, answer the drag's last position at once. A finger
        taking the rows stops a head reveal; a press that stops a fling is remembered, so
        its release is not read as a tap on a row."""
        was_dragging = self._scroller_dragging
        self._scroller_dragging = (state == QScroller.State.Dragging)
        if state in (QScroller.State.Pressed, QScroller.State.Dragging) and self.head_reveal is not None:
            self.head_reveal.cancel()
        if state == QScroller.State.Pressed:
            self._fling_stopped = self._flinging
        self._flinging = state == QScroller.State.Scrolling
        if state == QScroller.State.Inactive:
            self._overshoot = 0.0
        if was_dragging and not self._scroller_dragging:
            self.respond_to_scroll(self.verticalScrollBar().value())

    def overshot(self, distance: float) -> None:
        """A finger (or a fling's momentum) pulled the rows past an edge: the content can't
        move, so no scroll travel is measured, yet the reader asked for more. Each pull
        further past it asks the shared lookahead for that edge's next page, as a wheel
        step at an edge does (`wheelEvent`)."""
        further = abs(distance) - abs(self._overshoot)
        self._overshoot = distance
        if distance and further > 0:
            rows = further / self._font_line_spacing()
            self.lookahead.request_boundary(-rows if distance < 0 else rows)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """A wheel at an edge with nowhere left to scroll still asks for the next page."""
        rows = -event.angleDelta().y() / 120 * self._font_line_spacing() * QApplication.wheelScrollLines()
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
        """The row under the viewport's top edge, with the block and line of its fragment
        there: Qt measures that by pixel, where Textual counts cells."""
        try:
            top = self.indexAt(self.viewport().rect().topLeft())
        except RuntimeError:
            return QtTopRow()
        if not top.isValid():
            return QtTopRow()
        rect = self.visualRect(top)
        fragment = top.data(HistoryRows.FRAGMENT)
        block, row = self.rows.block_row(fragment, self.font(), rect.width(), -rect.top())
        return QtRowUnderTop(FragmentRowUnderTop(fragment, block, row, rect.left(), rect.width()))

    def live_message_header(self) -> PinnedHeader:
        """Qt draws no live blocks: the draft is rows, so a row under the top edge pins."""
        return PinnedHeader((), 0, 0)

    def message_top(self, key) -> float | None:
        """Qt keeps rows by pixel: the row's top under the viewport, plus the offset."""
        model_rows = self.model_rows
        row = model_rows.row_of(key)
        if row < 0:
            return None
        return self.scroll_y + self.visualRect(model_rows.index(row, 0)).top()

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
