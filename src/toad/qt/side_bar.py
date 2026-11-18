"""Qt's sidebar surfaces and the chrome that places them, over the shared sidebar owners.

Each class here inherits the toolkit-neutral owner its Textual sibling inherits, so the two
frontends cannot draw a sidebar differently at the same viewport:

- ``QtWorkspaceChrome`` ↔ ``WorkspaceChrome``: ``SidebarChromeArrangement`` resolves where the
  conversation and every presented sidebar go through the one ``SidebarLayout``.
- ``QtSideBar`` ↔ ``SideBar``: ``SidebarSurface`` owns the placement role, the extent and
  placement-action writes, and where the toggle strip, resize handle and content sit.
- ``QtSideBarToggle`` ↔ ``SideBarToggle``: ``SidebarToggleFace`` draws the edge's toggle text.
- ``QtSidebarSlider`` ↔ ``SidebarSlider``: ``SidebarExtentTrack`` owns the "40% ──●──" track.
- ``QtSidebarAction`` ↔ ``SidebarAction``: ``PlacementControl`` is what the placement-action
  family presents.

Geometry is resolved in cells, as Textual resolves it; the chrome maps a cell to the window
font's character box so a phone and a desktop window split the same way a terminal of the
same column count does.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QGridLayout, QLabel, QToolButton, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from textual.geometry import Offset, Region, Size

from toad.sidebar_layout import (
    PlacementControl,
    SidebarChromeArrangement,
    SidebarExtentTrack,
    SidebarLayout,
    SidebarPlacementAction,
    SidebarResizeGrip,
    SidebarSurface,
    SidebarToggleFace,
)
from toad.sidebar_placement import SidebarPlacement

if TYPE_CHECKING:
    from toad.client.application import ClientApplication


def cells_to_pixels(region: Region, cells: Size, pixels: QRect) -> QRect:
    """``region`` (in a ``cells``-sized grid) as a rectangle of ``pixels``: each cell edge maps
    proportionally, so the regions tile the pixel rectangle with no remainder strip."""
    def x(column: int) -> int:
        return pixels.x() + column * pixels.width() // max(1, cells.width)

    def y(row: int) -> int:
        return pixels.y() + row * pixels.height() // max(1, cells.height)

    left, top = x(region.x), y(region.y)
    return QRect(left, top, x(region.right) - left, y(region.bottom) - top)


class QtSidebarAction(PlacementControl, QToolButton, metaclass=PyQtWidgetMeta):
    """One arrow or Float/Push as a Qt button; the placement-action family presents it."""

    def __init__(self, action: SidebarPlacementAction, surface: QtSideBar) -> None:
        super().__init__(surface)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.action = action
        self.setText(action.label)
        self.setAutoRaise(True)
        self.clicked.connect(lambda: surface.apply_placement_action(action))

    def set_shown(self, shown: bool) -> None:
        self.setVisible(shown)

    def set_label(self, label: str) -> None:
        self.setText(label)

    def set_tooltip(self, tooltip: str) -> None:
        self.setToolTip(tooltip)


class QtSidebarSlider(SidebarExtentTrack, QLabel, metaclass=PyQtWidgetMeta):
    """The extent slider: the shared track drawn in the label's width of track cells; a press
    or drag picks the value under the pointer."""

    def __init__(self, surface: QtSideBar) -> None:
        super().__init__(surface)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._surface = surface
        self.start_track(SidebarLayout.minimum_percent, SidebarLayout.maximum_percent,
                         SidebarLayout.minimum_percent)
        self.setToolTip(self.track_tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _cell(self) -> int:
        return max(1, self.fontMetrics().horizontalAdvance("─"))

    def _cells(self) -> int:
        return max(1, self.contentsRect().width() // self._cell())

    def set_range(self, minimum: int, maximum: int, value: int) -> None:
        super().set_range(minimum, maximum, value)
        self.draw()

    def draw(self) -> None:
        """The widest track whose text fits the label: the percentage's digits are wider
        than the track's cells in a proportional font, so the fit is measured, not assumed."""
        width = self.contentsRect().width()
        cells = self._cells()
        text = self.track_text(cells)
        while cells > 1 and self.fontMetrics().horizontalAdvance(text) > width:
            cells -= 1
            text = self.track_text(cells)
        self.setText(text)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.draw()

    def _pick(self, event) -> None:
        value = self.value_at(int(event.position().x()) // self._cell(), self._cells(), self.reversed)
        if value != self.value:
            self.value = value
            self.draw()
            self._surface.resize_to(value)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._pick(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
            self._pick(event)


class QtSideBarToggle(SidebarToggleFace, QLabel, metaclass=PyQtWidgetMeta):
    """The toggle strip on the conversation-facing side: the edge's arrows around the
    heading, exactly the text the Textual strip shows. A press shows or hides the pane."""

    def __init__(self, surface: QtSideBar) -> None:
        super().__init__(surface)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName("SidebarToggle")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._surface = surface

    def show_toggle(self, text: str, tooltip: str) -> None:
        self.setText(text)
        self.setToolTip(tooltip)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._surface.toggle_pane()


class QtSidebarResizeHandle(SidebarResizeGrip, QWidget, metaclass=PyQtWidgetMeta):
    """The line between the content and the toggle strip, as Textual's
    `SidebarResizeHandle`: a drag resizes through the shared `SidebarResizeGrip`; a press
    without a drag shows or hides the slider and placement controls."""

    def __init__(self, surface: QtSideBar) -> None:
        super().__init__(surface)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setToolTip(self.grip_tooltip)
        self._surface = surface
        self._start: QPoint | None = None
        self._dragged = False

    @property
    def grip_surface(self) -> QtSideBar:
        return self._surface

    def grip_viewport_extent(self) -> int:
        chrome = self._surface.parentWidget()
        return self._surface.placement.side.extent(Size(chrome.width(), chrome.height()))

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """The handle's line, as the edge's ``handle_text`` draws it in a terminal: one
        unbroken stroke down a column handle or across a row handle."""
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Mid))
        middle = self.rect().center()
        if self.height() >= self.width():
            painter.drawLine(middle.x(), 0, middle.x(), self.height())
        else:
            painter.drawLine(0, middle.y(), self.width(), middle.y())

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._start = event.globalPosition().toPoint()
            self._dragged = False
            self.begin_grip()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._start is None:
            return
        event.accept()
        moved = event.globalPosition().toPoint() - self._start
        self._dragged = self._dragged or moved.manhattanLength() > 4
        if self._dragged:
            self.drag_grip(Offset(moved.x(), moved.y()))

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._start is not None and not self._dragged:
            self.grip_clicked()
        self._start = None


