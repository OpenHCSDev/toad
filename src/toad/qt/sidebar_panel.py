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

from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial

from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from toad.client.session_tracker import SidebarState
from toad.client.sidebar_filter import SidebarFilter, SidebarSearchField
from toad.client.sidebar_panels import PanelMenuModel, PanelSpec, SidebarPanelCollapse, SidebarPanelColumn
from toad.qt.metrics import UiGap


class QtSidebarPanelFrame(SidebarPanelCollapse, QFrame, metaclass=PyQtWidgetMeta):
    """A collapsible panel: header row + body container. The body visibility follows
    the shared `SidebarState.is_panel_collapsed(spec.title)` answer; a header tap
    toggles it through `set_panel_collapsed`. The frame itself holds no collapse
    state — one authority, which Textual's `SideBarCollapsible` also writes."""

    collapse_changed = Signal(bool)

    def __init__(self, spec: PanelSpec, body: QWidget, state: SidebarState, collapsed: bool,
                 parent: QWidget | None = None, *, header_controls: tuple[QWidget, ...] = ()) -> None:
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
        # The controls Textual's panel declares beside its title (`SideBar.Panel.header_control`),
        # such as the Channels panel's channel order or the Comms panel's relationship order.
        for control in header_controls:
            control.setParent(self._header)
            header_row.addWidget(control)
        self._body.setParent(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header)
        outer.addWidget(self._body, 1 if spec.flex else 0)
        self._header.mousePressEvent = self._header_press  # type: ignore[method-assign]
        self._show_collapsed(collapsed)

    @property
    def spec(self) -> PanelSpec:
        return self._spec

    @property
    def body(self) -> QWidget:
        return self._body

    @property
    def panel_title(self) -> str:
        return self._spec.title

    @property
    def panel_state(self) -> SidebarState:
        return self._state

    def is_collapsed(self) -> bool:
        return self.stored_collapsed(self._spec.collapsed)

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
        new_value = not self.is_collapsed()
        self.record_collapsed(new_value)
        self._present_collapse()
        self.collapse_changed.emit(new_value)

    def _present_collapse(self) -> None:
        self._show_collapsed(self.is_collapsed())

    def _show_collapsed(self, collapsed: bool) -> None:
        self._body.setVisible(not collapsed)
        self._chevron.setArrowType(
            Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow
        )


