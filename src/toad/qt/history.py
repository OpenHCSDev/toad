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
from abc import ABC, abstractmethod

import shiboken6
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterator, Hashable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, replace
from functools import cached_property, partial
from math import ceil, copysign
from pathlib import Path
from time import monotonic
from typing import ClassVar
from weakref import WeakSet

from metaclass_registry.mro_dispatch import handles
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QDesktopServices, QFont, QFontMetrics, QFontMetricsF, QImage, QPainter, QPalette, QPen, QPixmap, QRegion, QScrollEvent, QTextDocument
from PySide6.QtWidgets import QApplication, QPushButton, QScroller, QScrollerProperties, QWidget
from pyqt_reactive.widgets.virtual_rows import HtmlRow, RowFormatting, RowPreparer
from toad.core.link_context_changed import CoreEventStream
from toad.qt.virtual_scroll import (
    FragmentRowList,
    NO_TAP_HIGHLIGHT,
    PinnedHeaderTapHighlight,
    PinnedLinkTapHighlight,
    RowDocumentStore,
    RowHeaderTapHighlight,
    RowLinkTapHighlight,
    TapHighlight,
    VirtualRowCanvas,
)
from toad.arrivals import AnimatesArrivals, SETTLED_ARRIVAL, ViewportArrivalState
from toad.client.application import ClientApplication
from toad.client.pending import AwaitsFirstPage
from toad.client.view_settings import SettingsReading
from toad.qt.finger_press import FingerPress, Press
from toad.client.fragments import BusMessageHistoryFragment, FragmentCollapse, HistoryFragment, Shown
from toad.core.projection import MroProjection
from toad.link_opening import TogglesFragmentShown
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
from toad.client.line_blocks import BlockPreparation, Divider, LineBlock, LineLink
from toad.client.history_changes import HeaderPin, PinnedHeader, PinsMessageHeader, TopPage
from toad.client.history_preparation import HistorySourceSnapshot
from toad.client.history_state import LiveTranscript
from toad.client.prepared_pages import (
    ClosedHistory, HoldsRows, MeasuresFragments, PreparedTranscriptPage, RowsAsked,
)
from toad.client.reader_position import (
    FragmentLocation, FragmentPosition, ReaderPage, ReaderPosition, RowPosition, TailPosition,
    UnloadedFragment,
)
from toad.history_jump import FollowsTail, JumpsToLatest, PagedReader
from toad.no_worker import NoTask
from toad.qt.live_turn import QtLiveBlock
from toad.qt.workspace_frame import QtWorkspaceHosted
from toad.markdown_links import LinkContext
from toad.qt.float_layer import QtFloatLayer
from toad.qt.hints import QtCallbackHintTarget, QtHintTargetSource
from toad.qt.lines import QtLineRenderer
from toad.patch import PREFORMATTED, DiffSettings
from toad.reader_actions import ReaderAction
from toad.view_actions import LatestJumpBar, ShowsLatestJumpBar
from toad.qt.widget_animation import DisplayScreen, frame_interval
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
from ui_theme.scheme import BackgroundColour, ColourScheme, ForegroundColour, PrimaryColour, SurfaceHoverColour

class QtPage(ReaderPage):
    """One prepared page, drawn as the rows of the fragments in its range that its history
    shows. The rows themselves live in the window's model, read from the pages."""

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


class BackingFormatWidget(ABC):
    """Widget whose backing store may choose the row image format."""

    @abstractmethod
    def backing_image_format(self) -> QImage.Format:
        ...

    @classmethod
    def from_optional(cls, value: QWidget | None) -> BackingFormatWidget:
        return AbsentBackingFormatWidget() if value is None else HeldBackingFormatWidget(value)


@dataclass(frozen=True)
class AbsentBackingFormatWidget(BackingFormatWidget):
    """Absent `BackingFormatWidget` carrying no value."""

    def backing_image_format(self) -> QImage.Format:
        return QImage.Format.Format_ARGB32_Premultiplied


@dataclass(frozen=True)
class HeldBackingFormatWidget(BackingFormatWidget):
    """Held `BackingFormatWidget` carrying its present value."""

    value: QWidget

    def backing_image_format(self) -> QImage.Format:
        backing = self.value.backingStore()
        if backing is not None:
            paint_device = backing.paintDevice()
            if isinstance(paint_device, QImage) and paint_device.format() != QImage.Format.Format_Invalid:
                return paint_device.format()
        return QImage.Format.Format_ARGB32_Premultiplied


