"""Qt's one pop-up menu: renders a tuple of toolkit-neutral MenuEntry rows as
`[bold key] [label / description]`, matching the Textual `Menu` widget's row structure.

A single widget renders every pop-up Toad opens (the application menu, a message's and a
sidebar row's held/right-click menu, the bus-connect choices, a sort choice), so they share
rendering, placement, dismissal and click handling, and the only thing that differs is
which MenuEntry tuple each one supplies and where it was asked for.

It floats: a child of the window placed over the window's content and outside every layout,
so opening or closing it moves nothing underneath. It is not a top-level window (a QMenu or
a `Qt.Popup`): on Qt for Android every QWindow needs its own EGL surface, and a second one
deadlocks the compositor.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial

from PySide6.QtCore import QEvent, QObject, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui_theme.scheme import FloatHoverToneColour, FloatToneColour, MutedColour, RuleColour

from pyqt_reactive.widgets.fitted_text import ElidedLine
from toad.client import platform as toad_platform

from toad.client.block_menu import BlockMenu
from toad.client.input_modality import InputModality
from toad.client.menu_entry import MenuEntry, MenuRowDisplay
from toad.qt.lines import QtLineRenderer
from toad.qt.metrics import UiGap, delete_layout_widgets


def platform_input() -> type[InputModality]:
    """Read the host platform's declared input modality (touch on Android, keys elsewhere)."""
    return toad_platform.host.input_modality


