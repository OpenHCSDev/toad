"""Qt sort control for a sidebar channel group.

Inherits `SortControlBase[ThreadSort]` so Qt and Textual read the current form
(order, label, tooltip) off the same owner. Textual's `ChannelSortChoice` lives
beside this as a parallel renderer (widgets/comms_sidebar.py); the shared base
`SortControlBase` guarantees both answer the same way to `update_order`,
`sort_label` and `sort_tooltip`.

Write path matches Textual's `CommsSortChoice.write_order`: build a
`CommsSortChannelTool(name, order)` and send through `observed.write_order`.
`QtChannelGroup.present` calls `update_order(channel.order)` each paint.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from agent_comms.display_order import ThreadSort
from agent_comms.transport.tools.sidebar import CommsSortChannelsTool as CommsSortChannelTool
from toad.client.sort_control import SortControlBase

if TYPE_CHECKING:
    from toad.qt.window import QtToadApp
    from toad.widgets.session_sort import ThreadSortForm


class QtChannelSortControl(SortControlBase[ThreadSort], QToolButton):
    """Per-channel sort button. The state (current form + label + tooltip) lives
    on the shared `SortControlBase`; this class renders it as a QToolButton with a
    QMenu and writes selections through the Core, mirroring
    `CommsSortChoice.write_order` in the Textual widget.
    """

    def __init__(
        self,
        app: "QtToadApp",
        form_type: "type[ThreadSortForm]",
        channel_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(form_type=form_type, scope=channel_name, parent=parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setAutoRaise(True)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._app = app
        self._channel_name = channel_name
        self._menu = QMenu(self)
        self.setMenu(self._menu)
        for order in ThreadSort.members_with(ThreadSort):
            action = QAction(order.title, self._menu)
            action.triggered.connect(partial(self._picked, order))
            self._menu.addAction(action)
        self.sort_changed()  # paint the "Sort ▾" placeholder

    def sort_changed(self) -> None:
        """Override of the base hook: repaint the button text + tooltip whenever
        `update_order` rebuilds the form."""
        self.setText(self.sort_label)
        self.setToolTip(self.sort_tooltip)

    def _picked(self, order: type[ThreadSort]) -> None:
        if order is self.order:
            return
        asyncio.ensure_future(self._write(order))

    async def _write(self, order: type[ThreadSort]) -> None:
        access = self._app.coordination_access
        observed = await access.preparation.run_thread(access.observation.observed)
        root = str(observed.root)
        request = CommsSortChannelTool(name=self._channel_name, order=order)
        await observed.write_order(access, root, request)
