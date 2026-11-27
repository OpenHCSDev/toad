"""Qt's painting of the shared name wave (`toad.client.name_wave`).

A working thread's sidebar line and a busy tab's title wave through their names as the
TUI's do: the same `NAME_WAVE` frame, read from the app's one `AnimationClock` when the
line paints, its band covering the cells `BandCells` names, in the accent, the name bold
while it runs. Nothing here keeps a period, a phase or a timer of its own.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap, QTextCharFormat, QTextLayout
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStyle, QStyleOptionTab, QStyleOptionViewItem, QStylePainter, QTabBar, QToolButton, QWidget
from pyqt_reactive.widgets.shared.list_item_delegate import MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.list_item_text_rendering import PreparedTextLayout
from pyqt_reactive.widgets.shared.tear_off_tab_widget import TearOffTabBar

from ui_theme.effects import Band

from toad.client.name_wave import BandCells, NameWave
from toad.motion import TAB_CLOSE, TAB_OPEN, TransitionTarget
from toad.qt.tap_flash import QtTextButton


def band_ink(span: tuple[int, int], length: int, ink: QTextCharFormat) -> QTextLayout.FormatRange:
    """The characters of ``span`` within a text ``length`` long, in the accent."""
    start, end = min(length, span[0]), min(length, span[1])
    band = QTextLayout.FormatRange()
    band.start, band.length = start, end - start
    band.format = ink
    return band


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
        baked = self.clone_layout(base, extra_format=band_ink((start, end), length, self.accent_format))
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
        self._row_images: dict[tuple[int, tuple[int, int] | None, int, int, int, bool, float], tuple[object, QImage]] = {}
        self._active_wave: tuple[object, tuple[int, int] | None] | None = None

    def _set_wave_accent(self, accent: QColor) -> None:
        super()._set_wave_accent(accent)
        self._banded_prepared.clear()
        self._row_images.clear()

    def forget_rows(self, *_changed) -> None:
        self._row_images.clear()
        super().forget_rows(*_changed)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        row = self._rows.get((index.row(), index.column(), index.internalId()))
        if row is None or index.model() is not self._rows_model:
            row = self.prepared_row(index)
        if row.object_state_path and self._manager is not None:
            super().paint(painter, option, index)
            return
        view = self.parent()
        wraps = view.wordWrap() if row.wrap_mode is None else row.wrap_mode.wrapped
        frame = QRect(option.rect)
        if wraps:
            frame.setLeft(0)
            frame.setWidth(view.viewport().width())
        width, height = frame.width(), frame.height()
        if width <= 0 or height <= 0:
            return
        item = view.itemFromIndex(index)
        running = item is not None and item.wave_running()
        span = item.painted_span if running else None
        dpr = painter.device().devicePixelRatioF()
        key = (id(row), span, width, height, option.state._value_, wraps, dpr)
        cached = self._row_images.get(key)
        if cached is not None and cached[0] is row:
            painter.drawImage(frame.topLeft(), cached[1])
            return
        if len(self._row_images) >= self.BANDED_KEPT:
            self._row_images.clear()
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
        self._row_images[key] = (row, image)
        painter.drawImage(frame.topLeft(), image)

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


class QtSessionTabBar(QtWaveBandCache, TearOffTabBar):
    """The workspace's tab bar: a busy tab's title waves as Textual's `SessionLabel` does.
    The title's line is the label with its one cell of padding each side, as the TUI's tab
    draws it, so the band covers the same characters. A tab that opens grows in and one that
    closes shrinks away, on the same clock."""

    padding_cells = 1
    TAB_GAP = 6
    """Inter-tab right margin (px); read by both the tab stylesheet and `_make_close_button`
    so the close button always sits inside the painted tab rather than the gap between tabs."""

    def __init__(self, clock, accent: QColor, ink: QColor) -> None:
        super().__init__()
        self.clock, self.ink = clock, ink
        self._init_wave_ink(accent)
        self.lines: dict[tuple[str, int], QTextLayout] = {}
        self._shown_titles: dict[tuple[int, str, int], tuple[QRect, str]] = {}
        self._tab_chrome: dict[tuple, QImage] = {}
        self.waves: dict[str, QtTabWave] = {}
        self.growing: dict[str, TabGrowth] = {}

    def set_colours(self, accent: QColor, ink: QColor) -> None:
        self.ink = ink
        self._set_wave_accent(accent)
        self._tab_chrome.clear()
        self.update()

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
        return True

    def _make_close_button(self, mode: str) -> QWidget:
        """A comfortable, theme-tinted close button tucked inside the tab's right edge
        instead of Fusion's tiny red cross clipped into the inter-tab gap."""
        container = QWidget(self)
        container.setObjectName("tab-close-slot")
        container.setStyleSheet("QWidget#tab-close-slot { background: transparent; }")
        layout = QHBoxLayout(container)
        right_inset = self.TAB_GAP + 2
        layout.setContentsMargins(2, 0, right_inset, 0)
        layout.setSpacing(0)
        button = QtTextButton(container)
        button.setObjectName("tab-close-button")
        button.setText("×")
        button.setToolTip("Close tab")
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        size = max(24, self.fontMetrics().height() + 4)
        button.setFixedSize(size, size)
        button.clicked.connect(lambda _checked=False, target=mode: self._request_close(target))
        layout.addWidget(button)
        container.setFixedSize(size + 2 + right_inset, size)
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

    def tabSizeHint(self, index: int) -> QSize:  # type: ignore[override]
        return self._grown(index, super().tabSizeHint(index))

    def minimumTabSizeHint(self, index: int) -> QSize:  # type: ignore[override]
        return self._grown(index, super().minimumTabSizeHint(index))

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
        """Cached text rectangle and elided title for ``index``; invalidated on tab/font/style/resize
        changes so 60-120 Hz wave ticks do not rebuild QStyleOptionTab + elidedText every tick."""
        text = self.tabText(index)
        tab_rect = self.tabRect(index)
        key = (index, text, tab_rect.width())
        cached = self._shown_titles.get(key)
        if cached is not None:
            return cached
        option = QStyleOptionTab()
        self.initStyleOption(option, index)
        rect = self.style().subElementRect(QStyle.SubElement.SE_TabBarTabText, option, self)
        shown = self.fontMetrics().elidedText(option.text, Qt.TextElideMode.ElideRight, rect.width())
        self._shown_titles[key] = (rect, shown)
        return rect, shown

    def shown_title(self, index: int) -> tuple[QStyleOptionTab, QRect, str]:
        """A tab's style option, the rectangle its title draws in, and the title as it fits
        there: what the paint draws, and what a wave's band is measured over."""
        option = QStyleOptionTab()
        self.initStyleOption(option, index)
        rect, shown = self._cached_title(index)
        return option, rect, shown

    def wave_span(self, wave: QtTabWave) -> tuple[int, int] | None:
        """The band's cells over the title of the tab ``wave`` runs in, padding included."""
        index = self.tab_of(wave.mode)
        if index < 0:
            return None
        _rect, shown = self._cached_title(index)
        return self.band_cells(wave.wave_frame(), len(shown) + 2 * self.padding_cells)

    def _tab_chrome_image(self, index: int, tab_rect: QRect, option: QStyleOptionTab, dpr: float) -> QImage:
        """Cache each busy tab's empty-text QSS background chrome so 60-120 Hz wave ticks
        blit one image instead of running Fusion's QSS `drawControl(CE_TabBarTab)` every tick."""
        key = (
            tab_rect.width(),
            tab_rect.height(),
            option.state.value,
            option.position.value,
            option.selectedPosition.value,
            dpr,
        )
        cached = self._tab_chrome.get(key)
        if cached is not None:
            return cached
        if len(self._tab_chrome) >= 32:
            self._tab_chrome.clear()
        image = QImage(
            max(1, round(tab_rect.width() * dpr)),
            max(1, round(tab_rect.height() * dpr)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        opt = QStyleOptionTab(option)
        opt.text = ""
        opt.rect = QRect(0, 0, tab_rect.width(), tab_rect.height())
        drawing = QPainter(image)
        self.style().drawControl(QStyle.ControlElement.CE_TabBarTab, opt, drawing, self)
        drawing.end()
        self._tab_chrome[key] = image
        return image

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QStylePainter(self)
        dpr = self.devicePixelRatioF()
        for index in range(self.count()):
            tab_rect = self.tabRect(index)
            if not tab_rect.intersects(event.rect()):
                # A wave repaints its own tab: the other tabs' titles were being measured
                # and elided again for each of its frames (the paint's largest Python cost
                # on a phone, 8% of the GUI thread's samples with a few tabs open).
                continue
            option, rect, shown = self.shown_title(index)
            wave = self.waves.get(self.tabData(index))
            if wave is None or not wave.wave_running():
                painter.drawControl(QStyle.ControlElement.CE_TabBarTab, option)
                continue
            chrome = self._tab_chrome_image(index, tab_rect, option, dpr)
            painter.drawImage(tab_rect.topLeft(), chrome)
            span = wave.band_drawn() or self.band_cells(wave.wave_frame(), len(shown) + 2 * self.padding_cells)
            start, end = span
            layout = self.bold_line(shown, rect.width())
            line = layout.lineAt(0)
            top = rect.top() + (rect.height() - line.height()) / 2
            painter.setPen(self.ink)
            baked = self.baked_band_layout(
                layout,
                (max(0, start - self.padding_cells), max(0, end - self.padding_cells)),
            )
            baked.draw(painter, QPointF(rect.left() + (rect.width() - line.naturalTextWidth()) / 2, top))

    def bold_line(self, shown: str, width: int) -> QTextLayout:
        """A working tab's title, bold, on one line ``width`` wide: laid out once for the
        title and width, since a frame of its wave moves the band's ink and not the text."""
        kept = self.lines.get((shown, width))
        if kept is None:
            if len(self.lines) >= self.KEPT:
                self.lines.clear()
            font = QFont(self.font())
            font.setBold(True)
            kept = self.lines[(shown, width)] = QTextLayout(shown, font)
            kept.setCacheEnabled(True)
            kept.beginLayout()
            kept.createLine().setLineWidth(width)
            kept.endLayout()
        return kept

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self._shown_titles.clear()
        self._tab_chrome.clear()
        super().resizeEvent(event)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self.lines.clear()  # laid out in the font that just changed
            self._banded.clear()
            self._shown_titles.clear()
            self._tab_chrome.clear()
        super().changeEvent(event)
