"""Qt sibling of Textual's `SideBarCollapsible`: a collapsible panel that stacks a
header row (title + collapse chevron) over a body widget, driven by the one shared
`SidebarState.panels_collapsed` owner so both frontends agree on which panel is
open.

Textual's `SideBarCollapsible.watch_collapsed` writes
`navigation.set_panel_collapsed(str(self.title), collapsed)` at
`widgets/side_bar.py:280`. Qt's `QtSidebarPanelFrame._on_header_clicked` writes
`state.toggle_panel_collapsed(self._spec.title)` at the same owner. One writer
contract, two frontends — the state can never disagree about a panel's open-ness.

The panel takes a `PanelSpec` (title, flex, default-collapsed, id) and a body
`QWidget`. The spec's title doubles as the key under
`SidebarState.panels_collapsed`, matching Textual, so a channel/thread/project
panel keyed by the same title stays in sync between frontends.
"""

from __future__ import annotations

from pyqt_reactive.widgets.fitted_text import ElidedLine
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from toad.client.session_tracker import SidebarState
from toad.client.sidebar_panels import PanelSpec
from toad.qt.metrics import UiGap


class QtSidebarPanelFrame(QFrame):
    """A collapsible panel: header row + body container. The body visibility follows
    the shared `SidebarState.is_panel_collapsed(spec.title)` answer; a header tap
    toggles it through `set_panel_collapsed`. The frame itself holds no collapse
    state — one authority, which Textual's `SideBarCollapsible` also writes."""

    collapse_changed = Signal(bool)

    def __init__(self, spec: PanelSpec, body: QWidget, state: SidebarState,
                 parent: QWidget | None = None, *, header_control: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName("QtSidebarPanelFrame")
        self._spec = spec
        self._state = state
        self._body = body
        self._header = QWidget(self)
        self._header.setObjectName("QtSidebarPanelHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron = QToolButton(self._header)
        self._chevron.setAutoRaise(True)
        self._chevron.setArrowType(Qt.ArrowType.DownArrow)
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chevron.clicked.connect(self._toggle)
        # One text line square, as Textual's `▼` takes one cell: the title keeps the width.
        line = self.fontMetrics().lineSpacing()
        self._chevron.setFixedSize(line, line)
        self._chevron.setStyleSheet("QToolButton { padding: 0px; border: none; }")
        # The title elides before the header's control, as every sidebar text does.
        self._title = ElidedLine(spec.title)
        self._title.setParent(self._header)
        self._title.setObjectName("QtSidebarPanelTitle")
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_row = QHBoxLayout(self._header)
        # `▼ Channels  Name ▾` as Textual's header row runs it: no inset, the chevron against
        # the title, one gap before the control.
        header_row.setContentsMargins(0, UiGap.tight, 0, UiGap.tight)
        header_row.setSpacing(0)
        header_row.addWidget(self._chevron)
        header_row.addWidget(self._title, 1)
        header_row.addSpacing(UiGap.tight)
        # The control Textual's panel declares beside its title (`SideBar.Panel.header_control`),
        # such as the Channels panel's channel order.
        if header_control is not None:
            header_control.setParent(self._header)
            header_row.addWidget(header_control)
        self._body.setParent(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header)
        outer.addWidget(self._body, 1 if spec.flex else 0)
        self._header.mousePressEvent = self._header_press  # type: ignore[method-assign]
        self._present_collapse()

    @property
    def spec(self) -> PanelSpec:
        return self._spec

    @property
    def body(self) -> QWidget:
        return self._body

    def is_collapsed(self) -> bool:
        return self._state.is_panel_collapsed(self._spec.title, self._spec.collapsed)

    def present(self) -> None:
        """Re-read the shared collapse state; call after an external write (e.g. a
        Textual tab wrote through the same owner) so the Qt panel reflects it."""
        self._present_collapse()

    def _header_press(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._toggle()
        else:
            event.ignore()

    def _toggle(self) -> None:
        new_value = self._state.toggle_panel_collapsed(self._spec.title, self._spec.collapsed)
        self._present_collapse()
        self.collapse_changed.emit(new_value)

    def _present_collapse(self) -> None:
        collapsed = self.is_collapsed()
        self._body.setVisible(not collapsed)
        self._chevron.setArrowType(
            Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow
        )