class QtSidebarSearch(SidebarSearchField, QLineEdit, metaclass=PyQtWidgetMeta):
    """The sidebar's search input, as Textual's `SidebarSearch`: its text is the sidebar's
    `SidebarFilter` text, and Escape clears it."""

    def __init__(self, search: SidebarFilter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setPlaceholderText(self.search_placeholder)
        self.setText(search.text)
        self.textChanged.connect(lambda text: setattr(search, "text", text))

    def show_search(self, text: str) -> None:
        self.setText(text)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape and self.text():
            event.accept()
            self.clear_search()
            return
        super().keyPressEvent(event)


class QtSidebarShell(QWidget):
    """A sidebar's content, as Textual's `SideBar._compose_shell`: the search input over the
    sidebar's panels. The search writes the sidebar's `SidebarFilter`, which its panels match
    rows against. The channels sidebar's panels are a column of collapsibles
    (`QtSidebarPanels`); the thread sidebar's are one picked at a time (`QtPanelMenu`), as
    Textual's `ThreadSidebar` composes a `PanelMenu`."""

    def __init__(self, search: SidebarFilter, body: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.search = search
        self.search_input = QtSidebarSearch(search, self)
        self.body = body
        body.setParent(self)
        layout = QVBoxLayout(self)
        # No inset: Textual's sidebar content runs to the strip, and a narrow sidebar
        # needs every column for its names.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(UiGap.normal)
        layout.addWidget(self.search_input)
        layout.addWidget(body, 1)


class QtSidebarPanels(SidebarPanelColumn["QtPanelEntry"], QScrollArea, metaclass=PyQtWidgetMeta):
    """A scrolling column of collapsible panels, as Textual's `SidebarViewport` of
    `SideBarCollapsible`s, composed by the shared `SidebarPanelColumn`; each panel's open
    state is the sidebar's `SidebarState`."""

    def __init__(self, state: SidebarState, entries: Iterable[QtPanelEntry],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        column = QWidget(self)
        column.setWindowFlags(Qt.WindowType.Widget)
        self._column = QVBoxLayout(column)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(0)
        self._state, self._holder = state, column
        self.panels: tuple[QtSidebarPanelFrame, ...] = self.panel_frames(entries, state)
        for frame in self.panels:
            self._column.addWidget(frame, self._panel_stretch(frame))
            frame.collapse_changed.connect(partial(self._restretch_panel, frame))
        # A column with no open flex panel keeps its panels at the top.
        self._column.addStretch(0)
        self.setWidget(column)
        self._restretch_tail()

    def entry_panel(self, entry: QtPanelEntry) -> PanelSpec:
        return entry.spec

    def panel_frame(self, entry: QtPanelEntry, collapsed: bool) -> QtSidebarPanelFrame:
        return QtSidebarPanelFrame(entry.spec, entry.widget, self._state, collapsed, self._holder,
                                   header_controls=entry.controls)

    def _panel_stretch(self, panel: QtSidebarPanelFrame) -> int:
        """An open flex panel owns a stretch slot (`claims_room`); collapsed, it is its
        header row, as Textual's `FlexSideBarCollapsible` is."""
        return int(self.claims_room(panel.spec, panel.is_collapsed()))

    def _restretch_panel(self, panel: QtSidebarPanelFrame, _collapsed: bool) -> None:
        self._column.setStretch(self._column.indexOf(panel), self._panel_stretch(panel))
        self._restretch_tail()

    def _restretch_tail(self) -> None:
        """The trailing stretch takes the room no open flex panel claims."""
        claimed = any(self._panel_stretch(panel) for panel in self.panels)
        self._column.setStretch(self._column.count() - 1, 0 if claimed else 1)


@dataclass(frozen=True, eq=False)
class QtPanelEntry:
    """One entry of a `QtPanelMenu`: its panel spec, the widget the page shows, the controls
    the page sets above it (Textual's `SideBar.Panel.header_control`), and what names it."""

    spec: PanelSpec
    widget: QWidget
    controls: tuple[QWidget, ...]
    identity: object


class QtPanelMenu(PanelMenuModel[QtPanelEntry], QWidget, metaclass=PyQtWidgetMeta):
    """The thread sidebar's panels, one shown at a time and picked from a compact list, as
    Textual's `PanelMenu`: the entries are the viewed object's, the pick opens on the entry
    the sidebar's `SidebarState` remembers, and each page holds its controls over its panel."""

    def __init__(self, navigation: SidebarState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.navigation = navigation
        self.entries = ()
        self.picker = QComboBox(self)
        self.picker.currentIndexChanged.connect(self._picked)
        self.pages = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.picker)
        layout.addWidget(self.pages, 1)

    def entry_identity(self, entry: QtPanelEntry) -> object:
        return entry.identity

    def show_entries(self, entries: tuple[QtPanelEntry, ...]) -> None:
        """List these entries and open the remembered one. A page is the entry's controls
        over its widget; widgets of entries listed again keep their state."""
        self.picker.blockSignals(True)
        self.picker.clear()
        for entry in self.entries:
            for widget in (entry.widget, *entry.controls):
                widget.hide()
                widget.setParent(self)
        while self.pages.count():
            page = self.pages.widget(0)
            self.pages.removeWidget(page)
            page.deleteLater()
        self.entries = entries
        for entry in entries:
            self.picker.addItem(entry.spec.title)
            self.pages.addWidget(self._page(entry))
        self.picker.setCurrentIndex(entries.index(self.initial_entry()))
        self.pages.setCurrentIndex(self.picker.currentIndex())
        self.picker.blockSignals(False)

    def _page(self, entry: QtPanelEntry) -> QWidget:
        page = QWidget(self.pages)
        page.setWindowFlags(Qt.WindowType.Widget)
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        if entry.controls:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addStretch(1)
            for control in entry.controls:
                control.setParent(page)
                row.addWidget(control)
                control.show()
            column.addLayout(row)
        entry.widget.setParent(page)
        column.addWidget(entry.widget, 1)
        entry.widget.show()
        return page

    def _picked(self, index: int) -> None:
        entry = self.entries[index]
        self.pages.setCurrentIndex(index)
        self.remember_entry(entry)
