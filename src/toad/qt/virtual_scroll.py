"""Prefix-sum virtual row canvas and text-inversion tap highlight for Qt histories.

Replaces `QListView` + `QAbstractListModel` + `QStyledItemDelegate` on `QtHistoryWindow`
with a direct `QAbstractScrollArea` backed by a flat prefix-sum height table:

- O(log N) row lookup (`bisect_right`), O(1) row rect and tail-append offset maintenance;
- zero `QAbstractItemView::verticalScrollbarValueChanged -> indexAt` scans on scroll ticks;
- zero `QListView::doItemsLayout` full-model walks or `QModelIndex`/`QStyleOptionViewItem`
  Shiboken wrapper churn on paint;
- skips `QTextDocument::idealWidth()` second-pass layout on rows without `<pre` blocks;
- nominal `TapHighlight` family inverting the actual tapped text/link color directly inside
  the live `QTextDocument` layout instead of painting stale pixel boxes over cached tiles.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
import math
import time

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPalette,
    QRegion,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextTable,
)
from PySide6.QtWidgets import QAbstractScrollArea, QWidget
from pyqt_reactive.widgets.virtual_rows import PendingRow, RowFormatting, RowPreparer, ThreadRowPreparer

from toad.arrivals import SETTLED_ARRIVAL, ViewportArrivalState
from toad.client.tap_flash import TapFeedback


def _inverted_char_format(bg: QColor, fg: QColor, existing: QTextCharFormat) -> QTextCharFormat:
    """Invert foreground and background on one tapped character run."""
    fmt = QTextCharFormat(existing)
    ink = existing.foreground().color() if existing.hasProperty(QTextFormat.Property.ForegroundBrush) else fg
    if not ink.isValid() or ink == bg:
        ink = fg
    fmt.setForeground(bg)
    fmt.setBackground(ink)
    return fmt


def _href_selections(document: QTextDocument, href: str, bg: QColor, fg: QColor) -> list[QAbstractTextDocumentLayout.Selection]:
    """Build `PaintContext.selections` covering every character run in `document` with `anchorHref() == href`."""
    selections: list[QAbstractTextDocumentLayout.Selection] = []
    block = document.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().anchorHref() == href:
                cursor = QTextCursor(document)
                cursor.setPosition(frag.position())
                cursor.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                sel = QAbstractTextDocumentLayout.Selection()
                sel.cursor = cursor
                sel.format = _inverted_char_format(bg, fg, frag.charFormat())
                selections.append(sel)
            it += 1
        block = block.next()
    return selections


def _divider_tables(document: QTextDocument) -> list[tuple[QTextTable, QColor]]:
    """Return every leading divider row `QTextTable` (1 row, 3 cols: `<hr> | title | <hr>`)
    and its rule colour at the top of `document`. Multi-line headers (title + wrapped title +
    timestamp) emit consecutive 3-column tables, so all of them flash together."""
    tables: list[tuple[QTextTable, QColor]] = []
    seen: set[int] = set()
    block = document.begin()
    while block.isValid():
        table = QTextCursor(block).currentTable()
        if table is None:
            if block.text().strip():
                break
            block = block.next()
            continue
        if table.rows() != 1 or table.columns() != 3:
            break
        left_blk = table.cellAt(0, 0).firstCursorPosition().block()
        right_blk = table.cellAt(0, 2).firstCursorPosition().block()
        hr_prop = QTextFormat.Property.BlockTrailingHorizontalRulerWidth
        if not (left_blk.blockFormat().hasProperty(hr_prop) and right_blk.blockFormat().hasProperty(hr_prop)):
            break
        tid = id(table)
        if tid not in seen:
            seen.add(tid)
            tables.append((table, left_blk.blockFormat().background().color()))
        block = block.next()
    return tables


def _header_selections(
    document: QTextDocument,
    bg: QColor,
    fg: QColor,
    tables: list[tuple[QTextTable, QColor]] | None = None,
) -> list[QAbstractTextDocumentLayout.Selection]:
    """Invert every text run across all leading message-header divider tables (or the first
    non-empty block when no divider table is present)."""
    selections: list[QAbstractTextDocumentLayout.Selection] = []
    divider_tables = _divider_tables(document) if tables is None else tables
    if divider_tables:
        for table, hr_color in divider_tables:
            ink = hr_color if hr_color.isValid() and hr_color != bg else fg
            cell = table.cellAt(0, 1)
            block = cell.firstCursorPosition().block()
            last = cell.lastCursorPosition().block()
            while block.isValid():
                it = block.begin()
                while not it.atEnd():
                    frag = it.fragment()
                    if frag.isValid() and frag.length() > 0:
                        cursor = QTextCursor(document)
                        cursor.setPosition(frag.position())
                        cursor.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                        sel = QAbstractTextDocumentLayout.Selection()
                        sel.cursor = cursor
                        fmt = QTextCharFormat(frag.charFormat())
                        fmt.setForeground(bg)
                        fmt.setBackground(ink)
                        sel.format = fmt
                        selections.append(sel)
                    it += 1
                if block == last:
                    break
                block = block.next()
        return selections
    block = document.begin()
    while block.isValid() and not block.text().strip():
        block = block.next()
    if block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.length() > 0:
                cursor = QTextCursor(document)
                cursor.setPosition(frag.position())
                cursor.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                sel = QAbstractTextDocumentLayout.Selection()
                sel.cursor = cursor
                sel.format = _inverted_char_format(bg, fg, frag.charFormat())
                selections.append(sel)
            it += 1
    return selections


class TapHighlight(TapFeedback, ABC):
    """What clickable text (or divider header + horizontal rules) is currently inverted in
    response to a tap."""

    def matches_row(self, key: object) -> bool:
        return False

    def matches_pinned(self, index: int) -> bool:
        return False

    def row_key(self) -> object | None:
        return None

    def is_pinned(self) -> bool:
        return False

    def invalidate_in(self, window) -> None:
        """Repaint whichever surface of `window` shows this highlight (no-op for none)."""

    def selections(self, document: QTextDocument, bg: QColor, fg: QColor) -> list[QAbstractTextDocumentLayout.Selection]:
        return []

    def paint_document(
        self,
        painter: QPainter,
        document: QTextDocument,
        palette: QPalette,
        bg: QColor,
        fg: QColor,
        clip: QRectF | None = None,
    ) -> None:
        """Draw `document` with this tap highlight's inverted formatting."""
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette = palette
        if clip is not None:
            context.clip = clip
        context.selections = self.selections(document, bg, fg)
        document.documentLayout().draw(painter, context)


