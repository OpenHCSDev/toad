"""Qt's painting of the shared name wave (`toad.client.name_wave`).

A working thread's sidebar line and a busy tab's title wave through their names as the
TUI's do: the same `NAME_WAVE` frame, read from the app's one `AnimationClock` when the
line paints, its band covering the cells `BandCells` names, in the accent, the name bold
while it runs. Nothing here keeps a period, a phase or a timer of its own.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPixmap, QTextCharFormat, QTextLayout
from PySide6.QtWidgets import QLabel, QStyle, QStyleOptionTab, QStylePainter
from pyqt_reactive.widgets.shared.list_item_delegate import MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.list_item_text_rendering import PreparedTextLayout
from pyqt_reactive.widgets.shared.tear_off_tab_widget import TearOffTabBar

from ui_theme.effects import Band

from toad.client.name_wave import BandCells, NameWave
from toad.motion import TAB_CLOSE, TAB_OPEN, TransitionTarget


def band_ink(span: tuple[int, int], length: int, accent: QColor) -> QTextLayout.FormatRange:
    """The characters of ``span`` within a text ``length`` long, in the accent."""
    start, end = (min(length, edge) for edge in span)
    band = QTextLayout.FormatRange()
    band.start, band.length = start, end - start
    ink = QTextCharFormat()
    ink.setForeground(accent)
    band.format = ink
    return band


class QtNameWaveDelegate(BandCells, MultilinePreviewItemDelegate):
    """The sidebar's row delegate: a line whose thread works (`SidebarItem.wave_span`) draws
    its title bold with the band's cells in the accent, as Textual's `ViewLabel` paints its
    first row. Other lines draw as pyqt-reactive prepares them.

    A frame of the wave changes which characters are in the accent and nothing else, so it
    lays no text out: the bold title is laid out once for the row's prepared text
    (`bold_titled`) and the band is ink drawn over it (`text_inks`). Laying the title out
    again for each frame was half of a row's paint (profiled on the sidebar's delegate,
    2026-11-22), and the sidebar's rows were 28% of a Pixel 8a's GUI thread while a fleet
    worked."""

    KEPT = 256
    """How many rows' bold titles are kept; past it they are all dropped and made again."""

    def __init__(self, accent: QColor, *args) -> None:
        super().__init__(*args)
        self.accent = accent
        # A row's prepared text and the same text with its title bold, by the prepared text's
        # identity: pyqt-reactive hands the same prepared text back until the row's text,
        # font or width changes, and a changed one is another object.
        self.bold: dict[int, tuple[PreparedTextLayout, PreparedTextLayout, int]] = {}
        # How many characters the title of the row being drawn has: the band is drawn within
        # them. Set as the row's text is taken, which a paint does before it asks for the ink.
        self.title_length = 0

    def _prepared_text(self, option, index) -> PreparedTextLayout:
        prepared = super()._prepared_text(option, index)
        item = self.parent().itemFromIndex(index)
        if item is None or not item.wave_running():
            return prepared
        _prepared, titled, self.title_length = self.bold_titled(prepared)
        return titled

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
        bold = QTextLayout(title.text(), font)
        bold.setFormats(title.formats())
        bold.setTextOption(title.textOption())
        bold.beginLayout()
        for number in range(title.lineCount()):
            line, laid = bold.createLine(), title.lineAt(number)
            if not line.isValid():
                break
            line.setLineWidth(laid.width())
            line.setPosition(laid.position())
        bold.endLayout()
        kept = self.bold[id(prepared)] = (
            prepared, PreparedTextLayout((bold, *rest), prepared.size, prepared.line_guides), len(title.text()))
        return kept

    def text_inks(self, index):
        item = self.parent().itemFromIndex(index)
        span = item.band_drawn() if item is not None else None
        if span is None:
            return ()
        return ([band_ink(span, self.title_length, self.accent)],)


class QtClockedWave(NameWave):
    """A name wave on the app's animation clock: the animation it holds is the running wave.
    A leaf says which clock that is and what a frame repaints."""

    animation = None

    def wave_clock(self):
        """The app's animation clock, as this wave's owner reaches it."""
        raise NotImplementedError

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

    @property
    def animation_visible(self) -> bool:
        return self.bar.isVisible()

    def wave_span(self) -> tuple[int, int] | None:
        return self.bar.wave_span(self) if self.wave_running() else None

    def repaint_wave(self) -> None:
        self.bar.repaint_tab(self.mode)