class HistoryRowDelegate(HoldsRows, RowDocumentStore):
    """Each fragment's line blocks as Qt rich text, rendered on the worker pool at the row's
    width (dividers fill it); a row paints plain text until prepared, and cached `QImage` tiles
    once prepared. Active tap highlights paint the tapped row's live `QTextDocument` with
    inverted character selections directly over the clicked text instead of drawing boxes.
    `ROW_PADDING = 0` is inherited from `RowDocumentStore` so message parts meet seamlessly."""

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
        self._colour_cache: tuple[ColourScheme, str, QColor, QColor] | None = None
        self._font_metrics_cache: tuple[QFont, float, int] | None = None
        self._font_spec_cache: tuple[QFont, str, float] | None = None
        self._backing_format_cache: tuple[int, int, QImage.Format] | None = None
        self._frame_paint: tuple[QWidget | None, QFont, float, QImage.Format, str, QColor, QColor, str, float, int] | None = None
        self._frame_source_mode = False
        self._frame_dirty: tuple[QRegion | None, QRect | None, QRegion | None] = (None, None, None)
        self._tile_paint_context = QAbstractTextDocumentLayout.PaintContext()
        self._fast_docs: dict[tuple[int, int], tuple[HistoryFragment, int, str, float, QTextDocument]] = {}

    @staticmethod
    def _backing_image_format(widget: BackingFormatWidget, painter: QPainter) -> QImage.Format:
        """Match the live backing store's `QImage.Format` (e.g. `ARGB32_Premultiplied` on
        Android `QRhiBackingStore`, `RGB32` on offscreen) so `CompositionMode_Source` tile
        blits hit Qt's zero-conversion memcpy fast path instead of spawning 4-thread raster
        format conversion."""
        device = painter.device()
        if isinstance(device, QImage) and device.format() != QImage.Format.Format_Invalid:
            return device.format()
        return widget.backing_image_format()

    def _font_metrics(self, font: QFont) -> tuple[float, int]:
        """Cached ``(averageCharWidth, lineSpacing)`` for ``font``, avoiding per-row and
        per-scroll-frame `QFontMetrics` / `QFontMetricsF` allocations."""
        cached = self._font_metrics_cache
        if cached is not None and cached[0] == font:
            return cached[1], cached[2]
        cell = max(1.0, QFontMetricsF(font).averageCharWidth())
        line = QFontMetrics(font).lineSpacing() or 1
        self._font_metrics_cache = (QFont(font), cell, line)
        return cell, line

    def _theme_colours(self) -> tuple[str, QColor, QColor]:
        scheme = self.renderer.scheme
        cached = self._colour_cache
        if cached is not None and cached[0] is scheme:
            return cached[1], cached[2], cached[3]
        bg_hex = BackgroundColour.rgb(scheme).hex
        bg_color = QColor(bg_hex)
        fg_color = QColor(ForegroundColour.rgb(scheme).hex)
        self._colour_cache = (scheme, bg_hex, bg_color, fg_color)
        return bg_hex, bg_color, fg_color

    def _background_colour(self) -> tuple[str, QColor]:
        bg_hex, bg_color, _fg = self._theme_colours()
        return bg_hex, bg_color

    def background_qcolor(self) -> QColor:
        return self._theme_colours()[1]

    def foreground_qcolor(self) -> QColor:
        return self._theme_colours()[2]

    def link(self, links: LinkContext) -> bool:
        """Rows draw with these names from now on; rows prepared before are stale.
        Returns True when `links` actually changed so a parallel `acquire_links` with
        unchanged links never wipes prepared rows and flashes an already-loaded view."""
        if links == self.renderer.links:
            return False
        self.renderer = self.app_renderer.with_links(links)
        self.links_revision += 1
        # Every row's key names the links it was drawn with: none keeps its height.
        self.forget_row_sizes()
        return True

    def restyle(self) -> None:
        """The app's renderer took a new scheme or diff marks: rows draw by it from now on,
        with the names they had; rows prepared before are stale."""
        self.renderer = self.app_renderer.with_links(self.renderer.links)
        self.links_revision += 1
        self._fast_docs.clear()
        self.forget_row_sizes()

    def row_key(self, fragment: HistoryFragment):
        return fragment.key

    def row_text(self, fragment: HistoryFragment) -> str:
        return fragment.clipboard_text

    def preparation_key_for(self, fragment: HistoryFragment, font: QFont, width: int):
        return self.fragment_key(fragment, font, width)

    def preparation_for(self, fragment: HistoryFragment, font: QFont, width: int) -> QtRowPreparation:
        return self.row_preparation(fragment, font, width)

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

    def header_key(self, header: LineBlock, font: QFont, width: int):
        """A standalone block (pinned header or gap) on its own: prepared, kept and laid out as a row is."""
        return self.drawn_key(self.header_shown(header), font, width)

    @staticmethod
    def header_shown(header: LineBlock) -> tuple:
        """A standalone block's place in a key, where a row's has its fragment, look and revision."""
        return header, None, 0

    def _font_spec(self, font: QFont) -> tuple[str, float]:
        cached = self._font_spec_cache
        if cached is not None and cached[0] == font:
            return cached[1], cached[2]
        family = font.family()
        size = round(font.pointSizeF(), 2)
        self._font_spec_cache = (QFont(font), family, size)
        return family, size

    def drawn_key(self, shown: tuple, font: QFont, width: int):
        family, size = self._font_spec(font)
        return shown, self.links_revision, family, size, width

    def row_preparation(self, fragment: HistoryFragment, font: QFont, width: int) -> QtRowPreparation:
        """Data-only row work: Qt measures its monospace cell once; the worker owns HTML, of
        the row, of each leading block the pin measures on its own (the header blocks and the
        one after them) and of the header the row pins."""
        return self.block_preparation(fragment.line_blocks, font, width,
                                      headed=fragment.header_blocks + 1, pinned=fragment.pinned_dividers)

    def block_preparation(self, blocks, font: QFont, width: int, *, headed: int = 0,
                          pinned: tuple[Divider, ...] = ()) -> QtRowPreparation:
        cell, _line = self._font_metrics(font)
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

    PREFORMATTED_SHEET = (
        f"pre {{ white-space: {PREFORMATTED.css_white_space}; margin-top: 0px; margin-bottom: 4px; }} "
        "p, blockquote, ul, ol, h1, h2, h3, h4, h5, h6 { margin-top: 0px; margin-bottom: 4px; }"
    )
    """Every `pre` in a row, whoever wrote it (a highlighted fence, Markdown's own for an
    unknown language, a tool's output), is laid out as the shared declaration says, and
    block elements suppress Qt's default 12-18 px top margin so text begins directly under
    its header divider."""

    def new_document(self, font: QFont, width: int) -> QTextDocument:
        document = super().new_document(font, width)
        document.setDefaultStyleSheet(self.PREFORMATTED_SHEET)
        return document

    def layout_width(self, extent: int) -> int:
        """The width a row is laid out and prepared at: the viewport's, whatever the row's
        own extent came out as (a row with an unwrapped block is wider). `extent` only
        before the view has a viewport."""
        return self.view.viewport_width() or extent

    def hinted_width(self, key, layout_width: int) -> int:
        """Horizontal extent for `key` at `layout_width`: `layout_width` while code wraps
        (preventing 1 px header-table rounding from creating phantom horizontal scroll range),
        and the document's measured extent when wrapping is off."""
        return self.renderer.diff.wrap.fitted_width(layout_width, self.row_extent(key, layout_width))

    def fragment_height(self, fragment: HistoryFragment, font: QFont, width: int) -> int:
        """How tall a fragment's row is at this width, before the model holds it. The shared
        row measurement caches this by key and width, so a pager summing its rows' pixels
        every scrolled frame lays each row out once, not afresh on every frame."""
        if not fragment.has_blocks:
            return 0
        key = self.fragment_key(fragment, font, width)
        formatting = PreparedOnFill(lambda: self.styled_formatting(key, fragment, font, width))
        return self.measured_height(key, font, width, formatting)

    def final_document_for(self, fragment: HistoryFragment, font: QFont, width: int) -> QTextDocument | None:
        """Laid-out document for `fragment` at `width`. While a new look of a previously drawn
        row is still being prepared on the worker, returns the previous look's document cached
        under its own key so the new key's document and height caches are never polluted."""
        key = self.preparation_key_for(fragment, font, width)
        cache_key = (key, width)
        document = self._documents.get(cache_key)
        if document is not None:
            self._documents.move_to_end(cache_key)
            return document
        if key in self._prepared:
            self._prepared.move_to_end(key)
            return self.laid_out(key, font, width, self._prepared[key])
        if self.prepare_inline(fragment, font, width, key=key):
            return self.laid_out(key, font, width, self._prepared[key])
        formatting = self.keyed_formatting(key, fragment.clipboard_text, self.row_preparation(fragment, font, width))
        if formatting.final:
            return self.laid_out(key, font, width, formatting)
        shown = self.last_shown.get(self.row_identity(key))
        if shown in self._prepared:
            return self.laid_out(shown, font, width, self._prepared[shown])
        return None

    def block_row(self, fragment: HistoryFragment, font: QFont, width: int, y: int) -> tuple[int, int]:
        """Which of `fragment`'s line blocks its row draws at pixel `y`, and which line of that
        block: the unit the fragment's own header decision (`sticky_header`) reads. A block's
        height is its own rows laid out at this width, cached as the row's height is. Only the
        header blocks are measured: past them the pin is the same in every block
        (`header_blocks`), so a `y` below them answers the first block after them."""
        blocks = fragment.line_blocks
        if not blocks:
            return 0, 0
        _cell, line = self._font_metrics(font)
        if y < line:
            return 0, 0
        decided = fragment.header_blocks
        if decided == 0 and len(blocks) > 1:
            return 0, 0
        key = self.fragment_key(fragment, font, width)
        prepared = self.prepared_look(key)
        if prepared is None:
            return 0, 0
        top = 0
        for index, html in enumerate(prepared.leading):
            if index == decided and index < len(blocks) - 1:
                return index, 0
            block_key = blocks[index].standalone_cache_key(
                key, index, lambda header: self.header_key(header, font, width)
            )
            height = self.measured_height(block_key, font, width, HtmlRow(html))
            if y < top + height or index == len(blocks) - 1:
                return index, max(0, int((y - top) // line))
            top += height
        return 0, 0

    def header_pin_threshold(self, fragment: HistoryFragment, font: QFont, width: int) -> float | None:
        """Minimum pixel offset `y` inside `fragment` at which its sticky header pins
        (`(block, row) > (header_blocks - 1, 0)`), skipping layout of the last header block
        itself (`Divider` after the globally cached `Gap`)."""
        decided = fragment.header_blocks
        if decided <= 0:
            return 0.0
        _cell, line = self._font_metrics(font)
        if decided == 1:
            return line
        blocks = fragment.line_blocks
        key = self.fragment_key(fragment, font, width)
        prepared = self.prepared_look(key)
        if prepared is None:
            return None
        top = 0.0
        for index in range(min(decided - 1, len(prepared.leading))):
            block_key = blocks[index].standalone_cache_key(
                key, index, lambda header: self.header_key(header, font, width)
            )
            top += self.measured_height(block_key, font, width, HtmlRow(prepared.leading[index]))
        return top + line

    def header_document(self, header: Divider, font: QFont, width: int) -> QTextDocument | None:
        """A pinned header laid out as its row lays it out at this width. Reuses the same
        cache key as `block_row` so crossing a message during scroll lays its header out once,
        and prepares a lightweight `Divider` (`renders_inline=True`) inline on the warm
        renderer if its cache entry is cold (e.g. immediately after resize or theme switch)."""
        key = self.header_key(header, font, width)
        if key not in self._prepared and width > 0 and header.renders_inline:
            cell, _line = self._font_metrics(font)
            cols = max(1, int((width - 8) / cell))
            html = self.renderer.at_width(cols).html((header,))
            self._row_prepared(key, RenderedRow(html, (), ()))
        formatting = self.keyed_formatting(key, "", self.block_preparation((header,), font, width))
        return self.laid_out(key, font, width, formatting) if formatting.final else None

    def styled_formatting(self, key, fragment: HistoryFragment, font: QFont, width: int) -> RowFormatting:
        """The row's formatting under `key`; while a new look of a drawn row is still being
        prepared, the look it last showed. Fast-paths cached rows before computing
        `clipboard_text` or `QFontMetricsF` on every scroll paint."""
        if key in self._prepared:
            self._prepared.move_to_end(key)
            return self._prepared[key]
        if self.prepare_inline(fragment, font, width, key=key):
            return self._prepared[key]
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
        if self._fast_docs:
            self._fast_docs.clear()
        if key in self._prepared:
            self.last_shown[self.row_identity(key)] = key
            _shown, *look = key
            for header, html in prepared.pinned:
                alone = self.header_shown(header), *look
                if alone not in self._prepared:
                    super()._row_prepared(alone, RenderedRow(html, (), ()))
        if len(self.last_shown) > 2 * self.MAX_PREPARED_ROWS:
            self.last_shown = {row: shown for row, shown in self.last_shown.items() if shown in self._prepared}

    def is_prepared(self, key) -> bool:
        return key in self._prepared

    def prepare_inline(
        self, fragment: HistoryFragment, font: QFont, width: int, *, key=None,
    ) -> bool:
        """Prepare a lightweight non-Markdown row (e.g. a collapsed message's header +
        1-line summary or collapsed tool call) immediately using the already-warm
        `self.renderer` so it lays out in one frame (< 1 ms) without a RenderProcessPool
        round-trip."""
        if self._stopped or width <= 0 or not fragment.has_blocks:
            return False
        blocks = tuple(fragment.line_blocks)
        if not blocks or not all(block.renders_inline for block in blocks):
            return False
        key = self.fragment_key(fragment, font, width) if key is None else key
        if key in self._prepared:
            return True
        cell, _line = self._font_metrics(font)
        cols = max(1, int((width - 8) / cell))
        html = self.renderer.at_width(cols).html
        headed = fragment.header_blocks + 1
        pinned = fragment.pinned_dividers
        rendered = RenderedRow(
            html(blocks),
            tuple(html((block,)) for block in blocks[:headed]),
            tuple((header, html((header,))) for header in pinned),
        )
        self._row_prepared(key, rendered)
        return key in self._prepared

    TILE = 256
    """Pixels of a row's height one picture holds. A row is as tall as its message, and a
    long message's whole picture would take most of what the app may retain; in 256px tiles
    (3.3 MB at 3x DPR instead of 13.2 MB at 1024px), the cache holds ~19 tiles across rows
    instead of 4 and each tile rasterizes only its own clipped band."""

    TILE_X = 512
    """Pixels of a row's width one picture holds. Normal portrait rows fit in one column
    (zero extra tiles); wide unwrapped code/diff rows rasterize only visible columns instead
    of allocating multi-megabyte full-width slabs."""

    def release_documents(self) -> None:
        """Pictures are drawn from documents and hold them: they go with them (Android
        suspending the app, a new width)."""
        super().release_documents()
        self.pictures.clear()
        self._fast_docs.clear()
        self._backing_format_cache = None

    def _paint_tile_document(
        self, drawing: QPainter, palette: QPalette, document: QTextDocument,
        left: int, top: int, width: int, height: int,
    ) -> None:
        """Draw only the `[left, left + width] x [top, top + height]` tile of `document`
        into a tile `QImage`. Setting `context.clip` skips off-tile blocks inside Qt's layout."""
        drawing.save()
        drawing.translate(-left, -top)
        clip = QRectF(left, top, width, height)
        drawing.setClipRect(clip)
        context = self._tile_paint_context
        context.palette = palette
        context.clip = clip
        document.documentLayout().draw(drawing, context)
        drawing.restore()

    def _paint_document_direct(
        self,
        painter: QPainter,
        document: QTextDocument,
        rect: QRect,
        clip_region: QRegion | None,
        arrival: ViewportArrivalState,
        highlight: TapHighlight,
    ) -> None:
        """Paint `document` directly into `painter` through `highlight.paint_document`,
        bypassing cached tiles so tile caches stay untouched."""
        shown = clip_region.boundingRect().intersected(rect) if clip_region is not None else rect
        if shown.isEmpty():
            return
        _bg_hex, bg_color, fg_color = self._theme_colours()
        device = self.view.backing_device()
        palette = device.palette() if device is not None else QPalette()
        painter.save()
        if self._frame_source_mode:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if arrival.active:
            painter.setOpacity(arrival.opacity)
        else:
            painter.fillRect(shown, bg_color)
        painter.translate(rect.topLeft())
        local_clip = QRectF(
            shown.left() - rect.left(),
            shown.top() - rect.top(),
            shown.width(),
            shown.height(),
        )
        painter.setClipRect(local_clip)
        highlight.paint_document(painter, document, palette, bg_color, fg_color, local_clip)
        painter.restore()

    def _paint_plain_row(
        self,
        painter: QPainter,
        fragment: HistoryFragment,
        rect: QRect,
        clip_region: QRegion | None,
        arrival: ViewportArrivalState = SETTLED_ARRIVAL,
    ) -> None:
        device = self.view.backing_device()
        font = device.font() if device is not None else QFont()
        document = self.new_document(font, self.layout_width(rect.width()))
        document.setPlainText(self.row_text(fragment))
        self._paint_document_direct(painter, document, rect, clip_region, arrival, NO_TAP_HIGHLIGHT)

    def _resolve_frame_paint(
        self, painter: QPainter, viewport_width: int = 0,
    ) -> tuple[QWidget | None, QFont, float, QImage.Format, str, QColor, QColor, str, float, int]:
        device = self.view.backing_device()
        font = device.font() if device is not None else QFont()
        paint_device = painter.device()
        ratio = paint_device.devicePixelRatioF()
        cached_fmt = self._backing_format_cache
        dev_id = id(paint_device)
        wid_id = id(device)
        if cached_fmt is not None and cached_fmt[0] == dev_id and cached_fmt[1] == wid_id:
            img_format = cached_fmt[2]
        else:
            img_format = self._backing_image_format(BackingFormatWidget.from_optional(device), painter)
            self._backing_format_cache = (dev_id, wid_id, img_format)
        bg_hex, bg_color, fg_color = self._theme_colours()
        font_family, font_size = self._font_spec(font)
        layout_w = self.layout_width(viewport_width) if viewport_width else 0
        return (
            device, font, ratio, img_format, bg_hex, bg_color, fg_color,
            font_family, font_size, layout_w,
        )

    def begin_paint(
        self,
        painter: QPainter,
        viewport_rect: QRect,
        *,
        animating: bool = False,
        dirty: QRegion | None = None,
    ) -> None:
        self._frame_paint = self._resolve_frame_paint(painter, viewport_rect.width())
        self._frame_source_mode = not animating
        if dirty is not None:
            dirty_rect = dirty.boundingRect()
            multi = dirty if dirty.rectCount() > 1 else None
            self._frame_dirty = (dirty, dirty_rect, multi)
        else:
            self._frame_dirty = (None, None, None)
        if self._frame_source_mode:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)

    def end_paint(self) -> None:
        self._frame_paint = None
        self._frame_source_mode = False
        self._frame_dirty = (None, None, None)

    def paint_row(
        self, painter: QPainter, row: int, fragment: HistoryFragment, rect: QRect, clip_region: QRegion | None
    ) -> None:
        """Paint one history row from cached `QImage` tiles (or directly with inverted text
        and divider rules when this row carries the active `TapHighlight`), applying the
        viewport's unified `ViewportArrivalState` (synchronized upward slide + fade-in)."""
        if not fragment.has_blocks:
            return
        arrival = self.view.arrival_state(fragment.key, rect.height()) if self.view.has_active_arrivals else SETTLED_ARRIVAL
        paint_rect = rect.translated(0, round(arrival.offset_y)) if arrival.offset_y else rect
        # Clip an arriving non-final row to its own layout slot so its downward slide offset
        # never draws over the sibling row underneath it while the arrival animation is running.
        clip_to_slot = bool(arrival.offset_y and row + 1 < self.view.model_rows.rowCount())
        row_clip = (
            (QRegion(rect) if clip_region is None else clip_region.intersected(QRegion(rect)))
            if clip_to_slot else clip_region
        )
        highlight = self.view.tap_highlight
        if highlight.matches_row(fragment.key):
            frame = self._frame_paint
            font = frame[1] if frame is not None else (
                self.view.backing_device().font() if self.view.backing_device() is not None else QFont()
            )
            document = self.final_document_for(fragment, font, self.layout_width(paint_rect.width()))
            if document is not None:
                self._paint_document_direct(painter, document, paint_rect, row_clip, arrival, highlight)
                self.view.row_painted(fragment, paint_rect)
                return
        if not self.paint_pictures(painter, fragment, paint_rect, row_clip, arrival, clip_to_shown=clip_to_slot):
            self._paint_plain_row(painter, fragment, paint_rect, row_clip, arrival)
        self.view.row_painted(fragment, paint_rect)

    def paint_pictures(
        self,
        painter: QPainter,
        fragment: HistoryFragment,
        rect: QRect,
        clip_region: QRegion | None,
        arrival: ViewportArrivalState = SETTLED_ARRIVAL,
        *,
        clip_to_shown: bool = False,
    ) -> bool:
        """The tiles of the row that this paint shows, each drawn once into a backing-store-matched
        `QImage` and blitted with `CompositionMode_Source` on subsequent frames."""
        frame = self._frame_paint
        if frame is None:
            frame = self._resolve_frame_paint(painter)
        (
            device, font, ratio, img_format, bg_hex, bg_color, _fg_color,
            font_family, font_size, layout_w,
        ) = frame
        palette: QPalette | None = None
        width = layout_w or self.layout_width(rect.width())
        fast_key = (id(fragment), width)
        fast = self._fast_docs.get(fast_key)
        if (
            fast is not None
            and fast[0] is fragment
            and fast[1] == self.links_revision
            and fast[2] == font_family
            and fast[3] == font_size
        ):
            document = fast[4]
        else:
            cache_key = (((fragment.key, fragment.shown, fragment.revision), self.links_revision, font_family, font_size, width), width)
            document = self._documents.get(cache_key)
            if document is not None:
                self._documents.move_to_end(cache_key)
            else:
                document = self.final_document_for(fragment, font, width)
            if document is not None:
                if len(self._fast_docs) >= self.MAX_DOCUMENTS:
                    self._fast_docs.clear()
                self._fast_docs[fast_key] = (fragment, self.links_revision, font_family, font_size, document)
        if document is None and not arrival.active:
            return False
        frame_dirty, frame_dirty_rect, frame_multi = self._frame_dirty
        if clip_region is frame_dirty and frame_dirty_rect is not None and not painter.hasClipping():
            shown = frame_dirty_rect.intersected(rect)
            tile_clip = frame_multi
        else:
            effective_clip = clip_region
            if painter.hasClipping():
                painter_clip = painter.clipRegion()
                effective_clip = painter_clip if effective_clip is None else effective_clip.intersected(painter_clip)
            if effective_clip is not None:
                shown = effective_clip.boundingRect().intersected(rect)
                tile_clip = effective_clip if effective_clip.rectCount() > 1 else None
            else:
                shown = rect
                tile_clip = None
        if shown.isEmpty():
            return True
        rect_left = rect.left()
        rect_top = rect.top()
        rect_w = rect.width()
        rect_h = rect.height()
        look = (rect_w, rect_h, ratio, bg_hex, img_format)
        row_id = id(document) if document is not None else (id(self), fragment.key)
        needs_state = arrival.active or clip_to_shown or not self._frame_source_mode
        if needs_state:
            painter.save()
            if clip_to_shown:
                painter.setClipRect(shown)
            if arrival.active:
                painter.setOpacity(arrival.opacity)
            elif not self._frame_source_mode:
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        plain_doc: QTextDocument | None = None
        tile_h = self.TILE
        tile_w = self.TILE_X
        pictures_kept = self.pictures.kept
        y_start = (shown.top() - rect_top) // tile_h
        y_end = (shown.bottom() - rect_top) // tile_h
        x_start = (shown.left() - rect_left) // tile_w
        x_end = (shown.right() - rect_left) // tile_w
        for tile_y in range(y_start, y_end + 1):
            top = tile_y * tile_h
            height = min(tile_h, rect_h - top)
            draw_y = rect_top + top
            for tile_x in range(x_start, x_end + 1):
                left = tile_x * tile_w
                width = min(tile_w, rect_w - left)
                draw_x = rect_left + left
                if tile_clip is not None and not tile_clip.intersects(
                    QRect(draw_x, draw_y, width, height)
                ):
                    continue
                tile_key = (row_id, tile_y, tile_x)
                picture = pictures_kept(tile_key, look, document)
                if picture is None:
                    if palette is None:
                        palette = device.palette() if device is not None else QPalette()
                    picture = QImage(
                        max(1, round(width * ratio)),
                        max(1, round(height * ratio)),
                        img_format,
                    )
                    picture.setDevicePixelRatio(ratio)
                    picture.fill(bg_color)
                    drawing = QPainter(picture)
                    if document is not None:
                        self._paint_tile_document(drawing, palette, document, left, top, width, height)
                    else:
                        if plain_doc is None:
                            plain_doc = self.new_document(font, self.layout_width(rect_w))
                            plain_doc.setPlainText(self.row_text(fragment))
                        self._paint_tile_document(drawing, palette, plain_doc, left, top, width, height)
                    drawing.end()
                    self.pictures.keep(tile_key, look, document, picture)
                painter.drawImage(draw_x, draw_y, picture)
        if needs_state:
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
        # tile of it: (look, document, picture, weight). Holding the document keeps the one the
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
        weight = self.weight(picture.size())
        self.rows[key] = (look, document, picture, weight)
        self.bytes += weight
        while self.bytes > self.limit and len(self.rows) > 1:
            _evicted_key, evicted = self.rows.popitem(last=False)
            self.bytes -= evicted[3]

    def drop(self, key) -> None:
        entry = self.rows.pop(key, None)
        if entry is not None:
            self.bytes -= entry[3]

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


class SourceTask(asyncio.Task):
    """Source work running on the Qt event loop; the pager's states join it with wait()."""

    async def wait(self) -> None:
        await asyncio.gather(self, return_exceptions=True)


class TaskGroupKey(ABC):
    """Optional group key under which a conversation worker task was tracked."""

    def clear_group_task(self, task: SourceTask, owner: QtConversationHistory) -> None:
        pass

    @classmethod
    def from_optional(cls, value: str | None) -> TaskGroupKey:
        return AbsentTaskGroupKey() if value is None else HeldTaskGroupKey(value)


@dataclass(frozen=True)
class AbsentTaskGroupKey(TaskGroupKey):
    """Absent `TaskGroupKey` carrying no value."""


@dataclass(frozen=True)
class HeldTaskGroupKey(TaskGroupKey):
    """Held `TaskGroupKey` carrying its present value."""

    value: str

    def clear_group_task(self, task: SourceTask, owner: QtConversationHistory) -> None:
        if owner._grouped_tasks.get(self.value) is task:
            del owner._grouped_tasks[self.value]


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
        self._grouped_tasks: dict[str, SourceTask] = {}
        self._read_task: asyncio.Task | NoTask = NoTask()
        self._after_refresh_callbacks: deque[tuple[Callable, tuple[object, ...]]] = deque()
        self._after_refresh_timer = QTimer(window)
        self._after_refresh_timer.setSingleShot(True)
        self._after_refresh_timer.setInterval(0)
        self._after_refresh_timer.timeout.connect(self._flush_after_refresh)
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

    def apply_filter(self) -> None:
        """A category toggle changed the view's selection: draw the shown rows again."""
        self.window.show_pages()

    @property
    def can_draw_on_screen(self) -> bool:
        return self.state.can_draw and self.window.presenting

    def source_snapshot(self) -> HistorySourceSnapshot:
        return HistorySourceSnapshot(self._generation, self.window, self.window, self.source_identity)

    def request_preparation(self) -> None:
        self.window.request_preparation()

    def prepare_visible_pages(self) -> None:
        """Qt rows lay themselves out where drawn: no page holds committed geometry."""

    def visible_fragments(self) -> tuple[HistoryFragment, ...]:
        return self.window.visible_fragments()

    @property
    def draws_rows(self) -> bool:
        """Whether any loaded page shows at least one non-empty row — O(1) over
        `shown_fragments`, avoiding `page.line_count` -> `fragment_height` ->
        `QTextDocument.setHtml` on every scroll frame."""
        return any(fragment.has_blocks for page in self.pages for fragment in page.shown_fragments)

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

    def apply_shown(self, changes: list[tuple[HistoryFragment, Shown]]) -> None:
        """Apply a status or collapse/expand change synchronously. Lightweight inline
        looks (e.g. first collapse of a message to its header + summary) prepare directly
        with the warm renderer so first collapse lays out in one frame instead of waiting
        on a RenderProcessPool round-trip."""
        changed = tuple(fragment for fragment, shown in changes if fragment.request_show(shown))
        if changed:
            self.window.model_rows.changed(changed)
            font, width = self.window.font(), self.window.viewport_width()
            rows = self.window.rows
            needs_layout = False
            for fragment in changed:
                if not fragment.has_blocks:
                    needs_layout = True
                elif width > 0 and (
                    rows.is_prepared(rows.fragment_key(fragment, font, width))
                    or rows.prepare_inline(fragment, font, width)
                ):
                    needs_layout = True
            if needs_layout:
                self.window.rows_changed()
            else:
                self.repaint(continuing=changed)

    async def _show(self, changes: list[tuple[HistoryFragment, Shown]]) -> None:
        self.apply_shown(changes)

    def repaint(self, fragments: tuple[HistoryFragment, ...] = (), *, continuing=()) -> None:
        """Repaint only the rows the pager named. The shared contract already says which
        fragments changed; dropping that and calling viewport().update() repaints every
        visible row on every clock tick, so the message header flickered under scroll."""
        window = self.window
        model_rows = window.model_rows
        if fragments and window.isVisible():
            # Unified arrival entry point (`AnimatesArrivals`): bus messages, tool calls,
            # thinking traces, drafts, and live blocks share one fade + glide coordinator.
            window.arrive_fragments(fragments, live=False)
        for fragment in (*fragments, *continuing):
            row = model_rows.row_of(fragment.key)
            if row >= 0:
                window.update_row(row)

    def _update_edges(self) -> None:
        """Older and newer rows load as the reader nears an edge: Qt shows no edge controls."""

    async def mount(self, view: QtPage, *, before) -> None:
        """A page's rows join the window when its publication resets them."""

    async def remove_children(self, pages) -> None:
        """Retired pages' rows go with the publication's row reset."""

    def call_after_refresh(self, callback: Callable, *arguments: object) -> None:
        """Schedule `callback` on the next Qt event-loop turn using one reusable `QTimer`
        instead of allocating per-call `QTimer.singleShot` objects during scroll."""
        if self.window.widget_gone:
            return
        self._after_refresh_callbacks.append((callback, arguments))
        if not self._after_refresh_timer.isActive():
            self._after_refresh_timer.start()

    def _flush_after_refresh(self) -> None:
        if self.window.widget_gone:
            self._after_refresh_callbacks.clear()
            return
        pending = tuple(self._after_refresh_callbacks)
        self._after_refresh_callbacks.clear()
        for callback, arguments in pending:
            callback(*arguments)

    def publish_core(self, event: object) -> None:
        """The view hears what its history publishes, through the handlers the shared view
        classes declare (`BoundViewHost`, `WireView`), as Textual's pump carries it up from
        the history widget. (This was empty, "no Qt listener waits on a history's source
        work": a Qt thread never retried the publication that had waited for that work, and
        a Qt channel never reconciled an observation that arrived during it.)"""
        self.core_publications.publish(event)

    @cached_property
    def core_publications(self) -> CoreEventStream:
        """This history's own publications, which its view hears whole: Textual's history
        widget holds the same stream and its pump carries each event up to the view."""
        stream = CoreEventStream(self)
        self.view.subscribe_core(stream)
        return stream

    # Running source work on the Qt event loop

    def run_worker(
        self,
        work: Callable[[], Awaitable[object]],
        *,
        group: str | None = None,
        exclusive: bool = False,
        **_options: object,
    ) -> SourceTask:
        if exclusive and group is not None and (running := self._grouped_tasks.get(group)) is not None:
            running.cancel()
        task = SourceTask(work(), loop=asyncio.get_event_loop())
        self._tasks.add(task)
        if group is not None:
            self._grouped_tasks[group] = task
        task.add_done_callback(partial(self._worker_done, TaskGroupKey.from_optional(group)))
        return task

    def _worker_done(self, group: TaskGroupKey, task: SourceTask) -> None:
        self._tasks.discard(task)
        group.clear_group_task(task, self)

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
    _notifications_timer: QTimer | None = None

    def report_queue_evidence(self) -> None:
        """New queue evidence repaints the composer's queue rows, as Textual's
        `Conversation.queue_evidence_changed` does through its submissions. Skip scheduling
        a composer sync when there is neither queue evidence nor an active send."""
        if self.submissions.queue_evidence is not None or self.submissions.active:
            self.submissions.publish_pending()

    def run_notification_work(self, work: Awaitable[None]) -> None:
        self.notification_work.cancel()
        self.notification_work = asyncio.ensure_future(work)

    def check_notifications_after_refresh(self) -> None:
        timer = self._notifications_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(0)
            timer.timeout.connect(self.check_notifications)
            self._notifications_timer = timer
        if not timer.isActive():
            timer.start()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.check_notifications_after_refresh()

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

    def row_index(self, model_rows: FragmentRowList) -> int:
        return -1

    def collapse_link(self) -> FragmentCollapse | None:
        return None


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

    def row_index(self, model_rows: FragmentRowList) -> int:
        return model_rows.row_of(self.fragment.key)

    def collapse_link(self) -> FragmentCollapse | None:
        return self.fragment.header_collapse_link()

    def reader_position(self, window: QtHistoryWindow) -> FragmentPosition:
        return FragmentPosition(self.fragment.key, self.into / self.height, self.height, block=0)

    def pinned_header(self, window: QtHistoryWindow) -> PinnedHeader:
        fragment = self.fragment
        dividers = fragment.pinned_dividers
        if not dividers:
            return PinnedHeader((), self.left, self.width, fragment.key.source)
        threshold = self.window.rows.header_pin_threshold(fragment, self.window.font(), self.width)
        headers = dividers if threshold is not None and self.into >= threshold else ()
        return PinnedHeader(headers, self.left, self.width, fragment.key.source)


@dataclass(frozen=True)
class QtRowLocation(FragmentLocation):
    """A message's row in a Qt window. Qt lays every row out in one step, so a row the model
    holds is laid out; a message with no row is `UnloadedFragment`."""

    row: int
    fragment: HistoryFragment

    def laid_out(self, window: QtHistoryWindow) -> bool:
        return True

    def destination(self, window: QtHistoryWindow, fraction: float) -> float:
        rect = window.row_rect(self.row)
        return window.scroll_y + rect.top() + round(fraction * rect.height())


class QtStickyHeader(HeaderPin, QWidget):
    """`HeaderPin` floated over the history's top edge, drawn by the history rows' own
    delegate. Always `WA_TransparentForMouseEvents` so finger drags starting on the pinned
    header route straight to `QScroller` on the viewport; taps are dispatched from
    `QtHistoryWindow._row_tapped` into `handle_tap` (stacked burst opens, `@sender`/`#target`
    links, and `▼`/divider collapse), with live text-color inversion on the tapped span."""

    _MAX_LAID_OUT = 32
    _MAX_PIXMAPS = 16

    def __init__(self, window: QtHistoryWindow) -> None:
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.history_window = window
        self.documents: tuple[QTextDocument, ...] = ()
        self.drawn: tuple = ()
        self.laid_out: OrderedDict[Divider, QTextDocument] = OrderedDict()
        self.layout_context: tuple = ()
        self._pixmap_cache: OrderedDict[tuple, QImage] = OrderedDict()
        self.hide()

    def draw_pinned(self, headers: tuple[Divider, ...], x: int, width: int) -> None:
        """Every scroll offset pins; only different headers, column, font, link context or
        renderer (a theme) lay anything out again, and recently pinned headers stay cached
        in `laid_out` and `_pixmap_cache` so scrolling back and forth across message
        boundaries avoids re-running `setHtml` / layout / rasterization or no-op geometry calls."""
        window = self.history_window
        context = (width, window.rows._font_spec(window.font()), window.rows.links_revision, id(window.rows.renderer))
        drawn = (headers, x, context)
        if drawn == self.drawn:
            return
        if context != self.layout_context:
            self.laid_out.clear()
            self._pixmap_cache.clear()
            self.layout_context = context
        documents: list[QTextDocument] = []
        for header in headers:
            document = self.laid_out.get(header)
            if document is not None:
                self.laid_out.move_to_end(header)
            else:
                document = window.rows.header_document(header, window.font(), width)
                if document is None:
                    return
                self.laid_out[header] = document
                while len(self.laid_out) > self._MAX_LAID_OUT:
                    self.laid_out.popitem(last=False)
            documents.append(document)
        self.drawn = drawn
        self.documents = tuple(documents)
        height = sum(int(document.size().height()) for document in self.documents)
        if self.width() != width or self.height() != height:
            self.resize(width, height)
            window._floating_covers_cache = None
        origin = window.viewport().mapTo(window, QPoint(x, 0))
        if self.pos() != origin:
            self.move(origin)
            window._floating_covers_cache = None
        if not self.isVisible():
            self.raise_()
        self.update()

    def show_pin(self, shown: bool) -> None:
        if self.isVisible() != shown:
            self.setVisible(shown)
            self.history_window._floating_covers_cache = None
            if shown:
                self.raise_()

    def handle_tap(self, local: QPoint) -> bool:
        """Handle a tap at `local` (widget coordinates) on the pinned header:
        1. Stacked burst headers open their message (`open_pinned`).
        2. Explicit anchors (`@sender`, `#target`, `▼` disclosure) dispatch their link and
           invert the tapped span text.
        3. Tapping anywhere else on a bus message's pinned header collapses/expands it and
           inverts the pinned header text."""
        y, top = local.y(), 0
        window = self.history_window
        for index, document in enumerate(self.documents):
            doc_h = int(document.size().height())
            if y < top + doc_h:
                if window.open_pinned(index):
                    window._set_tap_highlight(PinnedHeaderTapHighlight(index))
                    return True
                tapped = window._tapped_link_in_document(document, local.x(), y - top, self.width(), doc_h)
                if tapped is not None:
                    link, href = tapped
                    window._set_tap_highlight(PinnedLinkTapHighlight(index, href))
                    window.dispatch_sync(link)
                    return True
                collapse = window.top_page().collapse_link()
                if collapse is not None:
                    window._set_tap_highlight(PinnedHeaderTapHighlight(index))
                    window.toggle_fragment(collapse)
                    return True
                return False
            top += doc_h
        return False

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if not self.documents:
            return
        painter = QPainter(self)
        bg_hex, bg_color, fg_color = self.history_window.rows._theme_colours()
        highlight = self.history_window.tap_highlight
        if highlight.is_pinned():
            painter.fillRect(self.rect(), bg_color)
            palette = self.palette()
            for index, document in enumerate(self.documents):
                active = highlight if highlight.matches_pinned(index) else NO_TAP_HIGHLIGHT
                active.paint_document(painter, document, palette, bg_color, fg_color)
                painter.translate(0, document.size().height())
            painter.end()
            return
        dpr = self.devicePixelRatioF()
        img_format = HistoryRowDelegate._backing_image_format(HeldBackingFormatWidget(self), painter)
        key = (self.drawn, self.width(), self.height(), dpr, bg_hex, img_format)
        image = self._pixmap_cache.get(key)
        if image is not None:
            self._pixmap_cache.move_to_end(key)
        else:
            image = QImage(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)), img_format)
            image.setDevicePixelRatio(dpr)
            image.fill(bg_color)
            drawing = QPainter(image)
            context = QAbstractTextDocumentLayout.PaintContext()
            context.palette = self.palette()
            for document in self.documents:
                document.documentLayout().draw(drawing, context)
                drawing.translate(0, document.size().height())
            drawing.end()
            self._pixmap_cache[key] = image
            while len(self._pixmap_cache) > self._MAX_PIXMAPS:
                self._pixmap_cache.popitem(last=False)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(0, 0, image)
        painter.end()


