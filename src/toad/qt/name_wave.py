"""Qt's painting of the shared name wave (`toad.client.name_wave`).

A working thread's sidebar line and a busy tab's title wave through their names as the
TUI's do: the same `NAME_WAVE` frame, read from the app's one `AnimationClock` when the
line paints, its band covering the cells `BandCells` names, in the accent, the name bold
while it runs. Nothing here keeps a period, a phase or a timer of its own.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextLayout
from PySide6.QtWidgets import QStyle, QStyleOptionTab, QStylePainter
from pyqt_reactive.widgets.shared.list_item_delegate import MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.list_item_text_rendering import PreparedTextLayout
from pyqt_reactive.widgets.shared.tear_off_tab_widget import TearOffTabBar

from toad.client.name_wave import BandCells, NameWave


def waved_layout(text: str, font: QFont, formats, span: tuple[int, int], accent: QColor) -> QTextLayout:
    """``text`` bold, with the characters in ``span`` in the accent over its own formats."""
    bold = QFont(font)
    bold.setBold(True)
    layout = QTextLayout(text, bold)
    start, end = (min(len(text), edge) for edge in span)
    band = QTextLayout.FormatRange()
    band.start, band.length = start, end - start
    ink = QTextCharFormat()
    ink.setForeground(accent)
    band.format = ink
    layout.setFormats([*formats, band])
    return layout


class QtNameWaveDelegate(BandCells, MultilinePreviewItemDelegate):
    """The sidebar's row delegate: a line whose thread works (`SidebarItem.wave_span`) draws
    its title bold with the band's cells in the accent, as Textual's `ViewLabel` paints its
    first row. Other lines draw as pyqt-reactive prepares them."""

    def __init__(self, accent: QColor, *args) -> None:
        super().__init__(*args)
        self.accent = accent

    def _prepared_text(self, option, index) -> PreparedTextLayout:
        prepared = super()._prepared_text(option, index)
        item = self.parent().itemFromIndex(index)
        span = item.wave_span() if item is not None else None
        if span is None:
            return prepared
        title, *rest = prepared.paragraphs
        waved = waved_layout(title.text(), title.font(), title.formats(), span, self.accent)
        waved.setTextOption(title.textOption())
        waved.beginLayout()
        for number in range(title.lineCount()):
            line, laid = waved.createLine(), title.lineAt(number)
            if not line.isValid():
                break
            line.setLineWidth(laid.width())
            line.setPosition(laid.position())
        waved.endLayout()
        return PreparedTextLayout((waved, *rest), prepared.size, prepared.line_guides)


class QtTabWave(NameWave):
    """One tab title's wave, on the app's clock; the tab bar repaints the tab with it."""

    def __init__(self, bar: QtSessionTabBar, mode: str) -> None:
        self.bar, self.mode = bar, mode
        self.animation = None

    def wave_running(self) -> bool:
        return self.animation is not None

    def start_wave(self) -> None:
        self.animation = self.bar.clock.start(self.name_wave, self)

    def stop_wave(self) -> None:
        if self.animation is not None:
            self.animation.stop()
            self.animation = None

    @property
    def animation_visible(self) -> bool:
        return self.bar.isVisible()

    def repaint(self) -> None:
        self.bar.update()


class QtSessionTabBar(BandCells, TearOffTabBar):
    """The workspace's tab bar: a busy tab's title waves as Textual's `SessionLabel` does.
    The title's line is the label with its one cell of padding each side, as the TUI's tab
    draws it, so the band covers the same characters."""

    padding_cells = 1

    def __init__(self, clock, accent: QColor, ink: QColor) -> None:
        super().__init__()
        self.clock, self.accent, self.ink = clock, accent, ink
        self.waves: dict[str, QtTabWave] = {}

    def follow_tabs(self, tabs) -> None:
        """Each open tab's wave follows its busy state; a closed tab's stops."""
        for mode in set(self.waves) - {tab.mode_name for tab in tabs}:
            self.waves.pop(mode).stop_wave()
        for tab in tabs:
            self.waves.setdefault(tab.mode_name, QtTabWave(self, tab.mode_name)).follow_activity(tab.busy)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QStylePainter(self)
        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            wave = self.waves.get(self.tabData(index))
            if wave is None or not wave.wave_running():
                painter.drawControl(QStyle.ControlElement.CE_TabBarTab, option)
                continue
            text, option.text = option.text, ""
            painter.drawControl(QStyle.ControlElement.CE_TabBarTab, option)
            rect = self.style().subElementRect(QStyle.SubElement.SE_TabBarTabText, option, self)
            shown = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
            start, end = self.band_cells(wave.animation.frame(), len(shown) + 2 * self.padding_cells)
            ink = QTextLayout.FormatRange()
            ink.start, ink.length = 0, len(shown)
            plain = QTextCharFormat()
            plain.setForeground(self.ink)
            ink.format = plain
            layout = waved_layout(shown, self.font(), [ink], (max(0, start - self.padding_cells),
                                                             max(0, end - self.padding_cells)), self.accent)
            layout.beginLayout()
            line = layout.createLine()
            line.setLineWidth(rect.width())
            layout.endLayout()
            top = rect.top() + (rect.height() - line.height()) / 2
            layout.draw(painter, QPointF(rect.left() + (rect.width() - line.naturalTextWidth()) / 2, top))