class QtMenuRow(QWidget):
    """One menu row: a bold key column (when the menu's modality shows keys) and a label
    column that fills the rest. Under touch the description is a second line elided to the
    row's width; under keys it follows the label. A click fires the entry's action; the
    whole row is the clickable target, so a fat-fingered tap on the phone still counts.

    The labels are laid over a QPushButton. A QFrame row whose own area was the target, with
    wrapping text (QLabel word wrap, then WrappedText), was tried (2026-11-18): after the
    panel opened over two tabs, qasync's loop ran no callbacks once the window closed, and
    this button row did not. The cause inside the QFrame row is not established."""

    def __init__(self, entry: MenuEntry, menu: MenuRowDisplay, chosen: Callable[[MenuEntry], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._entry = entry
        self._chosen = chosen
        self._button = QPushButton(self)
        self._button.setFlat(True)
        self._button.clicked.connect(self._fire)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._button)
        inner = QHBoxLayout(self._button)
        inner.setContentsMargins(UiGap.dialog, UiGap.tight, UiGap.dialog, UiGap.tight)
        inner.setSpacing(UiGap.dialog)
        if keys := menu.row_keys(entry):
            key = QLabel(keys, self._button)
            key.setStyleSheet("font-weight: bold;")
            key.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            inner.addWidget(key)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.label = ElidedLine(menu.row_text(entry))
        self.label.setParent(self._button)
        text.addWidget(self.label)
        if subtext := menu.row_subtext(entry):
            description = ElidedLine(subtext)
            description.setParent(self._button)
            description.setObjectName("toad-menu-description")  # muted (`QtMenu.paint`)
            text.addWidget(description)
        inner.addLayout(text, 1)
        # The row is as tall as its lines need, as the layout measures them (each line's own
        # minimum, margins included), never less than a touch target. An explicit minimum
        # overrides the layout's own: one summed from line spacing gave each line 12 px of a
        # 17 px font and cut every descender on the phone (`qt_drive menu_text`).
        height = inner.totalMinimumSize().height()
        self._button.setMinimumHeight(max(44, menu.input_modality.row_height, height))

    def _fire(self) -> None:
        self._chosen(self._entry)


class QtMenu(BlockMenu, QFrame):
    """The window's pop-up menu: one surface of MenuEntry rows floating over the window's
    content (see the module docstring for why it is a child widget). `show_entries` lists
    the rows and places the menu at the `anchor` it was asked from: under it, or above it
    where there is no room below, kept inside the window. A tap outside the menu closes it
    and does nothing else (the press and its release are eaten), as does Escape; Back closes
    it through the window's `go_back`. A choice closes it and runs the entry.

    Its chrome is one surface: the theme's float tone, one rule-coloured border, the rows
    flat on it, the float hover tone under a finger or the pointer (`paint`)."""

    #: The widest a menu draws, in pixels; a phone's narrower window caps it first, and
    #: the rows elide within whichever is narrower.
    WIDEST = 420

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName("toad-menu")
        self.input_modality = platform_input()
        self._anchor = QRect()
        self._eating_release = False
        self._rows = QWidget()
        self._rows.setObjectName("toad-menu-rows")
        self._layout = QVBoxLayout(self._rows)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._scroll = QScrollArea(self)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._rows)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, UiGap.normal, 1, UiGap.normal)  # 1px: inside the border
        outer.setSpacing(0)
        outer.addWidget(self._scroll)
        self.hide()

    @classmethod
    def of(cls, widget: QWidget) -> QtMenu:
        """The pop-up menu of the window `widget` is in: the window's own direct child."""
        return QWidget.window(widget).findChild(cls, "toad-menu", Qt.FindChildOption.FindDirectChildrenOnly)

    @staticmethod
    def anchor_of(widget: QWidget) -> QRect:
        """`widget`'s rectangle in its window, as `show_entries` takes an anchor."""
        return QRect(widget.mapTo(QWidget.window(widget), widget.rect().topLeft()), widget.size())

    def paint(self, renderer: QtLineRenderer) -> None:
        """One surface in the renderer's theme: the float tone (a tier above what it floats
        over) and one rule-coloured border; rows flat on it, the float hover tone under a
        finger or the pointer; descriptions muted."""
        hover = renderer.theme(FloatHoverToneColour)
        modality = toad_platform.host.input_modality
        self.setStyleSheet(
            f"#toad-menu {{ background: {renderer.theme(FloatToneColour)};"
            f" border: 1px solid {renderer.theme(RuleColour)}; border-radius: 6px; }}"
            "#toad-menu QScrollArea, #toad-menu-rows { background: transparent; border: none; }"
            "#toad-menu QPushButton { background: transparent; border: none; border-radius: 0; padding: 0;"
            " text-align: left; }"
            + modality.hover_or_pressed("#toad-menu QPushButton", f"background: {hover};")
            + f"#toad-menu-description {{ color: {renderer.theme(MutedColour)}; }}")

    def show_entries(self, entries: Iterable[MenuEntry], anchor: QRect | None = None) -> None:
        """Replace the rows with ``entries`` and show the menu at ``anchor`` (a rectangle in
        the window's coordinates: the button or the pressed point that asked for it), or at
        the top of the window with none. A selection runs the entry's action and dismisses
        the menu."""
        delete_layout_widgets(self._layout)
        for entry in entries:
            self._layout.addWidget(QtMenuRow(entry, self, self._chose, parent=self._rows))
        self._anchor = anchor if anchor is not None else QRect()
        self.place()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)

    def show_panel(
        self,
        title: str,
        content: QWidget,
        *,
        back: Callable[[], None] | None = None,
        anchor: QRect | None = None,
    ) -> None:
        """Show a nested inline control panel inside this same floating menu surface (with an
        optional Back row returning to the parent menu)."""
        delete_layout_widgets(self._layout)
        if back is not None:
            back_entry = MenuEntry(label=f"← {title}", run=back, description="Back to menu")
            self._layout.addWidget(QtMenuRow(back_entry, self, lambda e: e.run(), parent=self._rows))
        content.setParent(self._rows)
        self._layout.addWidget(content)
        self._anchor = anchor if anchor is not None else QRect()
        self.place()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)

    def place(self) -> None:
        """Under the anchor (or above it, where there is more room there and too little
        below), inside the window by a frame gap, WIDEST wide or the window's width, as
        tall as its rows within the room it has; it scrolls only when they do not fit."""
        window = self.parentWidget()
        area = window.rect().adjusted(UiGap.frame, UiGap.frame, -UiGap.frame, -UiGap.frame)
        margins = self.layout().contentsMargins()
        width = min(area.width(), self.WIDEST)
        wanted = self._rows.sizeHint().height() + margins.top() + margins.bottom()
        anchor = self._anchor
        if not anchor.isValid():
            geometry = QRect(area.left() + (area.width() - width) // 2, area.top(), width, min(wanted, area.height()))
        else:
            below, above = area.bottom() - anchor.bottom(), anchor.top() - area.top()
            x = max(area.left(), min(anchor.left(), area.right() + 1 - width))
            if wanted <= below or below >= above:
                geometry = QRect(x, anchor.bottom() + 1, width, min(wanted, below))
            else:
                height = min(wanted, above)
                geometry = QRect(x, anchor.top() - height, width, height)
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff if geometry.height() >= wanted
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setGeometry(geometry)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt virtual method name
        kind = event.type()
        if watched is self.parentWidget() and kind == QEvent.Type.Resize and self.isVisible():
            self.place()
            return False
        if self._eating_release:
            if kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
                self._eating_release = False
                QApplication.instance().removeEventFilter(self)
                return True
            return kind == QEvent.Type.MouseMove
        if not self.isVisible():
            return False
        if kind == QEvent.Type.MouseButtonPress and not self.geometry().contains(
                self.parentWidget().mapFromGlobal(event.globalPosition().toPoint())):
            self._eating_release = True
            self.hide()
            return True
        if kind == QEvent.Type.ShortcutOverride and event.key() == Qt.Key.Key_Escape:
            # Escape is the open menu's: no shortcut bound to it (the composer's dismiss) runs,
            # and the key press that follows comes here and closes the menu.
            event.accept()
            return True
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.hide()
            return True
        return False

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        """Closed: the app stops passing its events here, unless the outside tap that
        closed it still has its release to eat."""
        if not self._eating_release:
            QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def _chose(self, entry: MenuEntry) -> None:
        self.hide()
        entry.run()