class QtJumpBar(LatestJumpBar, QPushButton):
    """The shared `LatestJumpBar` as a floating button over the history's viewport; clicking
    it jumps the window back to the latest row. Text and border take PrimaryColour, as
    Textual's `BackToBottom` takes `PrimaryText`.

    Renders its rounded pill once into a device-ratio `QPixmap` so scroll frames that
    repaint the viewport strip underneath blit a cached pixmap instead of re-evaluating
    a stylesheet `QPushButton` every frame."""

    def __init__(self, parent: QWidget, renderer: QtLineRenderer) -> None:
        super().__init__(self.label, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._bg_color = QColor()
        self._primary_color = QColor()
        self._pill_cache: tuple[tuple, QPixmap] | None = None
        font = QFont(self.font())
        font.setBold(True)
        self.setFont(font)
        renderer.themed(self, partial(self.paint_colours, renderer))
        self.hide()

    def paint_colours(self, renderer: QtLineRenderer) -> None:
        scheme = renderer.scheme
        self._primary_color = QColor(PrimaryColour.rgb(scheme).hex)
        self._bg_color = QColor(SurfaceHoverColour.rgb(scheme).hex)
        self._pill_cache = None
        if self.isVisible():
            self.update()

    def sizeHint(self) -> QSize:  # type: ignore[override]
        metrics = QFontMetrics(self.font())
        text_size = metrics.size(0, self.text())
        return QSize(text_size.width() + 24, text_size.height() + 10)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        dpr = self.devicePixelRatioF()
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return
        down = self.isDown()
        key = (width, height, dpr, down, self.text(), self._bg_color.rgb(), self._primary_color.rgb())
        cached = self._pill_cache
        if cached is not None and cached[0] == key:
            pixmap = cached[1]
        else:
            pixmap = QPixmap(max(1, round(width * dpr)), max(1, round(height * dpr)))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.GlobalColor.transparent)
            drawing = QPainter(pixmap)
            drawing.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            bg = self._bg_color.darker(115) if down else self._bg_color
            drawing.setBrush(bg)
            drawing.setPen(QPen(self._primary_color, 1.0))
            box = QRectF(0.5, 0.5, width - 1.0, height - 1.0)
            radius = min(14.0, height / 2.0)
            drawing.drawRoundedRect(box, radius, radius)
            drawing.setFont(self.font())
            drawing.setPen(self._primary_color)
            drawing.drawText(QRect(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, self.text())
            drawing.end()
            self._pill_cache = (key, pixmap)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()

    @property
    def jump_shown(self) -> bool:
        return self.isVisible()

    def show_jump(self, shown: bool) -> None:
        self.setVisible(shown)


class QtHistoryWindow(AnimatesArrivals, ReaderPlacement, ShowsLatestJumpBar, FollowsTail, PagedReader,
                      QtWorkspaceHosted, VirtualRowCanvas, PagingWindow, TogglesFragmentShown, PinsMessageHeader,
                      SettingsReading, QtHintTargetSource):
    """The reader window of one Qt conversation: prefix-sum virtual rows of the history's
    shown fragments, scrolled by pixel without `QListView`/`QAbstractListModel` overhead. It
    answers the shared pager's window contract: reaching the top reads older pages, the bottom
    newer ones, End and the reader at the end follow the newest row, and rows that arrive or
    are evicted above the reader leave the row they are reading where it was."""

    def primary_hint_targets(self, host):
        if self.widget_gone or not self.isVisible():
            return ()
        vp = self.viewport()
        vp_rect = vp.rect()
        targets = []
        for fragment in self.visible_fragments():
            row = self.model_rows.row_of(fragment.key)
            if row < 0:
                continue
            rect = self.row_rect(row)
            if rect.isEmpty() or not rect.intersects(vp_rect):
                continue
            top_pt = QPoint(max(4, rect.left() + 4), max(2, rect.top() + 2))
            x, y = self.hint_anchor(vp, host, top_pt)
            targets.append(
                QtCallbackHintTarget(
                    vp, x, y, lambda r=row, f=fragment: self._activate_header_hint(r, f)
                )
            )
        return targets

    def _activate_header_hint(self, row: int, fragment: HistoryFragment) -> None:
        self.setFocus(Qt.FocusReason.ShortcutFocusReason)
        if not self.widget_gone and 0 <= row < self.model_rows.rowCount():
            self.toggle_fragment(fragment)

    def context_hint_targets(self, host):
        if self.widget_gone or not self.isVisible():
            return ()
        vp = self.viewport()
        vp_rect = vp.rect()
        targets = []
        for fragment in self.visible_fragments():
            row = self.model_rows.row_of(fragment.key)
            if row < 0:
                continue
            rect = self.row_rect(row)
            if rect.isEmpty() or not rect.intersects(vp_rect):
                continue
            pt = QPoint(max(4, rect.left() + 4), max(2, rect.top() + 2))
            x, y = self.hint_anchor(vp, host, pt)
            targets.append(QtCallbackHintTarget(vp, x, y, lambda p=pt: self._emit_block_menu_at(p)))
        return targets

    block_menu_requested = Signal(object, QPoint, name="blockMenuRequested")

    history: QtConversationHistory
    _cached_font_line_spacing: tuple[QFont, int] | None = None
    _floating_covers_cache: tuple[list[QRect], list[QRect]] | None = None
    arrival_slide_distance: float = 36.0
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

    def __init__(self, renderer: QtLineRenderer, pictures: RowPictures, scope,
                 parent: QWidget | None = None) -> None:
        super().__init__(HistoryRowDelegate(renderer, pictures, scope.app.render_processes), parent)
        self._last_viewport_width: int = 0
        self._viewport_resize_pending: bool = False
        self._vbar = self.verticalScrollBar()
        self._viewport = self.viewport()
        self._overlay_scrollbar = None
        self._top_page_cache: tuple[int, int, int, QtTopRow] | None = None
        self._visible_cache: tuple[int, int, int, tuple[HistoryFragment, ...]] | None = None
        self._last_scroll_at: float = 0.0
        self.actively_scrolling = False
        self.tap_highlight: TapHighlight = NO_TAP_HIGHLIGHT
        # Mark the history window opaque with the theme's background colour so repainting
        # floating overlays (`QtJumpBar`, `QtStickyHeader`) or the viewport stops here instead
        # of walking up 5 ancestor widgets to `QtToadApp` on every scroll frame.
        self.setAutoFillBackground(True)
        self._apply_opaque_background()
        self.configuration_scope = scope  # the view this window reads in
        # Rows draw by the app's renderer: a new scheme or diff marks draws them again.
        renderer.follows_theme(self, self.restyle_rows)
        self.draft: tuple[HistoryFragment, ...] = ()  # after the pages, as Textual's `CliDraft`
        self.live_blocks: list[QtLiveBlock] = []  # after the draft, as Textual's live blocks
        self.histories: WeakSet = WeakSet()
        self.history_lock = asyncio.Lock()
        self.presentation_budget = PresentationBudget(
            buffer_viewports=scope.configuration_settings.current.ui.history_buffer_viewports,
        )
        self.lookahead = DirectionalPreparation(self)
        self.reader_position = TailPosition()
        self._anchored = True
        self._restoring = False
        self._preparing = False
        self._prepare_timer = QTimer(self)
        self._prepare_timer.setSingleShot(True)
        self._prepare_timer.setInterval(0)
        self._prepare_timer.timeout.connect(self.prepare_viewport)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._on_settle_timer)
        self._viewport_resize_timer = QTimer(self)
        self._viewport_resize_timer.setSingleShot(True)
        self._viewport_resize_timer.setInterval(0)
        self._viewport_resize_timer.timeout.connect(self._apply_viewport_width_change)
        self._tap_highlight_timer = QTimer(self)
        self._tap_highlight_timer.setSingleShot(True)
        self._tap_highlight_timer.setInterval(self.tap_highlight.tap_flash_duration_ms)
        self._tap_highlight_timer.timeout.connect(self._clear_tap_highlight)
        self.verticalScrollBar().valueChanged.connect(self.scrolled)
        self._scroll_frame_timer = QTimer(self)
        self._scroll_frame_timer.setSingleShot(True)
        self._scroll_frame_timer.timeout.connect(self._scroll_frame)
        self._scroll_frame_pending = False
        self._overshoot = 0.0
        _scroller = QScroller.scroller(self.viewport())
        _scroller.stateChanged.connect(self._on_scroller_state)
        self.jump_bar = QtJumpBar(self, renderer)
        self.jump_bar.clicked.connect(self.jump_to_latest)
        self.sticky_header = QtStickyHeader(self)
        self.destroyed.connect(self._on_widget_destroyed)
        self._fling_stopped = False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_block_menu_at)
        FingerPress.install(QApplication.instance()).tapped.connect(self._row_tapped)
        self._reader_shortcuts = scope.app.action_keys.bind_family(self, ReaderAction, self)

    @property
    def animation_clock(self):
        return self.configuration_scope.app.animation_clock

    @property
    def arrival_animation_visible(self) -> bool:
        return not self.widget_gone and self.isVisible()

    def arrival_rows_height(self, keys: tuple[object, ...]) -> float | None:
        if self.widget_gone:
            return None
        model_rows = self.model_rows
        rows = [row for key in keys if (row := model_rows.row_of(key)) >= 0]
        if not rows:
            return None
        self.execute_layout()
        return float(sum(self.row_rect(row).height() for row in rows))

    def prepare_arrival_layout(self) -> None:
        if not self.widget_gone:
            self.execute_layout()

    def repaint_arrival_keys(self, keys: tuple[object, ...]) -> None:
        """Only the rising rows (plus any local upward slide band): a whole-viewport update
        every tick flickers the pinned header."""
        if self.widget_gone:
            return
        model_rows = self.model_rows
        extra = ceil(self.arrival_slide_distance)
        for key in keys:
            if (row := model_rows.row_of(key)) >= 0:
                self.update_row(row, extra_bottom=extra)

    def _on_widget_destroyed(self, *_args) -> None:
        self.stop_arrival_motion()
        self.animation_clock.set_scrolling(self, False)

    async def acquire_links(self, app) -> None:
        """The names this conversation's bodies link through; redraw rows only if links changed."""
        links = await LinkContext.observed(app.renderer.links.root, app.coordination_access)
        changed = self.rows.link(links)
        app.renderer.links = links
        if changed:
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
        self._floating_covers_cache = None
        if shown:
            self._place_jump_bar()
            QTimer.singleShot(0, self, self._reposition_jump_bar)

    def _reposition_jump_bar(self) -> None:
        if not self.widget_gone and self.jump_bar.isVisible():
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
        self._floating_covers_cache = None

    def _apply_viewport_width_change(self) -> None:
        """Re-measure rows once after a viewport-only width change (e.g. `setViewportMargins`
        from `OverlayScrollBar.follow`). Deferred off `viewportEvent` so Qt's own scrollbar
        geometry updates inside `doItemsLayout` can never recurse back into `rows_changed`."""
        self._viewport_resize_pending = False
        if self.widget_gone:
            return
        width = self._viewport.width()
        if width > 0 and width != self._last_viewport_width:
            self._last_viewport_width = width
            self._layout_width_measured = 0
            self.rows.width_changed()
            self.rows_changed()

    def floating_covers(self) -> tuple[list[QRect], list[QRect]]:
        """Only this window's two floating overlays (`sticky_header` and `jump_bar`),
        cached across steady scroll ticks and invalidated whenever either overlay or the
        viewport moves, resizes, or toggles visibility."""
        cached = self._floating_covers_cache
        if cached is not None:
            return cached
        area = self._viewport.geometry()
        top_left = area.topLeft()
        covers: list[QRect] = []
        opaque: list[QRect] = []
        for child in (self.sticky_header, self.jump_bar):
            if child.isVisible():
                geo = child.geometry()
                if geo.intersects(area):
                    rect = geo.intersected(area).translated(-top_left)
                    covers.append(rect)
                    if child.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent):
                        opaque.append(rect)
        result = (covers, opaque)
        self._floating_covers_cache = result
        return result

    def _invalidate_tap_highlight(self, highlight: TapHighlight) -> None:
        if not self.widget_gone:
            highlight.invalidate_in(self)

    def _set_tap_highlight(self, highlight: TapHighlight) -> None:
        previous = self.tap_highlight
        self.tap_highlight = highlight
        self._invalidate_tap_highlight(previous)
        self._invalidate_tap_highlight(highlight)
        if highlight is NO_TAP_HIGHLIGHT:
            self._tap_highlight_timer.stop()
        else:
            self._tap_highlight_timer.start()

    def _clear_tap_highlight(self) -> None:
        previous = self.tap_highlight
        if previous is NO_TAP_HIGHLIGHT:
            return
        self.tap_highlight = NO_TAP_HIGHLIGHT
        self._tap_highlight_timer.stop()
        self._invalidate_tap_highlight(previous)

    def _row_tapped(self, press: Press) -> None:
        """A tap on a row or pinned sticky header: a tapped link opens and inverts its text;
        tapping a bus message's header divider collapses/expands it and inverts the header
        text; otherwise a message whose head is above the viewport glides its head to the top.
        A tap while rows are still flinging only stops the fling."""
        viewport = self.viewport()
        if not press.within(viewport):
            return
        stopped, self._fling_stopped = self._fling_stopped, False
        scroller = QScroller.scroller(viewport)
        if stopped or scroller.state() == QScroller.State.Scrolling:
            scroller.stop()
            press.claim()
            return
        point_in_window = press.at(self)
        if self.sticky_header.isVisible() and self.sticky_header.geometry().contains(point_in_window):
            if self.sticky_header.handle_tap(point_in_window - self.sticky_header.pos()):
                press.claim()
                return
        point = press.at(viewport)
        row = self.row_at_point(point)
        if row < 0:
            return
        fragment = self.model_rows.fragments[row]
        tapped = self._tapped_link_at(row, point)
        if tapped is not None:
            link, href = tapped
            self._set_tap_highlight(RowLinkTapHighlight(fragment.key, href))
            press.claim()
            self.dispatch_sync(link)
        elif (collapse := self._header_collapse_at(row, point)) is not None:
            self._set_tap_highlight(RowHeaderTapHighlight(fragment.key))
            press.claim()
            self.toggle_fragment(collapse)
        elif self.reveal_head_at(point):
            press.claim()

    def _header_collapse_at(self, row: int, point: QPoint) -> FragmentCollapse | None:
        """If `point` (viewport coordinates) landed on a bus message's header divider lines
        or timestamp (outside an explicit `@sender`/`#target` anchor), return its collapse link."""
        fragment = self.model_rows.fragments[row]
        collapse = fragment.in_flow_collapse_link()
        if collapse is None:
            return None
        rect = self.row_rect(row)
        y_in_row = point.y() - rect.top()
        width = self.rows.layout_width(rect.width())
        block_index, _line = self.rows.block_row(fragment, self.font(), width, y_in_row)
        blocks = fragment.line_blocks
        if block_index < len(blocks) and blocks[block_index].triggers_header_collapse:
            return collapse
        return None

    _TOUCH_LINK_OFFSETS: ClassVar[tuple[tuple[int, int], ...]] = (
        (0, -4), (0, 4), (0, -8), (0, 8), (-3, 0), (3, 0),
    )
    """Touch-slop offsets probed around a tap so a finger near a 16 px sender/receiver name
    in a header opens that conversation tab instead of falling through to header collapse."""

    def _tapped_link_in_document(
        self, document: QTextDocument, local_x: int, local_y: int, width: int, height: int
    ) -> tuple[LineLink, str] | None:
        """The `(link, href)` at `(local_x, local_y)` in `document`, preferring higher
        `touch_priority` links (`@sender`/`#target`, URLs, files) within touch slop."""
        layout = document.documentLayout()
        href = layout.anchorAt(QPointF(local_x, local_y))
        exact = (LineLink.from_href(href), href) if href else None
        if exact is not None and exact[0].touch_priority > 0:
            return exact
        for dx, dy in self._TOUCH_LINK_OFFSETS:
            probe_x, probe_y = local_x + dx, local_y + dy
            if 0 <= probe_x < width and 0 <= probe_y < height:
                nearby_href = layout.anchorAt(QPointF(probe_x, probe_y))
                if nearby_href:
                    nearby = LineLink.from_href(nearby_href)
                    if nearby.touch_priority > 0:
                        return nearby, nearby_href
        return exact

    def _tapped_link_at(self, row: int, point: QPoint) -> tuple[LineLink, str] | None:
        """The `(link, href)` under `point` in `row`."""
        rect = self.row_rect(row)
        if rect.isEmpty():
            return None
        width = self.rows.layout_width(rect.width())
        document = self.rows.row_document_for(self.model_rows.fragments[row], self.font(), width)
        local = point - rect.topLeft()
        return self._tapped_link_in_document(document, local.x(), local.y(), rect.width(), rect.height())

    def anchor_at(self, point: QPoint) -> str:
        """The href of the link drawn at `point` (viewport coordinates), or "" over plain text."""
        row = self.row_at_point(point)
        if row < 0:
            return ""
        rect = self.row_rect(row)
        width = self.rows.layout_width(rect.width())
        document = self.rows.row_document_for(self.model_rows.fragments[row], self.font(), width)
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

    def changeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        """Follow the application-wide text scale (`QApplication.setFont`) automatically."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and not self.widget_gone:
            self._cached_font_line_spacing = None
            self._layout_font_key = ""
            self.rows.release_documents()
            self.rows_changed()
            self.repin_header()

    def toggleable_fragments(self) -> tuple[HistoryFragment, ...]:
        return self.model_rows.fragments

    def apply_fragment_shown(
        self, target: HistoryFragment, changes: list[tuple[HistoryFragment, Shown]]
    ) -> None:
        self.history.apply_shown(changes)

    def _emit_block_menu_at(self, point: QPoint) -> None:
        """Right-click or long-press at ``point`` (viewport coordinates): emit the
        fragment under that row so ConversationView can open the block menu."""
        row = self.row_at_point(point)
        if row < 0:
            return
        fragment = self.model_rows.fragments[row]
        self.block_menu_requested.emit(fragment, self.viewport().mapTo(self.window(), point))

    # Geometry, in pixels

    @property
    def scroll_y(self) -> float:
        return 0.0 if self.widget_gone else self._vbar.value()

    @scroll_y.setter
    def scroll_y(self, value: float) -> None:
        if not self.widget_gone:
            self._vbar.setValue(int(value))

    @property
    def scroll_target_y(self) -> float:
        """Where the rows are being carried (`animated_travel`), within what is loaded; where
        they are when nothing carries them."""
        return max(0.0, min(self.max_scroll_y, self.scroll_y + self.animated_travel))

    @property
    def max_scroll_y(self) -> float:
        return 0.0 if self.widget_gone else self._vbar.maximum()

    @property
    def tail_scroll_y(self) -> float:
        return self.max_scroll_y

    def _viewport_height_safe(self) -> int:
        return 0 if self.widget_gone else self._viewport.height()

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
        if self._vbar.maximum() > 0:
            return 0
        return max(0, height - self.total_height())

    def toolkit_animated_travel(self) -> float:
        """Pixels a fling's momentum (`fling_travel`) still carries the rows."""
        return 0.0 if self.widget_gone else self.fling_travel()

    def fling_travel(self) -> float:
        """How far a fling's speed carries the rows at QScroller's deceleration (v²/2a, the
        distance QScroller itself plans), whether or not rows are loaded that far: Qt stops
        a fling at the loaded edge, and the rows it was thrown towards are what the reader
        asked for."""
        scroller = QScroller.scroller(self._viewport)
        if scroller.state() != QScroller.State.Scrolling:
            return 0.0
        speed = scroller.velocity().y()
        deceleration = scroller.scrollerProperties().scrollMetric(
            QScrollerProperties.ScrollMetric.DecelerationFactor)
        return copysign(speed * speed / (2 * deceleration) * scroller.pixelPerMeter().y(), speed)

    @property
    def presenting(self) -> bool:
        return False if self.widget_gone else self.isVisible()

    def runway(self, history) -> OffScreenRunway:
        if not self.presenting:
            return OffScreenRunway()
        return Runway(int(self.scroll_y), int(self.max_scroll_y - self.scroll_y))

    def fragment_height(self, fragment: HistoryFragment) -> int:
        if self.widget_gone:
            return 0
        return self.rows.fragment_height(fragment, self.font(), self.viewport_width())

    def visible_fragments(self) -> tuple[HistoryFragment, ...]:
        """Fragments intersecting the viewport, cached per `(scroll_y, geometry_revision, height)`
        and computed by walking forward from the top row instead of a second `QListView::indexAt`."""
        if self.widget_gone:
            return ()
        area = self._viewport.rect()
        height = area.height()
        if height <= 0:
            return ()
        scroll_val = self._vbar.value()
        cached = self._visible_cache
        if cached is not None and cached[0] == scroll_val and cached[1] == self.geometry_revision and cached[2] == height:
            return cached[3]
        model_rows = self.model_rows
        start = -1
        top_cached = self._top_page_cache
        if (top_cached is not None and top_cached[0] == scroll_val
                and top_cached[1] == self.geometry_revision):
            start = top_cached[3].row_index(model_rows)
        if start < 0:
            start = self.row_at_y(scroll_val)
        if start < 0:
            result: tuple[HistoryFragment, ...] = ()
        else:
            total = model_rows.rowCount()
            row = start
            bottom_edge = area.bottom()
            while row + 1 < total:
                next_rect = self.row_rect(row + 1)
                if not next_rect.isEmpty() and next_rect.top() > bottom_edge:
                    break
                row += 1
            result = model_rows.fragments[start:row + 1]
        self._visible_cache = (scroll_val, self.geometry_revision, height, result)
        return result

    def fragment_location(self, key) -> FragmentLocation:
        row = self.model_rows.row_of(key)
        return QtRowLocation(row, self.model_rows.fragments[row]) if row >= 0 else UnloadedFragment()

    # The reader

    @property
    def follows_tail(self) -> bool:
        return self._anchored

    def _stop_scroll_momentum(self) -> None:
        """Cancel any active fling, glide, head reveal, or travel offset before an explicit jump."""
        self.cancel_head_reveal()
        self.cancel_arrival_glide()
        if not self.widget_gone:
            scroller = QScroller.scroller(self.viewport())
            if scroller.state() != QScroller.State.Inactive:
                scroller.stop()
        self._flinging = False
        self._fling_stopped = False
        self._overshoot = 0.0
        self._travel_origin = 0.0

    def destination(self) -> None:
        """Stop kinetic scroll momentum before jumping to a destination (e.g. `jump_to_latest`).

        `QtJumpBar` is a child of the window rather than the viewport so `QScroller`
        cannot swallow its tap, which also means tapping it does not stop an active
        upward fling; without `scroller.stop()` the next kinetic frame pulls the
        window straight back up off the bottom."""
        self._stop_scroll_momentum()
        super().destination()

    def apply_anchor(self, anchor: bool) -> None:
        self._anchored = anchor
        # A publication restoring a following reader (`FollowTailCommit.restore_reader`)
        # glides to rows that just arrived; a running glide lands on the end itself.
        # A view closed between scheduling this and its running has nothing to scroll.
        if anchor and not self.widget_gone and not self.gliding_to_end():
            with self.layout_scroll():
                self.follow_end()

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
        self._flush_reader_scroll()
        history = self.history
        self.model_rows.show(tuple(fragment for page in history.pages if page.display
                                   for fragment in page.shown_fragments) + self.draft
                             + tuple(block.fragment() for block in self.live_blocks))

    def show_pages(self) -> None:
        """The rows as the pages show them now, laid out with the reader kept on their message."""
        self.show_rows()
        self.request_reader_layout()

    def request_reader_layout(self) -> None:
        """One prefix-sum layout now, keeping the reader on their message and answering the
        change that asked for it. Wrapping layout and reader placement in one `layout_scroll()`
        keeps scrollbar clamping from firing `scrolled()` as a fake reader move."""
        self._flush_reader_scroll()
        answered = self.history_change.layout_requests
        with self.layout_scroll():
            self.schedule_layout()
            self.execute_layout()
            self._top_page_cache = None
            self._visible_cache = None
            self.place_layout_reader()
        self.history_change.finish_layout(answered)
        self.repin_header()

    def show_draft(self, fragments: tuple[HistoryFragment, ...]) -> None:
        """Core's CLI draft as rows after the history (none clears it); new draft rows arrive smoothly."""
        if not fragments and not self.draft:
            return
        existing = {fragment.key for fragment in self.draft}
        new_fragments = tuple(fragment for fragment in fragments if fragment.key not in existing)
        self.draft = fragments
        if new_fragments:
            self.arrive_fragments(new_fragments, live=True)
        self.show_pages()

    def show_live(self, block: QtLiveBlock) -> None:
        """A turn's live block as a row after the history and the draft, arriving smoothly."""
        self.live_blocks.append(block)
        self.arrive_fragments((block.fragment(),), live=True)
        self.live_changed()

    def live_changed(self) -> None:
        """A live block grew or left: read the rows again, following the end if the reader was."""
        self.show_pages()

    def drop_live(self, block: QtLiveBlock) -> None:
        if block in self.live_blocks:
            self.live_blocks.remove(block)
            self.clear_live_seen((block.fragment().source_identity,))
            self.live_changed()

    def retire_live(self, blocks) -> None:
        """Remove live blocks covered by saved history in one row update."""
        retired = set(blocks)
        kept = [block for block in self.live_blocks if block not in retired]
        if len(kept) != len(self.live_blocks):
            self.live_blocks = kept
            self.clear_live_seen(block.fragment().source_identity for block in retired)
            self.show_pages()

    def live_in_viewport(self, candidates) -> bool:
        """Whether any candidate live block currently draws inside the visible viewport."""
        if self.widget_gone or not self.isVisible():
            return False
        candidate_set = set(candidates)
        positions = {block.position for block in self.live_blocks if block in candidate_set}
        if not positions:
            return False
        return any(
            event.position in positions
            for fragment in self.visible_fragments()
            for event in fragment.events
        )

    def committed_pages_changed(self) -> None:
        """Saved pages' shown fragments changed: note sent references and redraw rows.
        Live blocks stay until `BoundView` retires the ones saved history actually covers."""
        if self.history.pages:
            self.history.note_sent_references(self.history.pages[-1].shown_fragments)
        self.show_pages()

    def _apply_opaque_background(self) -> None:
        """Keep `QPalette.Window` and `QPalette.Base` opaque on the window and viewport so
        `QWidgetPrivate::isOpaque()` stays True across theme switches."""
        bg = QColor(BackgroundColour.rgb(self.rows.renderer.scheme).hex)
        for widget in (self, self._viewport):
            palette = widget.palette()
            palette.setColor(palette.ColorRole.Window, bg)
            palette.setColor(palette.ColorRole.Base, bg)
            widget.setPalette(palette)

    def restyle_rows(self) -> None:
        if not self.widget_gone:
            self._apply_opaque_background()
            self.rows.restyle()
            self.rows_changed()

    def rows_repainted(self) -> None:
        """Prepared rows, or a header the pin waited on, landed at the height they had."""
        super().rows_repainted()
        self.repin_header()

    def showEvent(self, event) -> None:  # type: ignore[override]
        """A hidden tab that deferred a latest jump or edge read resumes once shown."""
        super().showEvent(event)
        self.request_preparation()
        if self.jump_bar.isVisible():
            self._place_jump_bar()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        super().hideEvent(event)
        self.actively_scrolling = False
        self._settle_timer.stop()
        self._sync_clock_scrolling()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """A window that follows the latest message stays on it when its height changes: the
        composer replacing its placeholder (the first of a kind is built at a height the
        estimate missed), a keyboard, a pane. The scroll range grows with the height lost and
        the offset stayed, so the last message sat that much below the fold with no jump bar
        offered (2026-11-22, a thread opened on a scratch bus: 106 px short, following)."""
        super().resizeEvent(event)
        if self.jump_bar.isVisible():
            self._place_jump_bar()
        self.keep_tail_after_resize(event.oldSize().height(), event.size().height())

    def keep_tail_after_resize(self, was: int, now: int) -> None:
        if was != now and self.follows_tail and not self.widget_gone:
            self.follow_latest()

    def apply_measured_rows(self, updates: list[tuple[int, int, int]]) -> None:
        """Commit background height measurements after flushing pending reader scroll so
        `request_reader_layout()` anchors against pre-update geometry."""
        if not updates or self.widget_gone:
            return
        self._flush_reader_scroll()
        for row, height, extent in updates:
            self._set_row_geometry(row, height, extent, False)
        self.rows_changed()

    def rows_changed(self) -> None:
        """Prepared rows changed height: lay them out again; the layout keeps the reader's
        message. A destroyed window has no reader to serve."""
        if not self.widget_gone:
            self.request_reader_layout()
            self.viewport().update()

    @property
    def at_tail_end(self) -> bool:
        """Qt's pixel scroll bar keeps END_SLACK around the bottom (`VirtualRowView.at_end`)."""
        return self.at_end

    def scrolled(self, value: int) -> None:
        """The reader moved: join or leave the end, and schedule the full response on the
        next display frame. QScroller fires valueChanged at touch rate during a drag;
        coalescing both `record_reader_scroll` and `repin_header`/`respond_to_scroll` to
        display frames keeps `QListView::indexAt` out of 90-240 Hz touch ticks."""
        # Every offset pins, the window's own as well as the reader's: a glide down into a tall
        # arrival moves the top row into it, and skipping the window's own offsets left the
        # arrival's header unpinned and its burst unstacked (Tristan, Android, 2026-11-18).
        self._schedule_scroll_frame()
        moved, self._scrolled_to = value - self._scrolled_to, value
        if moved and self.tap_highlight is not NO_TAP_HIGHLIGHT:
            self._clear_tap_highlight()
        if self._restoring:
            return
        if not self.at_end and self.follows_tail:
            self.release_anchor()
        self._reader_moved += moved
        self._reader_position_dirty = True
        self._reader_scrolled = True

    _reader_scrolled = False
    _reader_position_dirty = False
    _reader_moved = 0
    _scrolled_to = 0

    def _flush_reader_scroll(self) -> None:
        """Commit pending scroll movement into `reader_position` before a row splice or layout
        runs `place_layout_reader()`, so an arrival or worker batch landing inside the 16 ms
        `_scroll_frame_timer` window cannot snap the reader back to their pre-scroll position."""
        if self._reader_position_dirty:
            self._reader_position_dirty = False
            moved, self._reader_moved = self._reader_moved, 0
            self.record_reader_scroll(moved)

    def _schedule_scroll_frame(self) -> None:
        if not self._scroll_frame_pending:
            self._scroll_frame_pending = True
            interval = max(1, round(frame_interval(DisplayScreen.from_optional(QWidget.screen(self))) * 1000))
            self._scroll_frame_timer.start(interval)

    def _scroll_frame(self) -> None:
        """One display frame's scroll response: reader position, pin, lookahead, and viewport
        preparation. Runs `prepare_viewport` inline instead of arming a second 0ms `_prepare_timer`
        on every scroll frame (~212 redundant timer starts in 5s)."""
        self._scroll_frame_pending = False
        if self._reader_scrolled:
            self._reader_scrolled = False
            self._flush_reader_scroll()
            self.repin_header()
            was_preparing = self._preparing
            self._preparing = True
            try:
                self.respond_to_scroll(self._vbar.value())
            finally:
                if not was_preparing:
                    self._prepare_timer.stop()
            self.prepare_viewport()
        else:
            self.repin_header()

    _flinging = False

    def reveal_head_at(self, point: QPoint) -> bool:
        """A tap at ``point`` (viewport coordinates): when the tapped message's head is above
        the viewport, glide it up to the top. A head already on screen stays where it is,
        as in Textual (`reveal_message_head`). Whether it moved the rows."""
        tapped_row = self.row_at_point(point)
        if tapped_row < 0:
            return False
        model_rows = self.model_rows
        head = model_rows.fragments[tapped_row].message_head(model_rows.fragments)
        row = model_rows.row_of(head.key)
        if row < 0:
            return False
        top = self.row_rect(row).top()
        if top >= 0:
            return False
        return self.start_head_reveal(self.scroll_y + top)

    @property
    def scroll_in_motion(self) -> bool:
        """Whether a finger drag/fling or an unsettled scroll burst is moving the viewport."""
        return self.actively_scrolling or self._settle_timer.isActive()

    def _sync_clock_scrolling(self) -> None:
        self.animation_clock.set_scrolling(self, self.scroll_in_motion)

    def _on_scroller_state(self, state) -> None:
        """A finger taking the rows stops a head reveal; a press that stops a fling is
        remembered, so its release is not read as a tap on a row. Notification checks,
        read-marking, and decorative chrome animations wait until motion settles."""
        scrolling = state in (QScroller.State.Dragging, QScroller.State.Scrolling)
        was_scrolling = self.actively_scrolling
        self.actively_scrolling = scrolling
        self.rows.set_scroll_paused(scrolling)
        if state in (QScroller.State.Pressed, QScroller.State.Dragging):
            self.cancel_head_reveal()
        if state == QScroller.State.Pressed:
            self._fling_stopped = self._flinging
        self._flinging = state == QScroller.State.Scrolling
        if state == QScroller.State.Inactive:
            self._overshoot = 0.0
            self._travel_origin = 0.0
        if was_scrolling and not scrolling:
            if self._settle_timer.isActive():
                self._settle_timer.stop()
                self._sync_clock_scrolling()
                self._settle()
            else:
                self._sync_clock_scrolling()
                self.request_preparation()
        else:
            self._sync_clock_scrolling()

    _travel_origin = 0.0
    """How far layout has moved the reader since the finger now scrolling them came down.
    QScroller plans a drag or a fling in scroll offsets it read when the finger came down;
    rows landing above the reader move every offset, so its next frame put the reader back
    on the old offset, a page of rows away. It is answered in offsets taken from this
    origin, which layout does not move (`viewportEvent`, `shift_travel`)."""

    def viewportEvent(self, event: QEvent) -> bool:  # type: ignore[override]
        """Handle viewport Resize/Move (keeping the overlay scrollbar, jump bar, and pinned
        header aligned with zero Python `eventFilter` on the viewport) and QScroller's Scroll
        events (overshoot detection plus travelling-finger origin offset)."""
        kind = event.type()
        if kind == QEvent.Type.Resize:
            self._floating_covers_cache = None
            width = self._viewport.width()
            if width > 0 and width != self._last_viewport_width:
                if self._last_viewport_width == 0:
                    self._last_viewport_width = width
                elif not self._viewport_resize_pending:
                    self._viewport_resize_pending = True
                    self._viewport_resize_timer.start()
            if self.jump_bar.isVisible():
                self._place_jump_bar()
            self.repin_header()
            overlay = self._overlay_scrollbar
            if overlay is not None and overlay.thickness:
                overlay.place()
            return super().viewportEvent(event)
        if kind == QEvent.Type.Move:
            self._floating_covers_cache = None
            overlay = self._overlay_scrollbar
            if overlay is not None and overlay.thickness:
                overlay.place()
            return super().viewportEvent(event)
        if kind == QEvent.Type.Scroll:
            self.overshot(event.overshootDistance().y())
            origin = self._travel_origin
            if origin:
                return super().viewportEvent(QScrollEvent(
                    event.contentPos() + QPointF(0, origin), event.overshootDistance(), event.scrollState()))
            return super().viewportEvent(event)
        origin = self._travel_origin
        if not origin:
            return super().viewportEvent(event)
        handled = super().viewportEvent(event)
        if handled and kind == QEvent.Type.ScrollPrepare:
            event.setContentPosRange(event.contentPosRange().translated(0, -origin))
            event.setContentPos(event.contentPos() - QPointF(0, origin))
        return handled

    def shift_toolkit_travel(self, rows: float, destination: float) -> None:
        """A finger's drag or fling goes on from the same rows at the same speed. QScroller
        prepares again from the moved origin: a fling it had planned to end at the loaded edge
        is planned again at its present speed, into the rows that landed."""
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
        """Ctrl+Wheel zooms the whole UI; otherwise a wheel at an edge asks for the next page."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                window = self.window()
                if isinstance(window, ClientApplication):
                    window.adjust_message_font_scale(5 if delta > 0 else -5)
            event.accept()
            return
        rows = -event.angleDelta().y() / 120 * self._font_line_spacing() * QApplication.wheelScrollLines()
        if not self.lookahead.request_boundary(rows):
            super().wheelEvent(event)

    def row_painted(self, fragment: HistoryFragment, rect: QRect) -> None:
        """A row whose text is on screen, beyond its header line, was seen.

        Reads a cached `lineSpacing` (invalidated in `changeEvent(FontChange)`) so the
        delegate's per-row `paint` skips both `QFontMetrics` allocations and C++ `QFont`
        comparisons on every visible row during scroll."""
        shown = rect.intersected(self._viewport.rect())
        if shown == rect or shown.height() > 2 * self._font_line_spacing():
            self.history.retain_painted(fragment)

    def _font_line_spacing(self) -> int:
        """Cached `QFontMetrics(self.font()).lineSpacing()`; invalidated on `FontChange`."""
        cached = self._cached_font_line_spacing
        if cached is not None:
            return cached[1]
        font = self.font()
        spacing = QFontMetrics(font).lineSpacing()
        self._cached_font_line_spacing = (QFont(font), spacing)
        return spacing

    # Frames

    def request_preparation(self) -> None:
        if not self._preparing and not self.widget_gone:
            self._preparing = True
            self._prepare_timer.start()

    def prepare_viewport(self) -> None:
        self._preparing = False
        for history in tuple(self.histories):
            history.prepare_viewport()

    def _schedule_settle(self) -> None:
        """Record the latest scroll timestamp and arm the settle timer once instead of
        mutating Qt's C++ timer heap on every scroll frame (~187 restarts in 5s)."""
        self._last_scroll_at = monotonic()
        if not self._settle_timer.isActive():
            self._settle_timer.start(int(self.lookahead.idle_seconds * 1000))
            self._sync_clock_scrolling()

    def _on_settle_timer(self) -> None:
        if self.widget_gone:
            return
        remaining_ms = round(self.lookahead.idle_seconds * 1000 - (monotonic() - self._last_scroll_at) * 1000)
        if remaining_ms > 15:
            self._settle_timer.start(remaining_ms)
            return
        self._sync_clock_scrolling()
        self._settle()

    def after_source_presented(self, callback, *arguments) -> None:
        QTimer.singleShot(0, partial(callback, *arguments))

    # The reader window contract's measurements Qt keeps by row instead

    def top_page(self) -> QtTopRow:
        """The row under the viewport's top edge, with the block and line of its fragment
        there: Qt measures that by pixel, where Textual counts cells. Cached per
        `(scroll_y, geometry_revision, viewport_width)` so `record_reader_scroll` and
        `repin_header` in the same frame share one `QListView::indexAt`."""
        if self.widget_gone:
            return QtTopRow()
        area = self._viewport.rect()
        scroll_val = self._vbar.value()
        cached = self._top_page_cache
        if (cached is not None and cached[0] == scroll_val
                and cached[1] == self.geometry_revision and cached[2] == area.width()):
            return cached[3]
        top_row = self.row_at_y(scroll_val)
        if top_row < 0:
            result: QtTopRow = QtTopRow()
        else:
            rect = self.row_rect(top_row)
            if rect.height() <= 0:
                result = QtTopRow()
            else:
                result = QtRowUnderTop(self, self.model_rows.fragments[top_row], rect.left(),
                                       self.rows.layout_width(rect.width()), -rect.top(), rect.height())
        self._top_page_cache = (scroll_val, self.geometry_revision, area.width(), result)
        return result

    def live_message_header(self) -> PinnedHeader:
        """Qt draws no live blocks: the draft is rows, so a row under the top edge pins."""
        return PinnedHeader((), 0, 0)

    def message_top(self, key) -> float | None:
        """Qt keeps rows by pixel: the row's top under the viewport, plus the offset."""
        model_rows = self.model_rows
        row = model_rows.row_of(key)
        if row < 0:
            return None
        return self.scroll_y + self.row_rect(row).top()

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