class QtSideBar(SidebarSurface, QWidget, metaclass=PyQtWidgetMeta):
    """One sidebar role's surface: its content over the extent slider and placement actions,
    the resize handle and the toggle strip, each where ``SidebarSurface.surface_parts`` puts
    it for the placement's edge. Folded, only the strip shows."""

    def __init__(self, layout: SidebarLayout, identity: type[SidebarPlacement], content: QWidget, *,
                 heading: Callable[[], str], toggled: Callable[[], None],
                 laid_out: Callable[[], None], client: ClientApplication, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        # `#SidebarPane` is the hook the scheme's sidebar-pane style selects.
        self.setObjectName("SidebarPane")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._layout = layout
        self._identity = identity
        self._heading = heading
        self._toggled = toggled
        self._laid_out = laid_out
        self._client = client
        self.content = content
        self.content_stack = QWidget(self)
        self.controls = QWidget(self.content_stack)
        self.slider = QtSidebarSlider(self)
        self.slider.setParent(self.controls)
        self._actions = [QtSidebarAction(action, self) for action in self.placement_actions()]
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(0)
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(0)
        controls.addWidget(self.slider)
        controls.addLayout(self._grid)
        stack = QVBoxLayout(self.content_stack)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        content.setParent(self.content_stack)
        stack.addWidget(content, 1)
        stack.addWidget(self.controls)
        self.handle = QtSidebarResizeHandle(self)
        self.toggle = QtSideBarToggle(self)
        self._cells = Size(1, 1)

    @property
    def placement_identity(self) -> type[SidebarPlacement]:
        return self._identity

    @property
    def collapsed(self) -> bool:
        return self._layout.is_collapsed(self._identity)

    @property
    def sidebar_layout(self) -> SidebarLayout:
        return self._layout

    @property
    def client(self) -> ClientApplication:
        return self._client

    def lay_out(self) -> None:
        self._laid_out()

    def toggle_pane(self) -> None:
        self._toggled()

    def toggle_controls(self) -> None:
        self.controls.setVisible(self.controls.isHidden())

    def present(self) -> None:
        """Draw the strip, the slider and the placement actions from the one layout."""
        self.toggle.present_toggle(self.collapsed, self.placement.side, self._heading())
        self.present_extent_track(self.slider)
        self.present_placement_controls(iter(self._actions), self._layout, self._identity)
        # Two actions to a row, as SidebarLayoutActions grids them; an action the layout
        # hides leaves no gap.
        while self._grid.count():
            self._grid.takeAt(0)
        shown = [action for action in self._actions if not action.isHidden()]
        for index, action in enumerate(shown):
            self._grid.addWidget(action, index // 2, index % 2)
        folded = self.collapsed
        self.content_stack.setVisible(not folded)
        self.handle.setVisible(not folded)

    def place(self, rect: QRect, cells: Size) -> None:
        """Take ``rect`` (``cells`` in the chrome's grid) and lay the parts inside it."""
        self.setGeometry(rect)
        self._cells = cells
        local = QRect(0, 0, rect.width(), rect.height())
        parts = self.surface_parts(self.placement.side, cells)
        self.toggle.setGeometry(cells_to_pixels(parts.toggle, cells, local))
        self.handle.setGeometry(cells_to_pixels(parts.handle, cells, local))
        self.content_stack.setGeometry(cells_to_pixels(parts.content, cells, local))


class QtWorkspaceChrome(SidebarChromeArrangement[QtSideBar], QWidget, metaclass=PyQtWidgetMeta):
    """The conversation pages and the sidebars, placed where the shared arrangement resolves
    them for this widget's size in cells: a pushing sidebar narrows the pages by its gutter, a
    floating one lies over them, a folded one is its strip."""

    def __init__(self, layout: SidebarLayout, pages: QWidget, *,
                 available: Callable[[type[SidebarPlacement]], bool], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._layout = layout
        self._available = available
        self.pages = pages
        pages.setParent(self)
        self.sidebars: tuple[QtSideBar, ...] = ()

    @property
    def sidebar_layout(self) -> SidebarLayout:
        return self._layout

    def presented_sidebars(self) -> tuple[QtSideBar, ...]:
        return tuple(bar for bar in self.sidebars if self._available(bar.placement_identity))

    def cells(self) -> Size:
        """This widget's size in the window font's character cells: a cell is the font's
        average character across and one line down, so a row of text fits as many
        characters as a terminal row of that many cells does."""
        metrics = self.fontMetrics()
        return Size(max(1, self.width() // max(1, metrics.averageCharWidth())),
                    max(1, self.height() // max(1, metrics.lineSpacing())))

    def arrange(self) -> None:
        cells = self.cells()
        pixels = self.rect()
        arranged = self.arrange_chrome(cells)
        self.pages.setGeometry(cells_to_pixels(arranged.content, cells, pixels))
        order = {identity: index for index, identity in enumerate(self._layout.ordered())}
        for bar in sorted(self.sidebars, key=lambda bar: order[bar.placement_identity]):
            region = arranged.bars.get(bar)
            if region is None:
                bar.hide()
                continue
            bar.place(cells_to_pixels(region, cells, pixels), region.size)
            bar.show()
            bar.raise_()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.arrange()