class NoTapHighlight(TapHighlight):
    """No active tap inversion."""


NO_TAP_HIGHLIGHT = NoTapHighlight()


class LinkTapHighlight(TapHighlight):
    """Shared base for inverting one tapped `<a href>` span in either a row or pinned header."""

    href: str

    def selections(self, document: QTextDocument, bg: QColor, fg: QColor) -> list[QAbstractTextDocumentLayout.Selection]:
        return _href_selections(document, self.href, bg, fg)


class HeaderTapHighlight(TapHighlight):
    """Shared base for inverting a tapped message header divider — including every wrapped
    header line AND the flanking `<hr>` horizontal bars — in both in-flow rows and pinned headers."""

    def selections(self, document: QTextDocument, bg: QColor, fg: QColor) -> list[QAbstractTextDocumentLayout.Selection]:
        return _header_selections(document, bg, fg)

    def paint_document(
        self,
        painter: QPainter,
        document: QTextDocument,
        palette: QPalette,
        bg: QColor,
        fg: QColor,
        clip: QRectF | None = None,
    ) -> None:
        tables = _divider_tables(document)
        layout = document.documentLayout()
        for table, hr_color in tables:
            ink = hr_color if hr_color.isValid() and hr_color != bg else fg
            painter.fillRect(layout.frameBoundingRect(table), ink)
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette = palette
        if clip is not None:
            context.clip = clip
        context.selections = _header_selections(document, bg, fg, tables)
        layout.draw(painter, context)
        for table, _hr_color in tables:
            for col in (0, 2):
                brect = layout.blockBoundingRect(table.cellAt(0, col).firstCursorPosition().block())
                if brect.width() > 0:
                    painter.fillRect(QRectF(brect.left(), brect.center().y() - 0.5, brect.width(), 1.5), bg)


class RowTapTarget(TapHighlight):
    """Tap target located on an in-flow history row."""

    key: object

    def matches_row(self, key: object) -> bool:
        return key == self.key

    def row_key(self) -> object:
        return self.key

    def invalidate_in(self, window) -> None:
        row = window.model_rows.row_of(self.key)
        if row >= 0:
            window.update_row(row)


class PinnedTapTarget(TapHighlight):
    """Tap target located on a pinned sticky header."""

    index: int

    def matches_pinned(self, index: int) -> bool:
        return index == self.index

    def is_pinned(self) -> bool:
        return True

    def invalidate_in(self, window) -> None:
        window.sticky_header.update()


@dataclass(frozen=True, slots=True)
class RowLinkTapHighlight(RowTapTarget, LinkTapHighlight):
    """Invert the tapped `<a href>` text span inside one history row."""

    key: object
    href: str


@dataclass(frozen=True, slots=True)
class RowHeaderTapHighlight(RowTapTarget, HeaderTapHighlight):
    """Invert the tapped message header divider (text + horizontal bars) inside one history row."""

    key: object


@dataclass(frozen=True, slots=True)
class PinnedLinkTapHighlight(PinnedTapTarget, LinkTapHighlight):
    """Invert the tapped `<a href>` text span inside a pinned sticky header."""

    index: int
    href: str


@dataclass(frozen=True, slots=True)
class PinnedHeaderTapHighlight(PinnedTapTarget, HeaderTapHighlight):
    """Invert the tapped pinned sticky header (text + horizontal bars)."""

    index: int


class RowMetrics:
    """A row key's laid-out size and horizontal extent at one width."""

    __slots__ = ("size", "extent")

    def __init__(self, size: QSize | None = None, extent: int | None = None) -> None:
        self.size = size
        self.extent = extent


class RowSize:
    """One row slot's measured size at the current font and width, and its preparation key."""

    __slots__ = ("key", "size", "font", "estimated", "row")

    def __init__(self, key: Hashable, size: QSize | None, font: QFont, estimated: bool = False, row: int = -1) -> None:
        self.key = key
        self.size = size
        self.font = font
        self.estimated = estimated
        self.row = row


class ViewportCanvas:
    """Shared canvas surface exposed to row delegates for tap highlights and unified viewport
    arrival animation (`ViewportArrivalState`). Both `DetachedCanvas` and `VirtualRowCanvas`
    inherit it; `QtHistoryWindow` overrides arrivals via `AnimatesArrivals` ahead in its MRO."""

    tap_highlight: TapHighlight = NO_TAP_HIGHLIGHT
    has_active_arrivals: bool = False
    arrival_slide_distance: float = 0.0

    def arrival_state(self, key: object, row_height: float = 0.0) -> ViewportArrivalState:
        return SETTLED_ARRIVAL

    def arrival_opacity(self, key: object) -> float | None:
        return None

    def row_painted(self, fragment, rect: QRect) -> None:
        pass