class TabGrowth(TransitionTarget):
    """A tab that just opened, widening from nothing on the shared clock (``TAB_OPEN``)."""

    def __init__(self, bar: QtSessionTabBar, mode: str) -> None:
        self.bar, self.mode, self.share = bar, mode, 0.0
        self.start_transition(bar.clock, TAB_OPEN)

    @property
    def animation_visible(self) -> bool:
        return self.bar.isVisible()

    def apply_amount(self, amount: float) -> None:
        self.share = amount
        self.bar.relayout()

    def land(self) -> None:
        self.bar.growing.pop(self.mode, None)
        self.bar.relayout()


class TabGhost(TransitionTarget):
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

    @property
    def animation_visible(self) -> bool:
        return self.bar.isVisible()

    def apply_amount(self, amount: float) -> None:
        width = round(self.rect.width() * amount)
        self.picture.setGeometry(self.rect.x() + (self.rect.width() - width) // 2,
                                 self.rect.y(), width, self.rect.height())

    def land(self) -> None:
        self.picture.deleteLater()


class QtSessionTabBar(BandCells, TearOffTabBar):
    """The workspace's tab bar: a busy tab's title waves as Textual's `SessionLabel` does.
    The title's line is the label with its one cell of padding each side, as the TUI's tab
    draws it, so the band covers the same characters. A tab that opens grows in and one that
    closes shrinks away, on the same clock."""

    padding_cells = 1

    def __init__(self, clock, accent: QColor, ink: QColor) -> None:
        super().__init__()
        self.clock, self.accent, self.ink = clock, accent, ink
        self.lines: dict[tuple[str, int], QTextLayout] = {}
        self.waves: dict[str, QtTabWave] = {}
        self.growing: dict[str, TabGrowth] = {}

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
        if moving:
            for mode in modes - set(shown):
                self.growing[mode] = TabGrowth(self, mode)
        for rect, picture in leaving:
            TabGhost(self, rect, picture)
        return True

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

    def shown_title(self, index: int) -> tuple[QStyleOptionTab, QRect, str]:
        """A tab's style option, the rectangle its title draws in, and the title as it fits
        there: what the paint draws, and what a wave's band is measured over."""
        option = QStyleOptionTab()
        self.initStyleOption(option, index)
        rect = self.style().subElementRect(QStyle.SubElement.SE_TabBarTabText, option, self)
        return option, rect, self.fontMetrics().elidedText(option.text, Qt.TextElideMode.ElideRight, rect.width())

    def wave_span(self, wave: QtTabWave) -> tuple[int, int] | None:
        """The band's cells over the title of the tab ``wave`` runs in, padding included."""
        index = self.tab_of(wave.mode)
        if index < 0:
            return None
        _option, _rect, shown = self.shown_title(index)
        return self.band_cells(wave.wave_frame(), len(shown) + 2 * self.padding_cells)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QStylePainter(self)
        for index in range(self.count()):
            if not self.tabRect(index).intersects(event.rect()):
                # A wave repaints its own tab: the other tabs' titles were being measured
                # and elided again for each of its frames (the paint's largest Python cost
                # on a phone, 8% of the GUI thread's samples with a few tabs open).
                continue
            option, rect, shown = self.shown_title(index)
            wave = self.waves.get(self.tabData(index))
            if wave is None or not wave.wave_running():
                painter.drawControl(QStyle.ControlElement.CE_TabBarTab, option)
                continue
            option.text = ""
            painter.drawControl(QStyle.ControlElement.CE_TabBarTab, option)
            start, end = self.wave_span(wave)
            layout = self.bold_line(shown, rect.width())
            line = layout.lineAt(0)
            top = rect.top() + (rect.height() - line.height()) / 2
            painter.setPen(self.ink)
            band = band_ink((max(0, start - self.padding_cells), max(0, end - self.padding_cells)), len(shown), self.accent)
            layout.draw(painter, QPointF(rect.left() + (rect.width() - line.naturalTextWidth()) / 2, top), [band])

    def bold_line(self, shown: str, width: int) -> QTextLayout:
        """A working tab's title, bold, on one line ``width`` wide: laid out once for the
        title and width, since a frame of its wave moves the band's ink and not the text."""
        kept = self.lines.get((shown, width))
        if kept is None:
            if len(self.lines) >= QtNameWaveDelegate.KEPT:
                self.lines.clear()
            font = QFont(self.font())
            font.setBold(True)
            kept = self.lines[(shown, width)] = QTextLayout(shown, font)
            kept.beginLayout()
            kept.createLine().setLineWidth(width)
            kept.endLayout()
        return kept

    def changeEvent(self, event) -> None:  # type: ignore[override]
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.lines.clear()  # laid out in the font that just changed
        super().changeEvent(event)
