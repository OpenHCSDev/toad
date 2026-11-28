"""Qt's painting of the shared name wave (`toad.client.name_wave`).

A working thread's sidebar line and a busy tab's title wave through their names as the
TUI's do: the same `NAME_WAVE` frame, read from the app's one `AnimationClock` when the
line paints, its band covering the cells `BandCells` names, in the accent, the name bold
while it runs. Nothing here keeps a period, a phase or a timer of its own.
"""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPixmap, QTextCharFormat, QTextLayout
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QStyle, QStyleOptionTab, QStyleOptionViewItem, QStylePainter, QTabBar, QToolButton, QWidget
from pyqt_reactive.widgets.shared.list_item_delegate import MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.list_item_text_rendering import PreparedTextLayout
from pyqt_reactive.widgets.shared.tear_off_tab_widget import TearOffTabBar

from ui_theme.effects import Band

from toad.client.name_wave import BandCells, NameWave, TitleMarquee
from toad.motion import TAB_CLOSE, TAB_OPEN, TransitionTarget
from toad.qt.tap_flash import QtTextButton


class QtWaveBandCache(BandCells):
    """Shared baked accent-band `QTextLayout` cache for Qt widgets waving a band across a bold
    title.

    Baking the band's `FormatRange` into `QTextLayout.setFormats` per `(base_layout, start, end)`
    lets `QTextLayout.draw(painter, origin)` take Qt's fast no-selections path (~2.4x faster than
    passing dynamic `selections` on every 60-120 Hz wave tick) while bounding cache entries."""

    KEPT = 256
    """How many base bold titles are kept; past it they are cleared."""
    BANDED_KEPT = 512
    """How many baked `(base_layout, start, end)` band layouts are kept; past it they are cleared."""

    def _init_wave_ink(self, accent: QColor) -> None:
        self.accent = accent
        self.accent_format = QTextCharFormat()
        self.accent_format.setForeground(accent)
        # Baked bold+accent QTextLayouts keyed by `(id(base), start, end)`.
        self._banded: dict[tuple[int, int, int], tuple[QTextLayout, QTextLayout]] = {}

    def _set_wave_accent(self, accent: QColor) -> None:
        self.accent = accent
        self.accent_format.setForeground(accent)
        self._banded.clear()

    @staticmethod
    def clone_layout(
        base: QTextLayout,
        *,
        font: QFont | None = None,
        extra_format: QTextLayout.FormatRange | None = None,
    ) -> QTextLayout:
        """Clone `base` onto the same line breaks with an optional bold font or extra format."""
        cloned = QTextLayout(base.text(), base.font() if font is None else font)
        cloned.setCacheEnabled(True)
        cloned.setTextOption(base.textOption())
        formats = list(base.formats())
        if extra_format is not None:
            formats.append(extra_format)
        cloned.setFormats(formats)
        cloned.beginLayout()
        for number in range(base.lineCount()):
            line, laid = cloned.createLine(), base.lineAt(number)
            if not line.isValid():
                break
            line.setLineWidth(laid.width())
            line.setPosition(laid.position())
        cloned.endLayout()
        return cloned

    def baked_band_layout(self, base: QTextLayout, span: tuple[int, int]) -> QTextLayout:
        """`base` with `span` baked into its `FormatRange`s, cached per `(base, start, end)`."""
        length = len(base.text())
        start, end = min(length, max(0, span[0])), min(length, max(0, span[1]))
        if start >= end:
            return base
        key = (id(base), start, end)
        hit = self._banded.get(key)
        if hit is not None and hit[0] is base:
            return hit[1]
        if len(self._banded) >= self.BANDED_KEPT:
            self._banded.clear()
        band = QTextLayout.FormatRange()
        band.start, band.length = start, end - start
        band.format = self.accent_format
        baked = self.clone_layout(base, extra_format=band)
        self._banded[key] = (base, baked)
        return baked