class DetachedCanvas(ViewportCanvas):
    """Rows no canvas draws yet: nothing to lay out again or repaint, and no viewport width."""

    def rows_changed(self) -> None:
        pass

    def rows_repainted(self) -> None:
        pass

    def viewport_width(self) -> int:
        return 0

    def estimating(self) -> bool:
        return False

    def invalidate_row_height(self, row: int) -> None:
        pass

    def measure_slice_rows(self) -> tuple[tuple, int, QFont, int] | None:
        return None

    def backing_device(self) -> QWidget | None:
        return None


class RowDocumentStore(ABC):
    """Caches prepared row formatting, laid-out `QTextDocument`s, and per-row heights without
    `QStyledItemDelegate` or `QModelIndex` overhead."""

    MAX_PREPARED_ROWS = 10_000
    MAX_DOCUMENTS = 500
    ROW_PADDING = 0
    MEASURE_SLICE_SECONDS = 0.008

    def __init__(self) -> None:
        self.view: DetachedCanvas | VirtualRowCanvas = DetachedCanvas()
        self.preparing = True
        self._stopped = False
        self._scroll_paused = False
        self._prepared: OrderedDict[Hashable, RowFormatting] = OrderedDict()
        self._pending: set[Hashable] = set()
        self._documents: OrderedDict[tuple[Hashable, int], QTextDocument] = OrderedDict()
        self._metrics: OrderedDict[Hashable, dict[int, RowMetrics]] = OrderedDict()
        self._viewport_update_timer = QTimer()
        self._viewport_update_timer.setSingleShot(True)
        self._viewport_update_timer.setInterval(16)
        self._viewport_update_timer.timeout.connect(self._update_viewport)
        self._row_sizes: list[RowSize | None] = []
        self._row_size_keys: dict[Hashable, list[RowSize]] = {}
        self._row_sizes_for: Hashable = None
        self._row_sizes_font: QFont = QFont()
        self._est_metrics: tuple[str, int, int] | None = None
        self._unmeasured: set[int] = set()
        self._measure_timer = QTimer()
        self._measure_timer.setSingleShot(True)
        self._measure_timer.setInterval(0)
        self._measure_timer.timeout.connect(self._measure_slice)
        self._arrivals_moved_rows = False
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._application_state_changed)

    def bind_view(self, view: VirtualRowCanvas) -> None:
        self.view = view
        self._viewport_update_timer.setParent(view)
        self._measure_timer.setParent(view)

    def set_scroll_paused(self, paused: bool) -> None:
        """Pause background off-screen row measurement during active finger drag or fling."""
        if self._scroll_paused == paused:
            return
        self._scroll_paused = paused
        if not paused and self._unmeasured and not self._measure_timer.isActive():
            self._measure_timer.start()

    @abstractmethod
    def row_key(self, fragment) -> Hashable: ...

    @abstractmethod
    def row_text(self, fragment) -> str: ...

    @abstractmethod
    def preparation_key_for(self, fragment, font: QFont, width: int) -> Hashable: ...

    @abstractmethod
    def preparation_for(self, fragment, font: QFont, width: int): ...

    @abstractmethod
    def background_qcolor(self) -> QColor: ...

    @abstractmethod
    def paint_row(self, painter: QPainter, row: int, fragment, rect: QRect, clip_region: QRegion | None) -> None: ...

    def begin_paint(self, painter: QPainter, viewport_rect: QRect, *, animating: bool = False) -> None:
        """Optional per-frame hook invoked once before `paint_row` runs over visible rows."""

    def end_paint(self) -> None:
        """Paired cleanup hook invoked after the visible-row `paint_row` loop."""

    def text_width(self, width: int) -> float:
        return width

    def stop_preparation(self) -> None:
        pass

    @cached_property
    def preparer(self) -> RowPreparer:
        return self.row_preparer()

    def row_preparer(self) -> RowPreparer:
        return ThreadRowPreparer(self._rows_prepared, self.view.backing_device())

    def keyed_formatting(self, key: Hashable, text: str, prepare) -> RowFormatting:
        if key in self._prepared:
            self._prepared.move_to_end(key)
            return self._prepared[key]
        if self.preparing and key not in self._pending:
            self._pending.add(key)
            self.preparer.prepare(key, prepare)
        return PendingRow(text)

    def _key_metrics(self, key: Hashable) -> dict[int, RowMetrics]:
        widths = self._metrics.get(key)
        if widths is not None:
            self._metrics.move_to_end(key)
            return widths
        widths = {}
        self._metrics[key] = widths
        if len(self._metrics) > self.MAX_PREPARED_ROWS:
            evicted, evicted_widths = self._metrics.popitem(last=False)
            for width in evicted_widths:
                self._documents.pop((evicted, width), None)
        return widths

    def _record_measured_size(self, key: Hashable, width: int, size: QSize) -> None:
        widths = self._key_metrics(key)
        entry = widths.get(width)
        if entry is None:
            widths[width] = RowMetrics(size=size)
        else:
            entry.size = size

    def _drop_key_metrics(self, key: Hashable) -> None:
        widths = self._metrics.pop(key, None)
        if widths is not None:
            for width in widths:
                self._documents.pop((key, width), None)

    def measured_size_for(self, key: Hashable, width: int) -> QSize | None:
        widths = self._metrics.get(key)
        if widths is None:
            return None
        entry = widths.get(width)
        return None if entry is None else entry.size

    def measured_count(self) -> int:
        return sum(1 for widths in self._metrics.values() for entry in widths.values() if entry.size is not None)

    def new_document(self, font: QFont, width: int) -> QTextDocument:
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(font)
        document.setTextWidth(self.text_width(width))
        return document

    def laid_out(
        self, key: Hashable, font: QFont, width: int, formatting: RowFormatting
    ) -> QTextDocument:
        cache_key = (key, width)
        document = self._documents.get(cache_key)
        if document is not None:
            self._documents.move_to_end(cache_key)
            return document
        document = self.new_document(font, width)
        formatting.fill(document)
        self._documents[cache_key] = document
        widths = self._key_metrics(key)
        entry = widths.get(width)
        if entry is None:
            entry = widths[width] = RowMetrics()
        # `document.size().width()` already reports the intrinsic laid-out width of unwrapped
        # `<pre>` / `white-space:pre` / `<table>` blocks in one pass, avoiding the full second
        # layout pass of `QTextDocument::idealWidth()`.
        extent = math.ceil(document.size().width())
        if extent > width:
            entry.extent = extent
        if len(self._documents) > self.MAX_DOCUMENTS:
            self._documents.popitem(last=False)
        return document

    def row_extent(self, key: Hashable, width: int) -> int:
        widths = self._metrics.get(key)
        if widths is None:
            return width
        entry = widths.get(width)
        return width if entry is None or entry.extent is None else entry.extent

    def measured_height(self, key: Hashable, font: QFont, width: int, formatting: RowFormatting) -> int:
        size = self.measured_size_for(key, width)
        if size is not None:
            return size.height()
        formatting = formatting.resolved()
        if not formatting.final:
            return formatting.estimated_height(font, self.text_width(width)) + self.ROW_PADDING
        document = self.laid_out(key, font, width, formatting)
        size = QSize(width, math.ceil(document.size().height()) + self.ROW_PADDING)
        self._record_measured_size(key, width, size)
        return size.height()

    def estimated_size(self, fragment, font: QFont, width: int) -> QSize:
        font_key = font.key()
        cached = self._est_metrics
        if cached is None or cached[0] != font_key:
            metrics = QFontMetrics(font)
            char_w = max(1, metrics.averageCharWidth())
            line_h = max(1, metrics.lineSpacing())
            cached = (font_key, char_w, line_h)
            self._est_metrics = cached
        _fk, char_w, line_h = cached
        text = self.row_text(fragment)
        if not text:
            return QSize(width, line_h + self.ROW_PADDING)
        cols = max(1, int(self.text_width(width) // char_w))
        lines = sum(max(1, (len(line) + cols - 1) // cols) for line in text.split("\n"))
        return QSize(width, lines * line_h + self.ROW_PADDING)

    def _rows_prepared(self, batch: list[tuple[Hashable, RowFormatting]]) -> None:
        if self._stopped:
            return
        for key, prepared in batch:
            self._row_prepared(key, prepared)

    def _row_prepared(self, key: Hashable, prepared: RowFormatting) -> None:
        if self._stopped:
            return
        awaited = key in self._pending
        self._pending.discard(key)
        self._prepared[key] = prepared
        if len(self._prepared) > self.MAX_PREPARED_ROWS:
            evicted, _ = self._prepared.popitem(last=False)
            self._drop_key_metrics(evicted)
        self._drop_key_metrics(key)
        if self._moves_rows(key, prepared, awaited):
            self._arrivals_moved_rows = True
        if not self._viewport_update_timer.isActive():
            self._viewport_update_timer.start()

    def _moves_rows(self, key: Hashable, prepared: RowFormatting, awaited: bool) -> bool:
        kept_sizes = self._row_size_keys.pop(key, ())
        moves = awaited and not kept_sizes
        for kept in kept_sizes:
            size = kept.size
            if size is None:
                continue
            if kept.estimated or self.measured_height(key, kept.font, size.width(), prepared) != size.height():
                kept.size = None
                moves = True
                self.view.invalidate_row_height(kept.row)
            else:
                self._row_size_keys.setdefault(key, []).append(kept)
        return moves

    def _update_viewport(self) -> None:
        moved, self._arrivals_moved_rows = self._arrivals_moved_rows, False
        if moved:
            self.view.rows_changed()
        else:
            self.view.rows_repainted()

    def _application_state_changed(self, state: Qt.ApplicationState) -> None:
        if state is Qt.ApplicationState.ApplicationSuspended:
            self.release_documents()

    def release_documents(self) -> None:
        self._documents.clear()

    def width_changed(self) -> None:
        self.release_documents()
        self._metrics.clear()
        self.forget_row_sizes()

    def forget_row_sizes(self) -> None:
        self._row_sizes = []
        self._row_size_keys.clear()
        self._row_sizes_for = None
        self._unmeasured.clear()

    def ensure_row_sizes(self, font: QFont, width: int, count: int) -> None:
        layout = (font.key(), width)
        if layout != self._row_sizes_for or len(self._row_sizes) != count:
            self._row_sizes = [None] * count
            self._row_size_keys.clear()
            self._row_sizes_for = layout
            self._row_sizes_font = QFont(font)
            self._unmeasured.clear()

    def splice_row_sizes(self, head: int, removed: int, added: int, changed: int) -> None:
        if self._row_sizes_for is None:
            return
        sizes = self._row_sizes
        if removed > changed:
            del_start = head + changed
            del_end = head + removed
            for kept in sizes[del_start:del_end]:
                self._unkeep(kept)
            del sizes[del_start:del_end]
        if added > changed:
            ins_at = head + changed
            sizes[ins_at:ins_at] = [None] * (added - changed)
        for row in range(head, min(head + changed, len(sizes))):
            self._unkeep(sizes[row])
            sizes[row] = None
        # Re-index surviving kept.row indices after splice
        if removed != added:
            for idx in range(head, len(sizes)):
                kept = sizes[idx]
                if kept is not None:
                    kept.row = idx
            self._unmeasured = {r for r in self._unmeasured if r < head}

    def mark_rows_changed(self, rows: Iterator[int]) -> None:
        sizes = self._row_sizes
        for row in rows:
            if 0 <= row < len(sizes):
                self._unkeep(sizes[row])
                sizes[row] = None

    def _unkeep(self, kept: RowSize | None) -> None:
        if kept is None:
            return
        under = self._row_size_keys.get(kept.key)
        if under is None:
            return
        try:
            under.remove(kept)
        except ValueError:
            return
        if not under:
            del self._row_size_keys[kept.key]

    def keep_row_size(self, row: int, key: Hashable, size: QSize, font: QFont, *, estimated: bool = False) -> None:
        sizes, layout = self._row_sizes, self._row_sizes_for
        if layout is None or row >= len(sizes) or size.width() != layout[1]:
            return
        self._unkeep(sizes[row])
        kept = RowSize(key, size, self._row_sizes_font, estimated, row)
        sizes[row] = kept
        self._row_size_keys.setdefault(key, []).append(kept)

    def kept_size(self, row: int, *, measured: bool = False) -> QSize | None:
        if row < 0 or row >= len(self._row_sizes):
            return None
        kept = self._row_sizes[row]
        if kept is None or kept.size is None or (measured and kept.estimated):
            return None
        return kept.size

    def kept_row(self, row: int, *, measured: bool = False) -> RowSize | None:
        if row < 0 or row >= len(self._row_sizes):
            return None
        kept = self._row_sizes[row]
        if kept is None or kept.size is None or (measured and kept.estimated):
            return None
        return kept

    def hinted_width(self, key: Hashable, layout_width: int) -> int:
        return layout_width

    def measure_row(self, row: int, fragment, font: QFont, width: int, *, allow_estimate: bool) -> tuple[int, int, bool]:
        """Return `(height, extent_width, is_estimated)` for `row` at `width`."""
        if not fragment.has_blocks:
            return 0, width, False
        kept = self.kept_row(row, measured=not allow_estimate)
        if kept is not None and kept.size is not None:
            return kept.size.height(), self.hinted_width(kept.key, width), kept.estimated
        key = self.preparation_key_for(fragment, font, width)
        size = self.measured_size_for(key, width)
        if size is not None:
            self.keep_row_size(row, key, size, font, estimated=False)
            return size.height(), self.hinted_width(key, width), False
        if allow_estimate:
            self._unmeasured.add(row)
            if not self._scroll_paused and not self._measure_timer.isActive():
                self._measure_timer.start()
            est = self.estimated_size(fragment, font, width)
            self.keep_row_size(row, key, est, font, estimated=True)
            return est.height(), width, True
        document = self.final_document_for(fragment, font, width)
        if document is None:
            est = self.estimated_size(fragment, font, width)
            return est.height(), width, True
        height = math.ceil(document.size().height()) + self.ROW_PADDING
        size = QSize(width, height)
        if key in self._prepared:
            self._record_measured_size(key, width, size)
        self.keep_row_size(row, key, size, font, estimated=False)
        return height, self.hinted_width(key, width), False

    @abstractmethod
    def final_document_for(self, fragment, font: QFont, width: int) -> QTextDocument | None: ...

    def row_document_for(self, fragment, font: QFont, width: int) -> QTextDocument:
        document = self.final_document_for(fragment, font, width)
        if document is None:
            document = self.new_document(font, width)
            document.setPlainText(self.row_text(fragment))
        return document

    def _measure_slice(self) -> None:
        if self._stopped or self._scroll_paused:
            return
        target = self.view.measure_slice_rows()
        if target is None or not self._unmeasured:
            self._unmeasured.clear()
            return
        fragments, reader, font, width = target
        count = len(fragments)
        waiting = sorted((row for row in self._unmeasured if 0 <= row < count),
                         key=lambda row: abs(row - reader))
        self._unmeasured.clear()
        self.ensure_row_sizes(font, width, count)
        started, measured = time.monotonic(), False
        while waiting and time.monotonic() - started < self.MEASURE_SLICE_SECONDS:
            row = waiting.pop(0)
            if self.kept_size(row, measured=True) is None:
                h, ext, est = self.measure_row(row, fragments[row], font, width, allow_estimate=False)
                if not est:
                    self.view._set_row_geometry(row, h, ext, False)
                    measured = True
        for row in waiting:
            self._unmeasured.add(row)
        if measured:
            self.view.rows_changed()
        if self._unmeasured and not self._scroll_paused:
            self._measure_timer.start()

    def forget_rows(self) -> None:
        self._prepared.clear()
        self._pending.clear()
        self.width_changed()

    def cleanup(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.preparing = False
        self._viewport_update_timer.stop()
        self._measure_timer.stop()
        self.preparer.clear()
        self.stop_preparation()
        self.preparer.stop()
        self._pending.clear()


class FragmentRowList:
    """Flat list of shown fragments with O(1) key->row lookup and minimal head/tail diffing
    (replaces `HistoryRows(QAbstractListModel)` with zero Qt model-index overhead)."""

    def __init__(self, canvas: VirtualRowCanvas) -> None:
        self._canvas = canvas
        self.fragments: tuple = ()
        self._rows: dict = {}

    def rowCount(self) -> int:
        return len(self.fragments)

    def row_of(self, key: object) -> int:
        return self._rows.get(key, -1)

    def show(self, fragments: tuple) -> None:
        old = self.fragments
        same = min(len(old), len(fragments))
        head = next((row for row in range(same) if old[row] is not fragments[row]), same)
        tail = 0
        while tail < same - head and old[-1 - tail] is fragments[-1 - tail]:
            tail += 1
        removed, added = len(old) - head - tail, len(fragments) - head - tail
        if removed == 0 and added == 0:
            return
        changed = min(removed, added)
        self._set(fragments, head)
        self._canvas._rows_spliced(head, removed, added, changed)

    def _set(self, fragments: tuple, first: int) -> None:
        if fragments is self.fragments:
            return
        rows = self._rows if first else {}
        if first:
            for key in [k for k, r in rows.items() if r >= first]:
                del rows[key]
        for row in range(first, len(fragments)):
            rows.setdefault(fragments[row].key, row)
        self.fragments = fragments
        self._rows = rows

    def changed(self, fragments: tuple) -> None:
        indices = [row for fragment in fragments if (row := self.row_of(fragment.key)) >= 0]
        if indices:
            self._canvas._rows_data_changed(indices)


class VirtualRowCanvas(QAbstractScrollArea, ViewportCanvas):
    """Direct-paint, O(log N) prefix-sum virtual scroll area for variable-height rows.

    Scrolls the uncovered viewport rectangle in place (`viewport.scroll(dx, dy, clear)`)
    and repaints only rows intersecting the dirty clip rectangle — zero `QListView`
    `indexAt` scans on scroll, zero `QModelIndex` or `QStyleOptionViewItem` allocations.
    """

    END_SLACK = 10
    MEASURED_VIEWPORTS = 2

    def __init__(self, rows: RowDocumentStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows = rows
        rows.bind_view(self)
        self.model_rows = FragmentRowList(self)
        self._heights: list[int] = []
        self._extents: list[int] = []
        self._estimated: list[bool] = []
        self._offsets: list[int] = [0]
        self._dirty_offset_from = 0
        self._max_extent = 0
        self._layout_width_measured = 0
        self._layout_font_key = ""
        self._layout_pending = False
        self._layouts = 0
        self._geometry_revision = 0
        self._estimating = False
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    @property
    def geometry_revision(self) -> int:
        return self._geometry_revision

    def viewport_width(self) -> int:
        return self.viewport().width()

    def estimating(self) -> bool:
        return self._estimating

    def invalidate_row_height(self, row: int) -> None:
        if 0 <= row < len(self._heights):
            self._heights[row] = -1
            self._estimated[row] = False
            if row < self._dirty_offset_from:
                self._dirty_offset_from = row

    def measure_slice_rows(self) -> tuple[tuple, int, QFont, int] | None:
        fragments = self.model_rows.fragments
        if not fragments:
            return None
        return fragments, self.reader_row(), self.font(), self.viewport_width() or 800

    def backing_device(self) -> QWidget:
        return self

    def _ensure_offsets(self) -> None:
        heights = self._heights
        count = len(heights)
        offsets = self._offsets
        if len(offsets) != count + 1:
            if len(offsets) < count + 1:
                offsets.extend([0] * (count + 1 - len(offsets)))
            else:
                del offsets[count + 1:]
        start = min(self._dirty_offset_from, count)
        if start <= count:
            acc = offsets[start] if start > 0 else 0
            if start == 0:
                offsets[0] = 0
            for i in range(start, count):
                h = heights[i]
                acc += h if h > 0 else 0
                offsets[i + 1] = acc
            self._dirty_offset_from = count + 1

    def total_height(self) -> int:
        self._ensure_offsets()
        return self._offsets[-1]

    def _set_row_geometry(self, row: int, height: int, extent: int, estimated: bool) -> None:
        if 0 <= row < len(self._heights):
            if self._heights[row] != height:
                self._heights[row] = height
                if row < self._dirty_offset_from:
                    self._dirty_offset_from = row
            self._extents[row] = extent
            self._estimated[row] = estimated
            if extent > self._max_extent:
                self._max_extent = extent

    def _rows_spliced(self, head: int, removed: int, added: int, changed: int) -> None:
        self.rows.splice_row_sizes(head, removed, added, changed)
        if removed > changed:
            del_start, del_end = head + changed, head + removed
            del self._heights[del_start:del_end]
            del self._extents[del_start:del_end]
            del self._estimated[del_start:del_end]
        if added > changed:
            ins_at = head + changed
            n = added - changed
            self._heights[ins_at:ins_at] = [-1] * n
            self._extents[ins_at:ins_at] = [0] * n
            self._estimated[ins_at:ins_at] = [False] * n
        for row in range(head, head + changed):
            self._heights[row] = -1
            self._extents[row] = 0
            self._estimated[row] = False
        if head < self._dirty_offset_from:
            self._dirty_offset_from = head
        self._geometry_revision += 1
        self._layout_pending = True

    def _rows_data_changed(self, indices: list[int]) -> None:
        self.rows.mark_rows_changed(iter(indices))
        for row in indices:
            if 0 <= row < len(self._heights):
                self._heights[row] = -1
                self._extents[row] = 0
                self._estimated[row] = False
                if row < self._dirty_offset_from:
                    self._dirty_offset_from = row
        self._geometry_revision += 1
        self._layout_pending = True

    def row_at_y(self, content_y: int) -> int:
        """Index of the row spanning `content_y` (content coordinates), or -1 when empty."""
        count = len(self._heights)
        if count == 0:
            return -1
        self._ensure_offsets()
        total = self._offsets[count]
        if total <= 0 or content_y < 0 or content_y >= total:
            return -1
        row = bisect_right(self._offsets, content_y) - 1
        if row < 0:
            return 0
        if row >= count:
            return count - 1
        # Collapsed trailing parts have height 0; bisect_right lands on the first positive-height
        # row sharing the same offset (or the last 0-height row at the boundary).
        while row < count - 1 and self._heights[row] <= 0:
            row += 1
        return row

    def row_at_point(self, point: QPoint) -> int:
        """Index of the row under viewport point `point`, or -1."""
        if not self.viewport().rect().contains(point):
            return -1
        return self.row_at_y(self.verticalScrollBar().value() + point.y())

    def row_rect(self, row: int) -> QRect:
        """Viewport-coordinate rectangle of `row` in O(1)."""
        if row < 0 or row >= len(self._heights):
            return QRect()
        self._ensure_offsets()
        h = self._heights[row]
        if h <= 0:
            return QRect()
        vp_w = self.viewport().width()
        w = max(vp_w, self._extents[row])
        top = self._offsets[row] - self.verticalScrollBar().value()
        left = -self.horizontalScrollBar().value()
        return QRect(left, top, w, h)

    def update_row(self, row: int, extra_bottom: int = 0) -> None:
        """Invalidate only `row`'s visible rectangle in the viewport (plus `extra_bottom`
        pixels below it while a local upward arrival slide is running)."""
        rect = self.row_rect(row)
        if not rect.isEmpty():
            if extra_bottom > 0:
                rect = rect.adjusted(0, 0, 0, extra_bottom)
            clipped = rect.intersected(self.viewport().rect())
            if not clipped.isEmpty():
                self.viewport().update(clipped)

    def scroll_to_row(self, row: int) -> None:
        """Scroll so `row` starts at the top of the viewport."""
        if row < 0 or row >= len(self._heights):
            return
        self.execute_layout()
        self._ensure_offsets()
        bar = self.verticalScrollBar()
        bar.setValue(min(bar.maximum(), max(bar.minimum(), self._offsets[row])))

    def schedule_layout(self) -> None:
        self._layout_pending = True

    def execute_layout(self) -> None:
        if self._layout_pending or self._dirty_offset_from <= len(self._heights):
            self.do_layout()

    @property
    def at_end(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - self.END_SLACK

    @property
    def at_start(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() <= bar.minimum()

    def follow_end(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    @contextmanager
    def keeping_end(self) -> Iterator[None]:
        was_at_end = self.at_end
        yield
        if was_at_end:
            self.execute_layout()
            self.follow_end()

    @contextmanager
    def holding_position(self) -> Iterator[None]:
        top_row = self.row_at_y(self.verticalScrollBar().value())
        key = self.model_rows.fragments[top_row].key if 0 <= top_row < len(self.model_rows.fragments) else None
        offset = self.row_rect(top_row).top() if key is not None else 0
        yield
        if key is None:
            return
        self.execute_layout()
        new_row = self.model_rows.row_of(key)
        if new_row < 0:
            return
        moved = self.row_rect(new_row).top() - offset
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + moved)

    def reader_row(self) -> int:
        count = len(self.model_rows.fragments)
        if count == 0:
            return 0
        if self.at_end:
            return count - 1
        top = self.row_at_y(self.verticalScrollBar().value())
        return top if top >= 0 else count - 1

    def do_layout(self) -> None:
        """Measure rows within `MEASURED_VIEWPORTS` of the reader, estimate the rest,
        rebuild dirty prefix sums, and sync scroll bar ranges."""
        self._layout_pending = False
        fragments = self.model_rows.fragments
        count = len(fragments)
        if count == 0:
            self._heights.clear()
            self._extents.clear()
            self._estimated.clear()
            self._offsets = [0]
            self._dirty_offset_from = 1
            self._max_extent = 0
            self._sync_scrollbars()
            self._layouts += 1
            return
        font = self.font()
        width = self.viewport_width() or 800
        font_key = font.key()
        if width != self._layout_width_measured or font_key != self._layout_font_key or len(self._heights) != count:
            self._heights = [-1] * count
            self._extents = [0] * count
            self._estimated = [False] * count
            self._dirty_offset_from = 0
            self._max_extent = width
            self._layout_width_measured = width
            self._layout_font_key = font_key
        self.rows.ensure_row_sizes(font, width, count)
        reader = min(count - 1, max(0, self.reader_row()))
        reach = self.MEASURED_VIEWPORTS * max(1, self.viewport().height())
        # Measure rows near the reader synchronously so visible and adjacent rows are exact.
        for seq in (range(reader, count), range(reader - 1, -1, -1)):
            covered = 0
            for row in seq:
                if covered >= reach:
                    break
                if self._heights[row] < 0 or self._estimated[row]:
                    h, ext, est = self.rows.measure_row(row, fragments[row], font, width, allow_estimate=False)
                    self._set_row_geometry(row, h, ext, est)
                covered += max(0, self._heights[row])
        # Estimate any remaining unmeasured rows away from the reader (measured between frames).
        self._estimating = True
        try:
            for row in range(count):
                if self._heights[row] < 0:
                    h, ext, est = self.rows.measure_row(row, fragments[row], font, width, allow_estimate=True)
                    self._set_row_geometry(row, h, ext, est)
        finally:
            self._estimating = False
        self._ensure_offsets()
        self._max_extent = max(width, max(self._extents, default=width))
        self._sync_scrollbars()
        self._layouts += 1

    def _sync_scrollbars(self) -> None:
        vp = self.viewport()
        vp_h = max(1, vp.height())
        vp_w = max(1, vp.width())
        total_h = self.total_height()
        vbar = self.verticalScrollBar()
        vbar.setPageStep(vp_h)
        vbar.setSingleStep(max(16, vp_h // 12))
        vbar.setRange(0, max(0, total_h - vp_h))
        hbar = self.horizontalScrollBar()
        hbar.setPageStep(vp_w)
        hbar.setSingleStep(20)
        hbar.setRange(0, max(0, self._max_extent - vp_w))

    def rows_changed(self) -> None:
        with self.keeping_end() if self.at_end else self.holding_position():
            self.schedule_layout()
        self.viewport().update()

    def rows_repainted(self) -> None:
        self.viewport().update()

    def floating_over(self) -> list[QRect]:
        viewport = self.viewport()
        area = viewport.geometry()
        return [
            child.geometry().intersected(area).translated(-area.topLeft())
            for child in self.children()
            if isinstance(child, QWidget) and child is not viewport and child.isVisible()
            and child.geometry().intersects(area)
        ]

    @staticmethod
    def uncovered(rect: QRect, covers: list[QRect]) -> QRect:
        for cover in sorted(covers, key=lambda c: c.width() * c.height(), reverse=True):
            if not rect.intersects(cover):
                continue
            left, top, width, height = rect.left(), rect.top(), rect.width(), rect.height()
            bands = (
                QRect(left, top, width, cover.top() - top),
                QRect(left, cover.bottom() + 1, width, rect.bottom() - cover.bottom()),
                QRect(left, top, cover.left() - left, height),
                QRect(cover.right() + 1, top, rect.right() - cover.right(), height),
            )
            rect = max(bands, key=lambda band: max(0, band.width()) * max(0, band.height()))
            if rect.width() <= 0 or rect.height() <= 0:
                return QRect()
        return rect

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802 - Qt virtual method name
        viewport = self.viewport()
        covers = self.floating_over()
        clear = self.uncovered(viewport.rect(), covers) if covers and not dx else QRect()
        if clear.isEmpty():
            viewport.scroll(dx, dy)
            return
        viewport.scroll(dx, dy, clear)
        viewport.update(QRegion(viewport.rect()).subtracted(QRegion(clear)))

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if self._layout_pending:
            self.do_layout()
        viewport = self.viewport()
        vp_rect = viewport.rect()
        dirty = event.region()
        clip = dirty.boundingRect().intersected(vp_rect)
        if clip.isEmpty():
            return
        painter = QPainter(viewport)
        try:
            bg_color = self.rows.background_qcolor()
            fragments = self.model_rows.fragments
            count = len(fragments)
            if count == 0:
                painter.fillRect(clip, bg_color)
                return
            self._ensure_offsets()
            scroll_y = self.verticalScrollBar().value()
            scroll_x = self.horizontalScrollBar().value()
            vp_w = vp_rect.width()
            total_h = self._offsets[count]
            top_y = scroll_y + clip.top()
            bot_y = scroll_y + clip.bottom()
            animating = self.has_active_arrivals
            slide_pad = int(math.ceil(self.arrival_slide_distance)) if animating else 0
            if top_y >= total_h + slide_pad:
                painter.fillRect(clip, bg_color)
                return
            if animating:
                # Clear once before painting arriving rows so semi-transparent tiles and local
                # upward slide offsets never ghost or erase sibling rows in the same burst.
                painter.fillRect(clip, bg_color)
            first = max(0, bisect_right(self._offsets, max(0, top_y - slide_pad)) - 1)
            last = min(count - 1, bisect_right(self._offsets, min(total_h - 1, bot_y)) - 1)
            last_bottom = -1
            self.rows.begin_paint(painter, vp_rect, animating=animating)
            try:
                for row in range(first, last + 1):
                    h = self._heights[row]
                    if h <= 0:
                        continue
                    y = self._offsets[row] - scroll_y
                    if y > clip.bottom():
                        break
                    if y + h + slide_pad - 1 < clip.top():
                        continue
                    row_w = max(vp_w, self._extents[row])
                    rect = QRect(-scroll_x, y, row_w, h)
                    self.rows.paint_row(painter, row, fragments[row], rect, dirty)
                    last_bottom = y + h
            finally:
                self.rows.end_paint()
            # Fill any empty area below the final row (or above row 0 on overscroll) when
            # not already pre-cleared for an active arrival.
            if not animating:
                if last_bottom >= 0 and last_bottom <= clip.bottom():
                    painter.fillRect(QRect(clip.left(), max(clip.top(), last_bottom), clip.width(), clip.bottom() - max(clip.top(), last_bottom) + 1), bg_color)
                elif last_bottom < 0:
                    painter.fillRect(clip, bg_color)
        finally:
            painter.end()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        if event.size().width() != event.oldSize().width():
            self.rows.width_changed()
            self._layout_width_measured = 0
            self._layout_pending = True
        super().resizeEvent(event)
        if self._layout_pending:
            self.do_layout()
        else:
            self._sync_scrollbars()
