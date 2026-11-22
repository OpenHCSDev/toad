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
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterator, Hashable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import cached_property, partial
from math import copysign
from pathlib import Path
from typing import ClassVar
from weakref import WeakSet

from metaclass_registry.mro_dispatch import handles
from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPoint, QPointF, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QDesktopServices, QFont, QFontMetrics, QFontMetricsF, QPainter, QPixmap, QScrollEvent, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QPushButton, QScroller, QScrollerProperties, QStyleOptionViewItem, QWidget,
)
from pyqt_reactive.widgets.virtual_rows import (
    HtmlRow, RowDocumentDelegate, RowFormatting, RowPreparer, VirtualRowView,
)
from toad.client.pending import AwaitsFirstPage
from toad.client.view_settings import SettingsReading
from toad.qt.finger_press import FingerPress, Press
from toad.client.fragments import FragmentDetails, HistoryFragment, Shown
from toad.core.events import CoreEventStream
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
    NativePresentation,
    OffScreenRunway,
    PagingWindow,
    PresentationBudget,
    ReaderPlacement,
    Runway,
)
from toad.client.line_blocks import BlockPreparation, Divider
from toad.client.history_changes import FragmentRowUnderTop, HeaderPin, PinnedHeader, PinsMessageHeader, TopPage
from toad.client.history_preparation import HistorySourceSnapshot
from toad.client.history_state import LiveTranscript
from toad.client.prepared_pages import (
    ClosedHistory, HoldsRows, MeasuresFragments, PreparedTranscriptPage, RowsAsked,
)
from toad.client.reader_position import (
    FragmentLocation, FragmentPosition, ReaderPage, ReaderPosition, RowPosition, TailPosition,
    UnloadedFragment,
)
from toad.history_jump import FollowsTail, JumpsToLatest, ReaderWindow
from toad.widget_view import WorkspaceHosted
from toad.workspace_frame import WorkspaceFrame
from toad.markdown_links import LinkContext
from toad.qt.float_layer import QtFloatLayer
from toad.qt.lines import QtLineRenderer
from toad.patch import PREFORMATTED, DiffSettings
from toad.reader_actions import ReaderAction
from toad.view_actions import LatestJumpBar, ShowsLatestJumpBar
from toad.qt.widget_animation import WidgetAnimation, frame_interval
from toad.qt.transcript_fragments import (
    QT_FRAGMENT_CLASSES,
    QtContextTranscriptFragment,
    QtMembershipFragment,
    QtMessageFragment,
    QtSentMessageFragment,
    QtToolTranscriptFragment,
    QtWireFragment,
)
from toad.render_backend import Renderer, RenderTask
from toad.transcript_filter import DrawnFilter, FilterState
from toad.frame_presentation import ARRIVAL
from toad.motion import FOLLOW_ARRIVAL, HEAD_REVEAL, TransitionTarget
from ui_theme.scheme import BackgroundColour, ColourScheme, ForegroundColour, PrimaryColour, SurfaceHoverColour

if TYPE_CHECKING:
    from toad.qt.live_turn import QtLiveBlock


class QtPage(ReaderPage):
    """One prepared page, drawn as the rows of the fragments in its range that its history
    shows. The rows themselves live in the window's model, read from the pages."""

    arrivals: frozenset = frozenset()
    rows_measured = True

    def __init__(self, prepared: PreparedTranscriptPage, history: QtConversationHistory) -> None:
        self.prepared = prepared
        self.history = history
        self.display = False
        self._shown: tuple[HistoryFragment, ...] | None = None
        prepared.configure(batch_size=PresentationBudget.batch_items)

    @classmethod
    def drawn_for(cls, owner: QtConversationHistory, prepared: PreparedTranscriptPage) -> QtPage:
        return cls(prepared, owner)

    @property
    def shown_fragments(self) -> tuple[HistoryFragment, ...]:
        shown = self._shown
        if shown is None:
            selected = self.history.selected_categories
            shown = tuple(fragment for fragment in self.prepared.fragments_in_range if fragment.shown_in(selected))
            self._shown = shown
        return shown

    @property
    def line_count(self) -> int:
        """The pixels this page's rows take in the window."""
        return sum(self.history.fragment_height(fragment) for fragment in self.shown_fragments)

    def range_changed(self) -> None:
        self._shown = None
        self.history.window.committed_pages_changed()

    def set_categories(self, selected) -> None:
        """A filter change: the history's selection decides which rows show."""
        self._shown = None
        self.range_changed()

    def remove(self) -> None:
        """An evicted page's rows go with the next row reset."""
        self._shown = None
        self.display = False

    def drawn_height(self, fragment: HistoryFragment) -> int:
        return self.history.fragment_height(fragment)

    @property
    def visible_categories(self):
        """The categories this page shows: Qt filters a history's pages together."""
        return self.history.selected_categories

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
        """The rows the pages show now, told to the view as what changed: the rows of pages
        that did not change are the same fragment objects, so the unchanged rows before and
        after the change are found by identity, and only the rows between them are inserted,
        removed or changed. The view keeps every other row's measured height
        (`RowDocumentDelegate` row sizes); a reset made it measure the whole history again
        on every arrival (Tristan, Pixel 8a, bursts at 30 ms a frame, 2026-11-18)."""
        old = self.fragments
        same = min(len(old), len(fragments))
        head = next((row for row in range(same) if old[row] is not fragments[row]), same)
        tail = 0
        while tail < same - head and old[-1 - tail] is fragments[-1 - tail]:
            tail += 1
        removed, added = len(old) - head - tail, len(fragments) - head - tail
        if removed == added:
            self._set(fragments, head)
            if added:
                self.dataChanged.emit(self.index(head, 0), self.index(head + added - 1, 0))
            return
        # The first `changed` rows of the change keep their old content through the removal
        # and the insertion (rows an insert or removal does not name must not change in it),
        # then change in place, told as a data change.
        changed = min(removed, added)
        kept, end = old[:head + changed], old[len(old) - tail:]
        if removed > changed:
            self.beginRemoveRows(QModelIndex(), head + changed, head + removed - 1)
            self._set(kept + end, head + changed)
            self.endRemoveRows()
        if added > changed:
            self.beginInsertRows(QModelIndex(), head + changed, head + added - 1)
            self._set(kept + fragments[head + changed:head + added] + end, head + changed)
            self.endInsertRows()
        self._set(fragments, head)
        if changed:
            self.dataChanged.emit(self.index(head, 0), self.index(head + changed - 1, 0))

    def _set(self, fragments: tuple[HistoryFragment, ...], first: int) -> None:
        """Hold these rows. Every row a key names is kept with the rows (a lookup is asked per
        changed row on each receipt update, arrival, glide and reader restore); rows before
        `first` did not move, so a change at the end indexes only the rows after it."""
        if fragments is self.fragments:
            return
        rows = self._rows if first else {}
        if first:
            for key in [key for key, row in rows.items() if row >= first]:
                del rows[key]
        for row in range(first, len(fragments)):
            rows.setdefault(fragments[row].key, row)
        self.fragments = fragments
        self._rows = rows

    def row_of(self, key) -> int:
        return self._rows.get(key, -1)

    def changed(self, fragments: tuple[HistoryFragment, ...]) -> None:
        """These rows' fragments now show differently (`request_show` changes a fragment in
        place, so `show` sees the same object): each is told to the view as a data change,
        which drops its kept height, so it is measured again in its new look."""
        for fragment in fragments:
            if (row := self.row_of(fragment.key)) >= 0:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index)


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

    def shifted(self, rows: float) -> None:
        """Layout moved the reader `rows` mid-glide: the glide is to the same message."""
        self.start += rows
        self.target += rows

    def cancel(self) -> None:
        """Stop where it is: the reader's own scrolling owns the rows now."""
        self.window.head_reveal = None
        self.animation.stop()


