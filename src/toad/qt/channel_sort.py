"""Qt sort controls for the Channels sidebar: the panel header's channel order and each
channel's member order.

Both inherit `SortControlBase` (the current form, label and tooltip) and `CommsSortWrite`
(the request each order is stored by, written through the observed Core) — the same two
owners Textual's `ChannelListSort` and `ChannelSortChoice` inherit — so the two frontends
label and write an order identically. This module adds only the QToolButton and its menu.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolButton, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta

from agent_comms.display_order import ChannelSort, DisplayOrder, ThreadSort
from toad.client.sort_control import ChannelListOrder, ChannelMemberOrder, CommsSortWrite, SortControlBase
from toad.widgets.session_sort import ChannelSortForm, ThreadSortForm

if TYPE_CHECKING:
    from toad.qt.window import QtToadApp


class QtSortControl[Order: DisplayOrder](CommsSortWrite[Order], SortControlBase[Order], QToolButton,
                                         metaclass=PyQtWidgetMeta):
    """A sort choice as a button whose menu lists its form's orders; a pick writes the
    order through the Core, and only the observation that follows repaints the label."""

    def __init__(self, app: QtToadApp, form_type, scope: str, parent: QWidget | None = None) -> None:
        super().__init__(form_type=form_type, scope=scope, parent=parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setAutoRaise(True)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # The label already ends in the shared "▾"; Qt's own menu arrow would draw a second.
        # The plate keeps the label legible where it lies over a long line's text.
        scheme = app.theme.color_scheme
        self.setStyleSheet(f"QToolButton {{ background-color: {scheme.to_hex(scheme.panel_bg)};"
                           " padding: 0px; border: none; }"
                           "QToolButton::menu-indicator { image: none; width: 0px; }")
        # One text line tall, as Textual's one-row segment: the summary line below stays clear.
        self.setFixedHeight(self.fontMetrics().lineSpacing())
        self._app = app
        self._form_type = form_type
        menu = QMenu(self)
        menu.aboutToShow.connect(self._fill)
        self.setMenu(menu)
        self._fill()
        self.sort_changed()

    def visibility_fields(self):
        """Settings the menu toggles beside the orders, as Textual's `SortChoice` lists them."""
        return ()

    def _fill(self) -> None:
        """The orders, then each visibility setting marked with its current value."""
        menu = self.menu()
        menu.clear()
        choices = self._form_type.choices
        for order in choices.choices():
            action = QAction(choices.label(order), menu)
            action.triggered.connect(partial(self._picked, order))
            menu.addAction(action)
        settings = self._app.saved_settings
        for path in self.visibility_fields():
            field = path.bind(settings.state)
            action = QAction(f"{'✓' if field.value else '○'} {field.label}", menu)
            action.triggered.connect(partial(self._toggle_visibility, path))
            menu.addAction(action)

    def _toggle_visibility(self, path) -> None:
        settings = self._app.saved_settings
        settings.toggle(path)
        asyncio.ensure_future(settings.save())

    def sort_changed(self) -> None:
        self.setText(self.sort_label)
        self.setToolTip(self.sort_tooltip)

    def _picked(self, order: type[Order]) -> None:
        if order is not self.order:
            asyncio.ensure_future(self._write(order))

    async def _write(self, order: type[Order]) -> None:
        access = self._app.coordination_access
        observed = await access.preparation.run_thread(access.observation.observed)
        await self.write_order(observed, access, str(observed.root), order)


class QtChannelListSort(ChannelListOrder, QtSortControl[ChannelSort]):
    """The Channels panel header's channel order, as Textual's `ChannelListSort`."""

    def __init__(self, app: QtToadApp, parent: QWidget | None = None) -> None:
        super().__init__(app, ChannelSortForm, "channels", parent)


class QtChannelSortControl(ChannelMemberOrder, QtSortControl[ThreadSort]):
    """One channel's member order, as Textual's `ChannelSortChoice`."""

    def __init__(self, app: QtToadApp, channel_name: str, parent: QWidget | None = None) -> None:
        super().__init__(app, ThreadSortForm, channel_name, parent)