class QtNameWaveDelegate(QtWaveBandCache, MultilinePreviewItemDelegate):
    """The sidebar's row delegate: a line whose thread works (`SidebarItem.wave_span`) draws
    its title bold with the band's cells in the accent, as Textual's `ViewLabel` paints its
    first row. Other lines draw as pyqt-reactive prepares them.

    A frame of the wave changes which characters are in the accent and nothing else: the bold
    title (`bold_titled`) and each accent band position (`baked_band_layout`) are laid out once
    and drawn through Qt's fast selection-free `QTextLayout.draw(painter, origin)` path."""

    def __init__(self, accent: QColor, *args) -> None:
        super().__init__(*args)
        self._init_wave_ink(accent)
        # A row's prepared text and the same text with its title bold, by the prepared text's
        # identity: pyqt-reactive hands the same prepared text back until the row's text,
        # font or width changes, and a changed one is another object.
        self.bold: dict[int, tuple[PreparedTextLayout, PreparedTextLayout, int]] = {}
        self._banded_prepared: dict[tuple[int, int, int], tuple[PreparedTextLayout, PreparedTextLayout]] = {}
        self._view = self.parent()
        self._viewport = self._view.viewport()
        self._row_images: dict[
            int,
            tuple[
                object,
                dict[tuple[bool, tuple[int, int] | None, int, int, int, bool, int, float], tuple[QImage, bool]],
            ],
        ] = {}
        self._row_image_count = 0
        self._active_wave: tuple[object, tuple[int, int] | None] | None = None

    def _set_wave_accent(self, accent: QColor) -> None:
        super()._set_wave_accent(accent)
        self._banded_prepared.clear()
        self._row_images.clear()
        self._row_image_count = 0

    def forget_rows(self, *_changed) -> None:
        self._row_images.clear()
        self._row_image_count = 0
        super().forget_rows(*_changed)

    def _rows_forgotten(self, rows) -> None:
        for row in rows:
            rid = id(row)
            bucket = self._row_images.get(rid)
            if bucket is not None and bucket[0] is row:
                self._row_image_count -= len(bucket[1])
                self._row_images.pop(rid, None)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        row = self._rows.get((index.row(), index.column(), index.internalId()))
        if row is None:
            row = self.prepared_row(index)
        if row.object_state_path and self._manager is not None:
            super().paint(painter, option, index)
            return
        view = self._view
        vp = self._viewport
        rect = option.rect
        item = view.itemFromIndex(index)
        running = item is not None and item.wave_running()
        span = item.painted_span if running else None
        dpr = painter.device().devicePixelRatioF()
        rid = id(row)
        wraps = row.wrap_mode.wrapped if row.wrap_mode is not None else view.wordWrap()
        vp_width = vp.width()
        hovered = view.underMouse() and rect.contains(vp.mapFromGlobal(QCursor.pos()))
        variant = (
            running,
            span,
            rect.width(),
            rect.height(),
            item is not None and item.isSelected(),
            view.hasFocus(),
            view.isActiveWindow(),
            hovered,
            wraps,
            vp_width,
            dpr,
        )
        bucket = self._row_images.get(rid)
        if bucket is not None and bucket[0] is row:
            cached = bucket[1].get(variant)
            if cached is not None:
                image, cached_wraps = cached
                if cached_wraps:
                    painter.drawImage(0, rect.top(), image)
                else:
                    painter.drawImage(rect.topLeft(), image)
                return
        frame = QRect(rect)
        if wraps:
            frame.setLeft(0)
            frame.setWidth(vp_width)
        width, height = frame.width(), frame.height()
        if width <= 0 or height <= 0:
            return
        if self._row_image_count >= self.BANDED_KEPT:
            self._row_images.clear()
            self._row_image_count = 0
            bucket = None
        image = QImage(
            max(1, round(width * dpr)),
            max(1, round(height * dpr)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        local_option = QStyleOptionViewItem(option)
        local_option.rect = QRect(0, 0, width, height)
        local_painter = QPainter(image)
        self._active_wave = (running, span)
        try:
            super().paint(local_painter, local_option, index)
        finally:
            self._active_wave = None
            local_painter.end()
        if bucket is None or bucket[0] is not row:
            self._row_images[rid] = (row, {variant: (image, wraps)})
        else:
            bucket[1][variant] = (image, wraps)
        self._row_image_count += 1
        painter.drawImage(frame.topLeft(), image)

    def sizeHint(self, option: QStyleOptionViewItem, index):  # type: ignore[override]
        """Wave bolding and accent-band format ranges preserve `prepared.size`, so sizeHint
        reads the base prepared layout without building bold or banded QTextLayouts."""
        previous = self._active_wave
        self._active_wave = (False, None)
        try:
            return super().sizeHint(option, index)
        finally:
            self._active_wave = previous

    def _prepared_text(self, option, index) -> PreparedTextLayout:
        prepared = super()._prepared_text(option, index)
        if self._active_wave is not None:
            running, span = self._active_wave
        else:
            item = self.parent().itemFromIndex(index)
            running = item is not None and item.wave_running()
            span = item.painted_span if running else None
        if not running:
            return prepared
        pid = id(prepared)
        kept = self.bold.get(pid)
        if kept is None or kept[0] is not prepared:
            kept = self.bold_titled(prepared)
        titled, length = kept[1], kept[2]
        if span is None:
            return titled
        start, end = min(length, max(0, span[0])), min(length, max(0, span[1]))
        if start >= end:
            return titled
        key = (pid, start, end)
        hit = self._banded_prepared.get(key)
        if hit is not None and hit[0] is prepared:
            return hit[1]
        if len(self._banded_prepared) >= self.BANDED_KEPT:
            self._banded_prepared.clear()
        baked = self.baked_band_layout(titled.paragraphs[0], (start, end))
        built = PreparedTextLayout((baked, *titled.paragraphs[1:]), titled.size, titled.line_guides)
        self._banded_prepared[key] = (prepared, built)
        return built

    def bold_titled(self, prepared: PreparedTextLayout) -> tuple[PreparedTextLayout, PreparedTextLayout, int]:
        """``prepared``, the same text with its title bold on the lines the title already
        had, and the title's length in characters."""
        kept = self.bold.get(id(prepared))
        if kept is not None and kept[0] is prepared:
            return kept
        if len(self.bold) >= self.KEPT:
            self.bold.clear()
        title, *rest = prepared.paragraphs
        font = QFont(title.font())
        font.setBold(True)
        bold = self.clone_layout(title, font=font)
        kept = self.bold[id(prepared)] = (
            prepared, PreparedTextLayout((bold, *rest), prepared.size, prepared.line_guides), len(title.text()))
        return kept


class QtClockedWave(NameWave):
    """A name wave on the app's animation clock: the animation it holds is the running wave.
    A leaf says which clock that is and what a frame repaints."""

    animation = None

    def wave_clock(self):
        """The app's animation clock, as this wave's owner reaches it."""
        raise NotImplementedError

    def wave_visible(self) -> bool:
        """Whether this wave's widget is currently shown on screen."""
        raise NotImplementedError

    @property
    def animation_visible(self) -> bool:
        return self.wave_visible()

    def wave_running(self) -> bool:
        return self.animation is not None

    def start_wave(self) -> None:
        self.animation = self.wave_clock().start(self.name_wave, self)

    def stop_wave(self) -> None:
        if self.animation is not None:
            self.animation.stop()
            self.animation = None
        self.wave_frame_drawn()  # no band now: the idle line, if a band was drawn

    def repaint(self) -> None:
        """The clock's frame (`AnimationTarget.repaint`)."""
        self.wave_frame_drawn()

    def wave_frame(self) -> Band:
        """The shared name-wave band at the app clock's current frame."""
        if self.animation is None:
            raise RuntimeError("An idle name has no working frame")
        return self.animation.frame()


class QtTabWave(QtClockedWave):
    """One tab title's wave, on the app's clock; the tab bar repaints the tab with it."""

    def __init__(self, bar: QtSessionTabBar, mode: str) -> None:
        self.bar, self.mode = bar, mode

    def wave_clock(self):
        return self.bar.clock

    def wave_visible(self) -> bool:
        return self.bar.isVisible()

    def wave_cells(self) -> tuple[int, int] | None:
        return self.bar.wave_span(self)

    def repaint_wave(self) -> None:
        self.bar.repaint_tab(self.mode)


class TabTransition(TransitionTarget):
    """A tab-bar transition whose animation visibility follows its owning ``bar``."""

    bar: QtSessionTabBar

    @property
    def animation_visible(self) -> bool:
        return self.bar.isVisible()


class TabGrowth(TabTransition):
    """A tab that just opened, widening from nothing on the shared clock (``TAB_OPEN``)."""

    def __init__(self, bar: QtSessionTabBar, mode: str) -> None:
        self.bar, self.mode, self.share = bar, mode, 0.0
        self.start_transition(bar.clock, TAB_OPEN)

    def apply_amount(self, amount: float) -> None:
        self.share = amount
        self.bar.relayout()

    def land(self) -> None:
        self.bar.growing.pop(self.mode, None)
        self.bar.relayout()


class TabGhost(TabTransition):
    """A tab that just closed, as it last looked, narrowing to nothing where it stood
    (``TAB_CLOSE``): the bar has already dropped it, so its neighbours take its place."""

    def __init__(self, bar: QtSessionTabBar, rect: QRect, picture: QPixmap) -> None:
        self.bar, self.rect = bar, rect
        self.picture = QLabel(bar)
        self.picture.setWindowFlags(Qt.WindowType.Widget)
        self.picture.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.picture.setScaledContents(True)
        self.picture.setPixmap(picture)
        self.picture.setGeometry(rect)
        self.picture.show()
        self.picture.raise_()
        self.start_transition(bar.clock, TAB_CLOSE)

    def apply_amount(self, amount: float) -> None:
        width = round(self.rect.width() * amount)
        self.picture.setGeometry(self.rect.x() + (self.rect.width() - width) // 2,
                                 self.rect.y(), width, self.rect.height())

    def land(self) -> None:
        self.picture.deleteLater()


class QtTabMarquee(TitleMarquee):
    """One shared banner-scroll animation for all overflowing tabs on a `QtSessionTabBar`."""

    def __init__(self, bar: QtSessionTabBar) -> None:
        self.bar = bar
        self.animation = None
        self.painted_offsets: dict[object, float] = {}
        self._painted_px: dict[object, int] = {}

    @property
    def animation_visible(self) -> bool:
        return self.bar.isVisible()

    def marquee_running(self) -> bool:
        return self.animation is not None

    def start_marquee(self) -> None:
        self.painted_offsets.clear()
        self._painted_px.clear()
        self.animation = self.bar.clock.start(self.marquee_effect, self)

    def stop_marquee(self) -> None:
        if self.animation is not None:
            self.animation.stop()
            self.animation = None
        self.painted_offsets.clear()
        self._painted_px.clear()

    def marquee_elapsed(self) -> float:
        return 0.0 if self.animation is None else self.animation.frame().value

    def repaint(self) -> None:
        """Compute marquee offsets once per tick and repaint only overflowing tabs that moved."""
        self.bar._repaint_marquee_tabs(self.painted_offsets, self._painted_px)


class QtSessionTabBar(QtWaveBandCache, TearOffTabBar):
    """The workspace's tab bar: compact tabs sized to their title up to a width cap so at least
    three tabs fit across Android's tab strip, with overflowing titles scrolling like a banner
    on the shared `AnimationClock` and busy tabs waving in the theme accent."""

    padding_cells = 1
    TAB_GAP = 3
    """Inter-tab right margin (px); read by both the tab stylesheet and `_make_close_button`
    so the close button sits cleanly inside the painted tab without dead padding."""
    TAB_PAD_LEFT = 5
    TAB_PAD_RIGHT = 1
    TAB_TEXT_CLOSE_GAP = 1
    MAX_TITLE_CHARS = 16
    MIN_VISIBLE_TABS = 3

    def __init__(self, clock, accent: QColor, ink: QColor, inactive_ink: QColor | None = None) -> None:
        super().__init__()
        self.clock, self.ink = clock, ink
        self.inactive_ink = ink if inactive_ink is None else inactive_ink
        self._init_wave_ink(accent)
        self.lines: dict[tuple[str, bool], QTextLayout] = {}
        self._shown_titles: dict[tuple[int, str, int], tuple[QRect, str]] = {}
        self._tab_chrome: dict[tuple, QImage] = {}
        self.waves: dict[str, QtTabWave] = {}
        self.growing: dict[str, TabGrowth] = {}
        self.marquee = QtTabMarquee(self)
        self._strip_width = 0

    def set_colours(self, accent: QColor, ink: QColor, inactive_ink: QColor | None = None) -> None:
        self.ink = ink
        self.inactive_ink = ink if inactive_ink is None else inactive_ink
        self._set_wave_accent(accent)
        self._tab_chrome.clear()
        self.update()

    def sync_strip_width(self, width: int) -> None:
        """Keep the 3-tab width cap synced with the visible tab strip viewport width."""
        width = max(0, int(width))
        if width == self._strip_width:
            return
        self._strip_width = width
        self._shown_titles.clear()
        self._tab_chrome.clear()
        self.relayout()
        self._sync_marquee()

    def _strip_viewport_width(self) -> int:
        if self._strip_width > 0:
            return self._strip_width
        parent = self.parentWidget()
        if parent is not None and isinstance(parent.parentWidget(), QScrollArea) and parent.width() > 0:
            return parent.width()
        return 0

    def _close_slot_metrics(self) -> tuple[int, int, int]:
        """(button_width_px, button_height_px, slot_width_px) for the right-side close button.
        Height stays thumb-friendly while width stays tight around `×` so tabs have no dead
        trailing gap between the title and close glyph."""
        fm = self.fontMetrics()
        height = max(24, fm.height() + 2)
        width = max(18, ceil(fm.horizontalAdvance("×")) + 10)
        return width, height, width + self.TAB_GAP

    def _tab_chrome_width(self) -> int:
        """Horizontal non-text pixels per tab: left pad + text/close gap + close slot + right pad."""
        _btn_w, _btn_h, slot_w = self._close_slot_metrics()
        return self.TAB_PAD_LEFT + self.TAB_TEXT_CLOSE_GAP + slot_w + self.TAB_PAD_RIGHT

    def _max_tab_width(self) -> int:
        """Maximum width (px) for one tab: bounded by `MAX_TITLE_CHARS` and by 1/3 of the
        visible tab strip so narrow screens (Android) generally show at least three tabs."""
        fm = self.fontMetrics()
        avg_char = max(1, fm.averageCharWidth())
        chrome = self._tab_chrome_width()
        min_width = chrome + 4 * avg_char
        char_cap = chrome + self.MAX_TITLE_CHARS * avg_char
        strip_w = self._strip_viewport_width()
        if strip_w > 0:
            return max(min_width, min(char_cap, strip_w // self.MIN_VISIBLE_TABS))
        return char_cap

    def show_tabs(self, entries: list[tuple[str, str]]) -> bool:
        """Draw ``entries`` (title, mode) as the bar's tabs; whether anything changed. The same
        tabs in the same order only retitle the ones whose title changed, as Textual's tab
        strip reconciles its labels: rebuilding every tab relaid and repainted the bar on each
        sidebar observation (Tristan's phone, a burst of arrivals, 2026-11-18). Otherwise,
        compared with what the bar showed: a mode that is new grows in, a mode that is gone
        leaves a shrinking picture of itself. The first drawing, a restore, appears at once."""
        current = [(self.tabText(index), self.tabData(index)) for index in range(self.count())]
        if current == entries:
            return False
        self._shown_titles.clear()
        if [mode for _, mode in current] == [mode for _, mode in entries]:
            for index, (title, _) in enumerate(entries):
                if current[index][0] != title:
                    self.setTabText(index, title)
            self._sync_marquee()
            return True
        shown = {self.tabData(index): self.tabRect(index) for index in range(self.count())}
        modes = {mode for _, mode in entries}
        moving = bool(shown) and self.clock.enabled and self.isVisible()
        leaving = [(rect, self.grab(rect)) for mode, rect in shown.items()
                   if moving and mode not in modes and rect.isValid()]
        while self.count():
            self.removeTab(0)
        for title, mode in entries:
            index = self.addTab(title)
            self.setTabData(index, mode)
            self.setTabButton(index, QTabBar.ButtonPosition.RightSide, self._make_close_button(mode))
        if moving:
            for mode in modes - set(shown):
                self.growing[mode] = TabGrowth(self, mode)
        for rect, picture in leaving:
            TabGhost(self, rect, picture)
        self._sync_marquee()
        return True

    def _make_close_button(self, mode: str) -> QWidget:
        """A comfortable, theme-tinted close button tucked inside the tab's right edge
        without dead horizontal padding next to the title."""
        container = QWidget(self)
        container.setObjectName("tab-close-slot")
        container.setStyleSheet("QWidget#tab-close-slot { background: transparent; }")
        layout = QHBoxLayout(container)
        btn_w, btn_h, slot_w = self._close_slot_metrics()
        layout.setContentsMargins(0, 0, self.TAB_GAP, 0)
        layout.setSpacing(0)
        button = QtTextButton(container)
        button.setObjectName("tab-close-button")
        button.setText("×")
        button.setToolTip("Close tab")
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(btn_w, btn_h)
        button.clicked.connect(lambda _checked=False, target=mode: self._request_close(target))
        layout.addWidget(button)
        container.setFixedSize(slot_w, btn_h)
        return container

    def _request_close(self, mode: str) -> None:
        index = self.tab_of(mode)
        if index >= 0:
            self.tabCloseRequested.emit(index)

    def relayout(self) -> None:
        """Lay the tabs out again with the growing tabs' current widths."""
        self.setIconSize(self.iconSize())

    def _grown(self, index: int, hint: QSize) -> QSize:
        growth = self.growing.get(self.tabData(index))
        if growth is not None:
            hint.setWidth(round(hint.width() * growth.share))
        return hint

    def _compact_tab_size(self, index: int, base: QSize) -> QSize:
        text = self.tabText(index)
        text_w = ceil(self.title_line(text, bold=True).lineAt(0).naturalTextWidth())
        _btn_w, btn_h, _slot_w = self._close_slot_metrics()
        width = min(self._max_tab_width(), self._tab_chrome_width() + max(8, text_w))
        height = max(btn_h + 6, base.height())
        return QSize(width, height)

    def tabSizeHint(self, index: int) -> QSize:  # type: ignore[override]
        return self._grown(index, self._compact_tab_size(index, super().tabSizeHint(index)))

    def minimumTabSizeHint(self, index: int) -> QSize:  # type: ignore[override]
        return self._grown(index, self._compact_tab_size(index, super().minimumTabSizeHint(index)))

    def follow_tabs(self, tabs) -> None:
        """Each open tab's wave follows its busy state; a closed tab's stops."""
        for mode in set(self.waves) - {tab.mode_name for tab in tabs}:
            self.waves.pop(mode).stop_wave()
        for tab in tabs:
            self.waves.setdefault(tab.mode_name, QtTabWave(self, tab.mode_name)).follow_activity(tab.busy)

    def tab_of(self, mode: str) -> int:
        """The index of the tab showing ``mode``, or -1 when the bar shows none."""
        return next((index for index in range(self.count()) if self.tabData(index) == mode), -1)

    def repaint_tab(self, mode: str) -> None:
        """Paint the one tab showing ``mode``; the others' pixels stand."""
        index = self.tab_of(mode)
        if index >= 0:
            self.update(self.tabRect(index))

    def _cached_title(self, index: int) -> tuple[QRect, str]:
        """Cached text rectangle and full title for ``index``; derived directly from `tabRect`
        and the close-button slot so Fusion's extra `SE_TabBarTabText` gap never clips early."""
        text = self.tabText(index)
        tab_rect = self.tabRect(index)
        key = (index, text, tab_rect.width())
        cached = self._shown_titles.get(key)
        if cached is not None:
            return cached
        _btn_w, _btn_h, slot_w = self._close_slot_metrics()
        close_slot = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        left = tab_rect.left() + self.TAB_PAD_LEFT
        if (close_slot is not None and close_slot.width() > 0
                and tab_rect.left() < close_slot.geometry().left() <= tab_rect.right()):
            right = max(left, close_slot.geometry().left() - self.TAB_TEXT_CLOSE_GAP)
        else:
            if close_slot is not None and close_slot.width() > 0:
                slot_w = close_slot.width()
            right = max(left, tab_rect.right() - slot_w - self.TAB_PAD_RIGHT - self.TAB_TEXT_CLOSE_GAP)
        rect = QRect(left, tab_rect.top(), max(0, right - left + 1), tab_rect.height())
        self._shown_titles[key] = (rect, text)
        return rect, text

    def shown_title(self, index: int) -> tuple[QStyleOptionTab, QRect, str]:
        """A tab's style option, the rectangle its title draws in, and its title."""
        option = QStyleOptionTab()
        self.initStyleOption(option, index)
        rect, text = self._cached_title(index)
        return option, rect, text

    def _tab_overflows(self, index: int) -> bool:
        rect, text = self._cached_title(index)
        if rect.width() <= 0 or not text:
            return False
        wave = self.waves.get(self.tabData(index))
        bold = (index == self.currentIndex()) or (wave is not None and wave.wave_running())
        return self.title_line(text, bold=bold).lineAt(0).naturalTextWidth() > rect.width() + 0.5

    def _sync_marquee(self) -> None:
        if not self.isVisible():
            return
        overflowing = any(self._tab_overflows(index) for index in range(self.count()))
        self.marquee.follow_overflow(overflowing)

    def _repaint_marquee_tabs(self, offsets: dict[object, float], painted_px: dict[object, int]) -> None:
        any_overflow = False
        elapsed = self.marquee.marquee_elapsed()
        effect = self.marquee.marquee_effect
        for index in range(self.count()):
            rect, text = self._cached_title(index)
            if rect.width() <= 0 or not text:
                continue
            mode = self.tabData(index)
            wave = self.waves.get(mode)
            bold = (index == self.currentIndex()) or (wave is not None and wave.animation is not None)
            full_w = self.title_line(text, bold=bold).lineAt(0).naturalTextWidth()
            if full_w <= rect.width() + 0.5:
                continue
            any_overflow = True
            offset = effect.offset(elapsed, full_w, rect.width())
            px = round(offset)
            key = index if mode is None else mode
            offsets[key] = offset
            if painted_px.get(key) != px:
                painted_px[key] = px
                self.update(self.tabRect(index))
        if not any_overflow:
            self.marquee.follow_overflow(False)

    def wave_span(self, wave: QtTabWave) -> tuple[int, int] | None:
        """The band's cells over the title of the tab ``wave`` runs in, padding included."""
        index = self.tab_of(wave.mode)
        if index < 0:
            return None
        _rect, shown = self._cached_title(index)
        return self.band_cells(wave.wave_frame(), len(shown) + 2 * self.padding_cells)

    def _tab_chrome_image(self, index: int, tab_rect: QRect, chrome_key: tuple, dpr: float) -> QImage:
        """Cache each tab's empty-text QSS background chrome so wave and marquee ticks blit one
        image instead of running Fusion's QSS `drawControl(CE_TabBarTab)` or touching Python
        `QStyle.StateFlag` enums on every frame."""
        cached = self._tab_chrome.get(chrome_key)
        if cached is not None:
            return cached
        if len(self._tab_chrome) >= 32:
            self._tab_chrome.clear()
        option = QStyleOptionTab()
        self.initStyleOption(option, index)
        image = QImage(
            max(1, round(tab_rect.width() * dpr)),
            max(1, round(tab_rect.height() * dpr)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        option.text = ""
        option.rect = QRect(0, 0, tab_rect.width(), tab_rect.height())
        drawing = QPainter(image)
        self.style().drawControl(QStyle.ControlElement.CE_TabBarTab, option, drawing, self)
        drawing.end()
        self._tab_chrome[chrome_key] = image
        return image

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QStylePainter(self)
        dpr = self.devicePixelRatioF()
        event_rect = event.rect()
        count = self.count()
        current_index = self.currentIndex()
        hover_index = self.tabAt(self.mapFromGlobal(QCursor.pos())) if self.underMouse() else -1
        shown_titles = self._shown_titles
        tab_chrome = self._tab_chrome
        lines = self.lines
        banded = self._banded
        waves = self.waves
        painted_offsets = self.marquee.painted_offsets
        gap = self.marquee.marquee_effect.gap
        pad_cells = self.padding_cells
        any_overflow = False
        for index in range(count):
            tab_rect = self.tabRect(index)
            if not tab_rect.intersects(event_rect):
                # A wave or marquee repaints its own tab: untouched tabs skip all layout work.
                continue
            text = self.tabText(index)
            tab_w = tab_rect.width()
            title_hit = shown_titles.get((index, text, tab_w))
            if title_hit is None:
                title_hit = self._cached_title(index)
            rect, shown = title_hit
            selected = index == current_index
            hovered = index == hover_index
            pos_tag = 0 if count == 1 else (1 if index == 0 else (2 if index == count - 1 else 3))
            adj_selected = 1 if index + 1 == current_index else (2 if index - 1 == current_index else 0)
            chrome_key = (tab_w, tab_rect.height(), selected, hovered, pos_tag, adj_selected, dpr)
            chrome = tab_chrome.get(chrome_key)
            if chrome is None:
                chrome = self._tab_chrome_image(index, tab_rect, chrome_key, dpr)
            painter.drawImage(tab_rect.topLeft(), chrome)
            if rect.width() <= 0 or not shown:
                continue
            mode = self.tabData(index)
            wave = waves.get(mode)
            waving = wave is not None and wave.animation is not None
            bold = waving or selected
            layout = lines.get((shown, bold))
            if layout is None:
                layout = self.title_line(shown, bold=bold)
            if waving:
                span = wave.painted_span
                if span is None:
                    span = self.band_cells(wave.wave_frame(), len(shown) + 2 * pad_cells)
                length = len(shown)
                s = min(length, max(0, span[0] - pad_cells))
                e = min(length, max(0, span[1] - pad_cells))
                if s < e:
                    hit = banded.get((id(layout), s, e))
                    drawn = hit[1] if hit is not None and hit[0] is layout else self.baked_band_layout(layout, (s, e))
                else:
                    drawn = layout
            else:
                drawn = layout
            line = drawn.lineAt(0)
            full_w = line.naturalTextWidth()
            top = rect.top() + (rect.height() - line.height()) / 2
            painter.setPen(self.ink if (waving or selected or hovered) else self.inactive_ink)
            painter.save()
            painter.setClipRect(rect)
            if full_w > rect.width() + 0.5:
                any_overflow = True
                offset = painted_offsets.get(index if mode is None else mode, 0.0)
                x = rect.left() - offset
                drawn.draw(painter, QPointF(x, top))
                second_x = x + full_w + gap
                if second_x < rect.right():
                    drawn.draw(painter, QPointF(second_x, top))
            else:
                drawn.draw(painter, QPointF(rect.left(), top))
            painter.restore()
        if any_overflow and self.marquee.animation is None:
            self.marquee.follow_overflow(True)

    def title_line(self, shown: str, *, bold: bool) -> QTextLayout:
        """One tab title laid out on a single unwrapped line so naturalTextWidth is exact."""
        kept = self.lines.get((shown, bold))
        if kept is None:
            if len(self.lines) >= self.KEPT:
                self.lines.clear()
            font = QFont(self.font())
            font.setBold(bold)
            kept = self.lines[(shown, bold)] = QTextLayout(shown, font)
            kept.setCacheEnabled(True)
            kept.beginLayout()
            kept.createLine().setLineWidth(1_000_000)
            kept.endLayout()
        return kept

    def bold_line(self, shown: str, _width: int = 0) -> QTextLayout:
        """A working tab's title, bold, on one line."""
        return self.title_line(shown, bold=True)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._sync_marquee()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self._shown_titles.clear()
        self._tab_chrome.clear()
        super().resizeEvent(event)
        self._sync_marquee()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self.lines.clear()  # laid out in the font that just changed
            self._banded.clear()
            self._shown_titles.clear()
            self._tab_chrome.clear()
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._sync_marquee()