class HistoryRowDelegate(HoldsRows, RowDocumentDelegate):
    """Each fragment's line blocks as Qt rich text, rendered on the pool at the row's width
    (dividers fill it); a row paints its plain text until then. A painted row tells the
    window, which marks what the reader saw."""

    ROW_PADDING = 0
    """The blocks own their spacing (`Gap`), as Textual's rows do: the parts of one message
    meet, so its accent bar runs unbroken from part to part."""

    def __init__(self, renderer: QtLineRenderer, pictures: RowPictures, processes: Renderer) -> None:
        super().__init__()
        self.processes = processes
        """The app's render processes: the only place a row's blocks become rich text."""
        self.pictures = pictures
        """The app's drawn rows (`RowPictures`), shared by every history it has open."""
        # Each drawn row's last prepared look (`styled_formatting`), by `row_identity`.
        self.last_shown: dict = {}
        self.app_renderer = renderer
        """The app's renderer, which follows `ui.theme` and the `diff` settings."""
        self.renderer = renderer
        """Replaced, never mutated, when the link context settles or the app's renderer
        restyles: a preparation already on the pool keeps the binding it was handed."""
        self.links_revision = 0

    def link(self, links: LinkContext) -> None:
        """Rows draw with these names from now on; rows prepared before are stale."""
        self.renderer = self.app_renderer.with_links(links)
        self.links_revision += 1
        # Every row's key names the links it was drawn with: none keeps its height.
        self.forget_row_sizes()

    def restyle(self) -> None:
        """The app's renderer took a new scheme or diff marks: rows draw by it from now on,
        with the names they had; rows prepared before are stale."""
        self.link(self.renderer.links)

    def preparation_key(self, index: QModelIndex, font: QFont, width: int):
        return self.fragment_key(index.data(HistoryRows.FRAGMENT), font, width)

    def preparation(self, index: QModelIndex, font: QFont, width: int) -> QtRowPreparation:
        return self.row_preparation(index.data(HistoryRows.FRAGMENT), font, width)

    def row_preparer(self) -> AskedRowPreparer:
        """History rows are prepared in the app's render processes and nowhere else: Python
        on a thread of this process takes turns with the frame for the interpreter."""
        return AskedRowPreparer(self, PresentationBudget.batch_items)

    # HoldsRows: a unit is a row's key and its preparation.

    async def render_rows(self, waiting):
        """The one place a history row is sent to be rendered."""
        return await self.processes.submit(
            QtHistoryRowBatchRenderTask(tuple(preparation for _key, preparation in waiting)))

    def hold_row(self, waiting, row: RenderedRow) -> None:
        """The row takes its place in the cache, drawn or not yet, and is what the row lays
        out from now on (`_row_prepared`)."""
        key, _preparation = waiting
        self._row_prepared(key, row)

    def fragment_key(self, fragment: HistoryFragment, font: QFont, width: int):
        """A fragment's row as shown, with these links, in this font at this width: dividers
        fill the width. A draft or live row grows, so its revision is part of the key."""
        return self.drawn_key((fragment.key, fragment.shown, fragment.revision), font, width)

    def header_key(self, header: Divider, font: QFont, width: int):
        """A pinned header on its own: prepared, kept and laid out as a row is."""
        return self.drawn_key(self.header_shown(header), font, width)

    @staticmethod
    def header_shown(header: Divider) -> tuple:
        """A header's place in a key, where a row's has its fragment, look and revision."""
        return header, None, 0

    def drawn_key(self, shown: tuple, font: QFont, width: int):
        return shown, self.links_revision, font.family(), font.pointSize(), width

    def row_preparation(self, fragment: HistoryFragment, font: QFont, width: int) -> QtRowPreparation:
        """Data-only row work: Qt measures its monospace cell once; the worker owns HTML, of
        the row, of each leading block the pin measures on its own (the header blocks and the
        one after them) and of the header the row pins."""
        return self.block_preparation(fragment.line_blocks, font, width,
                                      headed=fragment.header_blocks + 1, pinned=fragment.pinned_dividers)

    def block_preparation(self, blocks, font: QFont, width: int, *, headed: int = 0,
                          pinned: tuple[Divider, ...] = ()) -> QtRowPreparation:
        cell = max(1.0, QFontMetricsF(font).averageCharWidth())
        return QtRowPreparation(
            blocks=blocks,
            scheme=self.renderer.scheme,
            links=self.renderer.links,
            diff=self.renderer.diff,
            width=max(1, int((width - 8) / cell)),
            headed=headed,
            pinned=pinned,
        )

    def prepared_look(self, key) -> RenderedRow | None:
        """The row's prepared formatting under `key`, or the look it last showed while a new
        one is prepared; none for a row that never had one."""
        return self._prepared.get(key) or self._prepared.get(self.last_shown.get(self.row_identity(key)))

    def painted_document(self, index: QModelIndex, option: QStyleOptionViewItem) -> QTextDocument:
        # A wide row's paint rect is its intrinsic extent. Layout still uses the
        # viewport width, or wrapped prose would stop wrapping after scrolling code.
        return self.row_document(index, option.font, self.layout_width(option.rect.width()))

    PREFORMATTED_SHEET = f"pre {{ white-space: {PREFORMATTED.css_white_space}; }}"
    """Every `pre` in a row, whoever wrote it (a highlighted fence, Markdown's own for an
    unknown language, a tool's output), is laid out as the shared declaration says."""

    def new_document(self, font: QFont, width: int) -> QTextDocument:
        document = super().new_document(font, width)
        document.setDefaultStyleSheet(self.PREFORMATTED_SHEET)
        return document

    def available_width(self, option: QStyleOptionViewItem) -> int:
        """Rows are laid out at the viewport's width: a wide row's own rect is its extent,
        and wrapped prose laid out at that would stop wrapping."""
        return self.layout_width(super().available_width(option))

    def layout_width(self, extent: int) -> int:
        """The width a row is laid out and prepared at: the viewport's, whatever the row's
        own extent came out as (a row with an unwrapped block is wider). `extent` only
        before the view has a viewport."""
        return self.view.viewport_width() or extent

    def hinted(self, key, size: QSize) -> QSize:
        """A row takes its height at the layout width and, across, what the reader's wrap
        choice makes of how wide its content came out (`row_extent`): the layout width while
        code wraps, and the content's own while it does not, which is what gives the history
        one horizontal scrollbar for an unwrapped diff instead of clipping it.

        The measured extent alone decided this, and a measurement holds Qt's rounding: a
        header's table (rule, title, rule) gives its two rules the room left over rounded up
        each, so half of all headers lay out one pixel wider than the width they were given.
        One pixel made the history scrollable sideways, and QScroller lets a scrollable axis
        be dragged past its edge: a finger moving across the page pulled every wrapped
        message up to 129 px into empty space (2026-11-22). pyqt-reactive answers this from
        the row's kept key, so a layout over every loaded row builds no row's key."""
        layout = size.width()
        return QSize(self.renderer.diff.wrap.fitted_width(layout, self.row_extent(key, layout)), size.height())

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
        prepared = self.prepared_look(key)
        if prepared is None:
            # A row drawn before its formatting arrived has no blocks to measure: its head.
            return 0, 0
        top = 0
        decided = fragment.header_blocks
        for index, html in enumerate(prepared.leading):
            if index == decided and index < len(blocks) - 1:
                return index, 0
            # The pin asks on every scroll offset: a block is laid out once per look.
            height = self.measured_height((key, index), font, width, HtmlRow(html))
            if y < top + height or index == len(blocks) - 1:
                return index, max(0, int((y - top) // line))
            top += height
        return 0, 0

    def header_document(self, header: Divider, font: QFont, width: int) -> QTextDocument | None:
        """A pinned header laid out as its row lays it out at this width, or none while it is
        prepared. Its rich text came with its row (`RenderedRow.pinned`); a header no row brought
        in this look (the width or the links just changed) is prepared as a row is, in a
        render process, and the pin is drawn again when it lands."""
        key = self.header_key(header, font, width)
        formatting = self.keyed_formatting(key, "", self.block_preparation((header,), font, width))
        return self.laid_out(key, font, width, formatting) if formatting.final else None

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
        formatting = self.keyed_formatting(key, fragment.clipboard_text, self.row_preparation(fragment, font, width))
        if not formatting.final:
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

    def _row_prepared(self, key, prepared: RenderedRow) -> None:
        super()._row_prepared(key, prepared)
        if key in self._prepared:
            self.last_shown[self.row_identity(key)] = key
            _shown, *look = key
            for header, html in prepared.pinned:
                # The header this row pins is prepared with it, in the row's look: the pin
                # waits on none, and each part of a message brings the same one.
                alone = self.header_shown(header), *look
                if alone not in self._prepared:
                    super()._row_prepared(alone, RenderedRow(html, (), ()))
        if len(self.last_shown) > 2 * self.MAX_PREPARED_ROWS:
            # Looks the prepared cache let go of name nothing to draw.
            self.last_shown = {row: shown for row, shown in self.last_shown.items() if shown in self._prepared}

    def is_prepared(self, key) -> bool:
        return key in self._prepared

    TILE = 1024
    """Pixels of a row's height one picture holds. A row is as tall as its message, and a
    long message's whole picture would take most of what the app may retain; in tiles, the
    part of it on screen is drawn and kept, as a short row is."""

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        """A row is painted from pictures of it (`paint_pictures`): a scroll moves the same
        rows a few pixels a frame, and laying a row's rich text out and drawing every glyph
        again each frame was most of the phone's work while scrolling. A rising row's fade
        paints the same pictures at that frame's opacity."""
        fragment = index.data(HistoryRows.FRAGMENT)
        opacity = self.view.arrival_opacity(fragment.key) if self.view.arrivals else None
        if not self.paint_pictures(painter, option, index, fragment.key, opacity):
            super().paint(painter, option, index)
        self.view.row_painted(fragment, option.rect)

    def release_documents(self) -> None:
        """Pictures are drawn from documents and hold them: they go with them (Android
        suspending the app, a new width)."""
        super().release_documents()
        self.pictures.clear()

    def paint_pictures(self, painter: QPainter, option, index, key, opacity: float | None) -> bool:
        """The tiles of the row that this paint shows, each drawn once and copied by every
        later frame; a new width, height, pixel ratio or document draws them again. False
        for a row still being prepared, which paints its plain text itself for the frame or
        two it lasts; a rising one is painted from pictures all the same, as its fade
        repaints it every frame."""
        rect = option.rect
        local = QStyleOptionViewItem(option)
        local.rect = QRect(0, 0, rect.width(), rect.height())
        document = self.painted_document(index, local)
        if document is None and opacity is None:
            return False
        shown = painter.clipBoundingRect().toAlignedRect().intersected(rect) if painter.hasClipping() else rect
        if shown.isEmpty():
            return True
        ratio = painter.device().devicePixelRatioF()
        look = (rect.width(), rect.height(), ratio)
        # A row is its document; one still being prepared has none, and is this view's row.
        row = id(document) if document is not None else (id(self), key)
        painter.save()
        if opacity is not None:
            painter.setOpacity(opacity)
        for tile in range((shown.top() - rect.top()) // self.TILE, (shown.bottom() - rect.top()) // self.TILE + 1):
            top = tile * self.TILE
            picture = self.pictures.kept((row, tile), look, document)
            if picture is None:
                height = min(self.TILE, rect.height() - top)
                picture = QPixmap(max(1, round(rect.width() * ratio)), max(1, round(height * ratio)))
                picture.setDevicePixelRatio(ratio)
                picture.fill(Qt.GlobalColor.transparent)
                drawing = QPainter(picture)
                local.rect = QRect(0, -top, rect.width(), rect.height())
                super().paint(drawing, local, index)
                drawing.end()
                self.pictures.keep((row, tile), look, document, picture)
            painter.drawPixmap(QPoint(rect.left(), rect.top() + top), picture)
        painter.restore()
        return True


class RowPictures(NativePresentation):
    """Drawn rows kept as pictures, the most recently painted last to go: the paint bytes
    Qt's histories retain (`NativePresentation.retained_paint_bytes`), within the app's one
    limit on retained prepared work (`PreparationRuntime.max_bytes`), so the rows around
    the reader scroll as pictures and neither a long history nor many open tabs hold a
    picture for every row. Textual retains its rows as the lines its worker finished; a
    row's pixels are what Qt has finished when its document is drawn."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        # By the row's document (a row still being prepared: its fragment key) and the
        # tile of it: (look, document, picture). Holding the document keeps the one the
        # picture was drawn from alive, so its identity cannot pass to a new document.
        self.rows: OrderedDict = OrderedDict()
        self.bytes = 0

    @property
    def retained_paint_bytes(self) -> int:
        return self.bytes

    @staticmethod
    def weight(size: QSize) -> int:
        return size.width() * size.height() * 4

    def kept(self, key, look, document) -> QPixmap | None:
        entry = self.rows.get(key)
        if entry is None or entry[0] != look or entry[1] is not document:
            return None
        self.rows.move_to_end(key)
        return entry[2]

    def keep(self, key, look, document, picture: QPixmap) -> None:
        self.drop(key)
        self.rows[key] = (look, document, picture)
        self.bytes += self.weight(picture.size())
        while self.bytes > self.limit and len(self.rows) > 1:
            self.drop(next(iter(self.rows)))

    def drop(self, key) -> None:
        entry = self.rows.pop(key, None)
        if entry is not None:
            self.bytes -= self.weight(entry[2].size())

    def clear(self) -> None:
        self.rows.clear()
        self.bytes = 0


@dataclass(frozen=True)
class QtRowPreparation(BlockPreparation):
    """One Qt row's immutable presentation declarations, safe across either transport."""

    scheme: ColourScheme
    links: LinkContext
    diff: DiffSettings
    width: int
    headed: int
    """How many of the row's first blocks are also rendered each on its own (`RenderedRow.leading`)."""
    pinned: tuple[Divider, ...]
    """The header the row pins, rendered on its own (`RenderedRow.pinned`): it need not be one of
    the row's blocks (a later part of a message pins a header only its first part draws)."""

    def render(self) -> RenderedRow:
        html = QtLineRenderer(self.scheme, self.links, self.diff).at_width(self.width).html
        return RenderedRow(html(self.blocks), tuple(html((block,)) for block in self.blocks[:self.headed]),
                           tuple((header, html((header,))) for header in self.pinned))


@dataclass(frozen=True)
class RenderedRow(HtmlRow):
    """A history row as a render process hands it back: everything the window reads of the
    row's rendering. The UI process renders nothing."""

    leading: tuple[str, ...]
    """Each leading block's rich text alone, in order: what the pin measures to place the
    window's top row among the row's header blocks."""
    pinned: tuple[tuple[Divider, str], ...]
    """Each header the row pins, and its rich text."""


class AskedRowPreparer(RowsAsked, RowPreparer):
    """pyqt-reactive's place for a row's preparation, answered by the shared `RowsAsked`: a
    row the view draws unprepared is rendered by the worker processes and held by the
    delegate, as a row the pager prepared is."""

    def __init__(self, rows: HistoryRowDelegate, batch: int) -> None:
        RowsAsked.__init__(self, rows, batch)
        RowPreparer.__init__(self, rows._rows_prepared)

    def prepare(self, key, work: QtRowPreparation) -> None:
        self.ask((key, work))

    def clear(self) -> None:
        self.drop()


@dataclass(frozen=True)
class QtHistoryRowBatchRenderTask(RenderTask[tuple[RenderedRow, ...]]):
    """Rows the shared pager asks be prepared ahead of drawing them, submitted through the
    launch's `app.render_processes` as Textual's `TranscriptLinesBatchRenderTask` is.

    The task carries each row's presentation declarations and nothing else; its result is
    one formatting per row, in order. Which cache key a formatting lands under is the
    delegate's own fact and never crosses the process boundary: a key that went to a worker
    and came back was a copy that no longer matched the one the delegate asks under, so
    every prepared row was dropped, rendered again inside the UI process, measured as an
    estimate and laid out again when that second render landed (a 229-row scroll-back:
    490 rows rendered twice, about 130 whole layouts).
    """

    rows: tuple[QtRowPreparation, ...]

    def execute(self) -> tuple[RenderedRow, ...]:
        return tuple(preparation.render() for preparation in self.rows)

    def result_size(self, result: tuple[RowFormatting, ...]) -> int:
        return 64 * (len(result) + 1)


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


class QtConversationHistory(DrawsBusMessages, SourceNotifications, ReadMarkedHistory, ConversationPager,
                            MeasuresFragments, NativePager):
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
        super().__init__(source_state=self.initial_state(view),
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

    @property
    def measurable(self) -> bool:
        """Not laid out yet: the first paint prepares its rows at the real width."""
        return self.window.viewport_width() > 0

    def unprepared(self, fragment: HistoryFragment) -> tuple[object, ...]:
        """The fragment's row at the window's width and font, unless the delegate holds it."""
        window = self.window
        rows, font, width = window.rows, window.font(), window.viewport_width()
        key = rows.fragment_key(fragment, font, width)
        return () if rows.is_prepared(key) else ((key, rows.row_preparation(fragment, font, width)),)

    async def render_rows(self, waiting):
        return await self.window.rows.render_rows(waiting)

    def hold_row(self, waiting, row) -> None:
        self.window.rows.hold_row(waiting, row)

    async def _show(self, changes: list[tuple[HistoryFragment, Shown]]) -> None:
        """A status change repaints only the rows it changed. A row's cache key carries how
        its fragment is shown, so the repaint asks the delegate for the new look, which keeps
        drawing the last one until it is prepared, and that arrival lays the rows out
        (`RowDocumentDelegate._row_prepared`). Laying every row out here on each receipt
        update cost the whole history's measurement while the new looks were not even ready."""
        changed = tuple(fragment for fragment, shown in changes if fragment.request_show(shown))
        if changed:
            self.window.model_rows.changed(changed)
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
        """The view hears what its history publishes, through the handlers the shared view
        classes declare (`BoundViewHost`, `WireView`), as Textual's pump carries it up from
        the history widget. (This was empty, "no Qt listener waits on a history's source
        work": a Qt thread never retried the publication that had waited for that work, and
        a Qt channel never reconciled an observation that arrived during it.)

        Coverage has no Qt handler: a Qt view stands no live blocks for it to retire
        (`HistoryRowsBlocks`)."""
        self.core_publications.publish(event)

    @cached_property
    def core_publications(self) -> CoreEventStream:
        """This history's own publications, which its view hears whole: Textual's history
        widget holds the same stream and its pump carries each event up to the view."""
        stream = CoreEventStream(self)
        self.view.subscribe_core(stream)
        return stream

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

    def close(self) -> None:
        self.attached = False
        super().close()
        # Rows still rendering in the workers must not land in a delegate Qt is about to
        # delete (`cleanup` stops and joins them; it ran for no history, so a render that
        # finished after its tab closed raised "QTimer already deleted" into the loop).
        self.window.rows.cleanup()


class QtWireHistory(AwaitsFirstPage, QtConversationHistory):
    """A channel or direct conversation's history, as Textual's `WireHistory`: until its
    first page is drawn the reader is told it is loading, floating over the window so
    nothing moves when it goes."""

    def __init__(self, window: QtHistoryWindow, view, app) -> None:
        super().__init__(window, view, app)
        self.waiting = QtFloatLayer(
            app.theme.color_scheme, app.renderer, app.animation_clock, window)
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
    """No row under a Qt window's top edge: only the scroll offset is known."""

    def reader_position(self, window: QtHistoryWindow) -> RowPosition:
        return RowPosition(window.scroll_y)


@dataclass(frozen=True)
class QtRowUnderTop(QtTopRow):
    """A fragment's row holds the top edge, `into` pixels of its `height` above it. The reader
    is on that message, as Textual's `PageBelowTop` names them, and its fragment decides the
    pinned header."""

    window: QtHistoryWindow
    fragment: HistoryFragment
    left: int
    width: int
    into: int
    height: int

    @cached_property
    def under(self) -> FragmentRowUnderTop:
        """The block and line on the top edge, worked out when a header is pinned: every
        scroll offset names the reader's message, and only a display frame pins."""
        block, row = self.window.rows.block_row(self.fragment, self.window.font(), self.width, self.into)
        return FragmentRowUnderTop(self.fragment, block, row, self.left, self.width)

    def reader_position(self, window: QtHistoryWindow) -> FragmentPosition:
        return FragmentPosition(self.fragment.key, self.into / self.height, self.height, block=0)

    def pinned_header(self, window: QtHistoryWindow) -> PinnedHeader:
        return self.under.pinned_header()


@dataclass(frozen=True)
class QtRowLocation(FragmentLocation):
    """A message's row in a Qt window. Qt lays every row out in one step, so a row the model
    holds is laid out; a message with no row is `UnloadedFragment`."""

    row: int
    fragment: HistoryFragment

    def location(self) -> FragmentLocation:
        return self

    def for_layout(self, window: QtHistoryWindow, position: ReaderPosition) -> ReaderPosition:
        return position

    def laid_out(self, window: QtHistoryWindow) -> bool:
        return True

    def destination(self, window: QtHistoryWindow, fraction: float) -> float:
        rect = window.visualRect(window.model_rows.index(self.row, 0))
        return window.scroll_y + rect.top() + round(fraction * rect.height())

    def find_in(self, pages, position: FragmentPosition) -> FragmentLocation:
        return self


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
        kept = self.laid_out if context == self.layout_context else {}
        laid_out = {header: kept.get(header) or window.rows.header_document(header, window.font(), width)
                    for header in headers}
        if None in laid_out.values():
            # A header still being prepared: the pin keeps what it draws and is asked again
            # when the header lands (`QtHistoryWindow.rows_repainted`).
            return
        self.drawn = drawn
        self.layout_context = context
        self.laid_out = laid_out
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


class QtHistoryWindow(ShowsLatestJumpBar, FollowsTail, ReaderWindow, WorkspaceHosted, VirtualRowView,
                      ReaderPlacement, PagingWindow, OpensLineLinks, PinsMessageHeader, SettingsReading):
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
    # `scroll_revision`, `history_change` and `keep_reader` are JumpsToLatest's (shared with Textual).

    @property
    def is_attached(self) -> bool:
        """Whether the window is still in its view, as Textual's `Widget.is_attached`
        answers for `HistoryWindow`: `BoundView` publishes only into an attached window."""
        return not self.widget_gone and self.parent() is not None

    @property
    def widget_gone(self) -> bool:
        """Whether Qt has destroyed this window's widget. Every Qt read of a destroyed widget
        raises RuntimeError; a late task that may outlive the view asks this first, and no
        code here catches that RuntimeError: caught, it hid every other one under it."""
        return not shiboken6.isValid(self)

    @property
    def screen(self) -> WorkspaceFrame:
        """Qt's workspace frame is the top-level `QtToadApp` (which inherits
        `QtWorkspaceFrame`). Qt widgets reach it through `window()`, not through a
        Textual `Widget.screen` chain, so `WorkspaceHosted`'s `super().screen` is
        replaced here."""
        return self.window()

    def __init__(self, renderer: QtLineRenderer, pictures: RowPictures, scope,
                 parent: QWidget | None = None) -> None:
        super().__init__(HistoryRowDelegate(renderer, pictures, scope.app.render_processes), parent)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.configuration_scope = scope  # the view this window reads in
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
        for changed in (self.model_rows.rowsInserted, self.model_rows.rowsRemoved,
                        self.model_rows.dataChanged, self.model_rows.modelReset):
            changed.connect(self.rows_moved)
        # Frame-rate coalescing: QScroller fires valueChanged at touch rate (90Hz
        # on Pixel 8a, up to 240Hz). The post-scroll chain (repin_header,
        # lookahead, page requests, tail-follow) runs once per display frame —
        # the same cadence as the TUI. Each valueChanged records the latest offset
        # and starts a single-shot timer at the display's frame interval; the
        # timer fires the full shared response. At frame-rate input (fling,
        # keyboard), the timer fires on the next event-loop pass (0 ms remaining),
        # so there is no added latency.
        self._scroll_frame_timer = QTimer(self)
        self._scroll_frame_timer.setSingleShot(True)
        self._scroll_frame_timer.timeout.connect(self._scroll_frame)
        self._scroll_frame_pending = False
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
        return self.configuration_scope.app.animation_clock

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
        if not self.reader_position.joins_tail(self):
            # An arrival taller than the window is read from its head: layout places it there
            # (`ArrivalPosition`), and a glide still running stops with the following.
            return False
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
        """Where the rows are being carried (`animated_travel`), within what is loaded; where
        they are when nothing carries them."""
        return max(0.0, min(self.max_scroll_y, self.scroll_y + self.animated_travel))

    @property
    def max_scroll_y(self) -> float:
        return self._safe_qt_read(lambda: self.verticalScrollBar().maximum(), 0.0)

    @property
    def tail_scroll_y(self) -> float:
        return self.max_scroll_y

    def _safe_qt_read(self, read, default):
        """`read`'s answer from a window Qt still has; `default` from a destroyed one. Late
        pager tasks still ask a closed view for geometry, visibility and fragment heights,
        and a benign answer lets their publish stop short. Only that is answered for: this
        used to catch every RuntimeError the read raised, so a failure inside a measurement
        (any RuntimeError, from anywhere under it) came back as a height of 0."""
        return default if self.widget_gone else read()

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
        """Pixels the rows are still being carried with no finger on them, as Textual answers
        with its scroll animation's distance to its target: a head reveal's way to its head,
        or a fling's momentum (`fling_travel`)."""
        if self.head_reveal is not None:
            return self.head_reveal.target - self.scroll_y
        return self._safe_qt_read(self.fling_travel, 0.0)

    def fling_travel(self) -> float:
        """How far a fling's speed carries the rows at QScroller's deceleration (v²/2a, the
        distance QScroller itself plans), whether or not rows are loaded that far: Qt stops
        a fling at the loaded edge, and the rows it was thrown towards are what the reader
        asked for."""
        scroller = QScroller.scroller(self.viewport())
        if scroller.state() != QScroller.State.Scrolling:
            return 0.0
        speed = scroller.velocity().y()
        deceleration = scroller.scrollerProperties().scrollMetric(
            QScrollerProperties.ScrollMetric.DecelerationFactor)
        return copysign(speed * speed / (2 * deceleration) * scroller.pixelPerMeter().y(), speed)

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
        if self.widget_gone:
            return ()
        area = self.viewport().rect()
        top, bottom = self.indexAt(area.topLeft()), self.indexAt(area.bottomLeft())
        if not top.isValid():
            return ()
        last = bottom.row() if bottom.isValid() else self.model_rows.rowCount() - 1
        return self.model_rows.fragments[top.row():last + 1]

    def fragment_location(self, key) -> FragmentLocation:
        row = self.model_rows.row_of(key)
        return QtRowLocation(row, self.model_rows.fragments[row]) if row >= 0 else UnloadedFragment()

    # The reader

    @property
    def follows_tail(self) -> bool:
        return self._anchored

    def apply_anchor(self, anchor: bool) -> None:
        self._anchored = anchor
        # A publication restoring a following reader (`FollowTailCommit.restore_reader`)
        # glides to rows that just arrived; a running glide lands on the end itself.
        # A view closed between scheduling this and its running has nothing to scroll.
        if anchor and not self.widget_gone and not self.gliding_to_end():
            with self.layout_scroll():
                self.follow_end()

    def jump_to_latest(self) -> None:
        """`JumpsToLatest.jump_to_latest` is abstract; the QtJumpBar click is wired to this
        at `__init__` (`self.jump_bar.clicked.connect(self.jump_to_latest)`). Without the
        override, clicking the Back-to-Bottom button ran the abstract docstring-only body
        and did nothing. Snapping back to the tail via `anchor(True)` runs `follow_end`
        which scrolls the viewport to the latest row, mirroring Textual's
        `WindowAction.scroll_end` path."""
        self.anchor(True)

    @asynccontextmanager
    async def tree_change(self):
        """Qt's rows are read again from the pages once the change to them is made; a window
        torn down meanwhile has none to read."""
        try:
            yield
        finally:
            if self.is_attached:
                self.show_rows()

    def show_rows(self) -> None:
        """Read the rows again from the history's shown pages, then the draft after them."""
        history = self.history
        self.model_rows.show(tuple(fragment for page in history.pages if page.display
                                   for fragment in page.shown_fragments) + self.draft
                             + tuple(block.fragment() for block in self.live_blocks))

    def show_pages(self) -> None:
        """The rows as the pages show them now, laid out with the reader kept on their message."""
        self.show_rows()
        self.request_reader_layout()

    def rows_moved(self, *_changed) -> None:
        """The model's rows changed: a change open over this window needs a layout to show it."""
        self.geometry_revision += 1

    geometry_revision = 0

    def request_reader_layout(self) -> None:
        """Qt has no later frame to lay out in: one layout now, and none left pending (a model
        insert or removal schedules Qt's own, which a direct `doItemsLayout` would leave to
        run a second time on the next turn). It puts the reader back on the message they
        were reading and answers the change that asked for it, as Textual's screen does
        around each of its layouts. A glide to the end owns the way there."""
        answered = self.history_change.layout_requests
        self.scheduleDelayedItemsLayout()
        self.executeDelayedItemsLayout()
        if not (self.follows_tail and self.gliding_to_end()):
            self.place_layout_reader()
        self.history_change.finish_layout(answered)
        self.repin_header()

    def show_draft(self, fragments: tuple[HistoryFragment, ...]) -> None:
        """Core's CLI draft as rows after the history (none clears it); the reader keeps their place."""
        if not fragments and not self.draft:
            return
        self.draft = fragments
        self.show_pages()

    def show_live(self, block: QtLiveBlock) -> None:
        """A turn's live block as a row after the history and the draft."""
        self.live_blocks.append(block)
        self.live_changed()

    def live_changed(self) -> None:
        """A live block grew or left: read the rows again, following the end if the reader was."""
        self.show_pages()

    def drop_live(self, block: QtLiveBlock) -> None:
        if block in self.live_blocks:
            self.live_blocks.remove(block)
            self.live_changed()

    def committed_pages_changed(self) -> None:
        """Saved rows arrived: they now carry the output of every finished live block."""
        self.live_blocks = [block for block in self.live_blocks if not block.finished]
        if self.history.pages:
            self.history.note_sent_references(self.history.pages[-1].shown_fragments)
        self.show_pages()

    def restyle_rows(self) -> None:
        self.rows.restyle()
        self.rows_changed()

    def rows_repainted(self) -> None:
        """Prepared rows, or a header the pin waited on, landed at the height they had."""
        super().rows_repainted()
        self.repin_header()

    def rows_changed(self) -> None:
        """Prepared rows changed height: lay them out again; the layout keeps the reader's
        message. A destroyed window has no reader to serve."""
        if not self.widget_gone:
            self.request_reader_layout()
            self.viewport().update()

    def scrolled(self, value: int) -> None:
        """The reader moved: join or leave the end, and schedule the full response on the
        next display frame. QScroller fires valueChanged at touch rate during a drag;
        coalescing to frames runs the same work at the same cadence as the TUI.

        The at_end/follows_tail transitions are immediate — they are cheap state flips
        and consumers (jump bar + anchor) need to see them during every touch tick."""
        # Every offset pins, the window's own as well as the reader's: a glide down into a tall
        # arrival moves the top row into it, and skipping the window's own offsets left the
        # arrival's header unpinned and its burst unstacked (Tristan, Android, 2026-11-18).
        self._schedule_scroll_frame()
        moved, self._scrolled_to = value - self._scrolled_to, value
        if self._restoring:
            return
        if self.at_end and not self.follows_tail:
            self.anchor()
        elif not self.at_end and self.follows_tail:
            self.release_anchor()
        elif not self.follows_tail:
            # The message under the top edge now; while a change is open, the kept one moves
            # with the reader (`HistoryChange.moved`).
            self.reader_position = self.reader_position.moved(self, moved)
        self._reader_scrolled = True

    _reader_scrolled = False
    _scrolled_to = 0

    def _schedule_scroll_frame(self) -> None:
        if not self._scroll_frame_pending:
            self._scroll_frame_pending = True
            interval = max(1, round(frame_interval(QWidget.screen(self)) * 1000))
            self._scroll_frame_timer.start(interval)

    def _scroll_frame(self) -> None:
        """One display frame's scroll response: the pin for every offset, and the reader's
        response (velocity, page requests, tail-follow) when the reader moved. Runs at frame
        rate regardless of input rate — the same cadence as the TUI."""
        self._scroll_frame_pending = False
        self.repin_header()
        if self._reader_scrolled:
            self._reader_scrolled = False
            self.respond_to_scroll(self.verticalScrollBar().value())

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
        """A finger taking the rows stops a head reveal; a press that stops a fling is
        remembered, so its release is not read as a tap on a row."""
        if state in (QScroller.State.Pressed, QScroller.State.Dragging) and self.head_reveal is not None:
            self.head_reveal.cancel()
        if state == QScroller.State.Pressed:
            self._fling_stopped = self._flinging
        self._flinging = state == QScroller.State.Scrolling
        if state == QScroller.State.Inactive:
            self._overshoot = 0.0
            self._travel_origin = 0.0

    _travel_origin = 0.0
    """How far layout has moved the reader since the finger now scrolling them came down.
    QScroller plans a drag or a fling in scroll offsets it read when the finger came down;
    rows landing above the reader move every offset, so its next frame put the reader back
    on the old offset, a page of rows away. It is answered in offsets taken from this
    origin, which layout does not move (`viewportEvent`, `shift_travel`)."""

    def viewportEvent(self, event: QEvent) -> bool:  # type: ignore[override]
        """QScroller's two events, in the travelling finger's own offsets: it is told where
        the rows are less the origin, and what it asks for is shown at that plus the origin."""
        origin = self._travel_origin
        if not origin:
            return super().viewportEvent(event)
        if event.type() == QEvent.Type.Scroll:
            return super().viewportEvent(QScrollEvent(
                event.contentPos() + QPointF(0, origin), event.overshootDistance(), event.scrollState()))
        handled = super().viewportEvent(event)
        if handled and event.type() == QEvent.Type.ScrollPrepare:
            event.setContentPosRange(event.contentPosRange().translated(0, -origin))
            event.setContentPos(event.contentPos() - QPointF(0, origin))
        return handled

    def shift_travel(self, rows: float, destination: float) -> None:
        """A head reveal glides to the same message; a finger's drag or fling goes on from
        the same rows at the same speed. QScroller prepares again from the moved origin: a
        fling it had planned to end at the loaded edge is planned again at its present
        speed, into the rows that landed."""
        if self.head_reveal is not None:
            self.head_reveal.shifted(rows)
        scroller = QScroller.scroller(self.viewport())
        if scroller.state() != QScroller.State.Inactive:
            self._travel_origin += rows
            scroller.resendPrepareEvent()

    def overshot(self, distance: float) -> None:
        """A finger (or a fling's momentum) pulled the rows past an edge: the content can't
        move, so no scroll travel is measured, yet the reader asked for more. Each pull
        further past it asks the shared lookahead for that edge's next page, as a wheel
        step at an edge does (`wheelEvent`)."""
        further = abs(distance) - abs(self._overshoot)
        self._overshoot = distance
        if distance and further > 0:
            # In this window's rows, which are pixels, as every other travel it reports.
            self.lookahead.request_boundary(-further if distance < 0 else further)

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

    # The reader window contract's measurements Qt keeps by row instead

    def top_page(self) -> QtTopRow:
        """The row under the viewport's top edge, with the block and line of its fragment
        there: Qt measures that by pixel, where Textual counts cells."""
        if self.widget_gone:
            return QtTopRow()
        top = self.indexAt(self.viewport().rect().topLeft())
        if not top.isValid():
            return QtTopRow()
        rect = self.visualRect(top)
        if rect.height() <= 0:
            return QtTopRow()
        # The row's layout width, not its extent: a row with an unwrapped block is wider than
        # the viewport, its header is not, and the pin draws that header.
        return QtRowUnderTop(self, top.data(HistoryRows.FRAGMENT), rect.left(),
                             self.rows.layout_width(rect.width()), -rect.top(), rect.height())

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
        """Whether `item` is a page this window draws."""
        return any(item is page for page in self.drawn_pages())

    def row_of(self, item) -> int:
        raise LookupError(item)

    def drawn_pages(self) -> Iterator[QtPage]:
        return (page for history in self.histories for page in history.pages if page.display)

