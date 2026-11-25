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

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QGridLayout, QLabel, QStyle, QStyleOption, QToolButton, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from textual.geometry import Offset, Region, Size
from toad.client.application import ClientApplication
from ui_theme.clock import AnimationClock
from ui_theme.effects import SIDEBAR_ENTER, SIDEBAR_EXIT

from toad.motion import TransitionTarget
from toad.qt.metrics import drain_layout_items
from toad.pointer_gesture import NO_GESTURE, Gesture, GestureControl, PressedGesture
from toad.sidebar_layout import (
    PlacedSidebar,
    PlacementControl,
    SidebarChromeArrangement,
    SidebarExtentTrack,
    SidebarFoldGrip,
    SidebarLayout,
    SidebarPlacementAction,
    SidebarResizeGrip,
    SidebarSurface,
    SidebarToggleFace,
    StoredSidebarLayout,
)
from toad.sidebar_placement import SidebarPlacement

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
        self.start_track(self.floor, SidebarLayout.maximum_percent, SidebarLayout.minimum_percent)
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
            self.track_moved(self._surface, value)
            self.draw()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.begin_track(self._surface)
            self._pick(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
            self._pick(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.track_released(self._surface)


class QtGripPointer(GestureControl):
    """A Qt grip's press, drag and release, for the resize handle and the toggle strip alike,
    through the shared gesture states: a press that travels more than a few pixels is a drag
    through the shared grip, a release before that is the grip's click."""

    drag_threshold = 4

    def __init__(self, surface: QtSideBar) -> None:
        super().__init__(surface)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._surface = surface
        self._gesture: Gesture = NO_GESTURE

    @property
    def grip_surface(self) -> QtSideBar:
        return self._surface

    def grip_viewport_extent(self) -> int:
        chrome = self._surface.parentWidget()
        return self._surface.placement.side.extent(Size(chrome.width(), chrome.height()))

    @staticmethod
    def _position(event) -> Offset:
        point = event.globalPosition().toPoint()
        return Offset(point.x(), point.y())

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            origin = self._position(event)
            self._gesture = PressedGesture(origin)
            self.begin_grip(origin)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._gesture.holds_pointer:
            event.accept()
            self._gesture = self._gesture.moved(self, self._position(event))

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._gesture.holds_pointer:
            event.accept()
            self._gesture = self._gesture.released(self, self._position(event))


class QtSideBarToggle(QtGripPointer, SidebarToggleFace, SidebarFoldGrip, QLabel, metaclass=PyQtWidgetMeta):
    """The toggle strip on the conversation-facing side, as Textual's `SideBarToggle`: the
    edge's arrows around the heading. A click shows or hides the pane; a drag resizes it
    exactly as the resize handle does. A column strip draws its heading turned to read along
    the strip, where a terminal can only stack the letters one per row."""

    def __init__(self, surface: QtSideBar) -> None:
        super().__init__(surface)
        self.setObjectName("SidebarToggle")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._symbol = self._heading = ""
        self._trailing_splitter = False

    def set_trailing_splitter(self, shown: bool) -> None:
        if self._trailing_splitter != shown:
            self._trailing_splitter = shown
            self.update()

    def show_toggle(self, text: str, tooltip: str) -> None:
        self.setText(text)
        self.setToolTip(f"{tooltip} · drag to resize")

    def show_turned(self, symbol: str, heading: str) -> None:
        """What a column strip draws: the edge's arrow upright at each end, the heading turned
        to read along the strip between them."""
        self._symbol, self._heading = symbol, heading
        self.update()

    def _draw_trailing_splitter(self, painter: QPainter) -> None:
        if not self._trailing_splitter:
            return
        painter.save()
        painter.setPen(self.palette().color(QPalette.ColorRole.Mid))
        x = self.width() - 1
        painter.drawLine(x, 0, x, self.height())
        painter.restore()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if self.height() <= self.width():
            super().paintEvent(event)
            if self._trailing_splitter:
                painter = QPainter(self)
                self._draw_trailing_splitter(painter)
            return
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        metrics = self.fontMetrics()
        line = metrics.lineSpacing()
        shown = metrics.elidedText(self._heading, Qt.TextElideMode.ElideRight, max(0, self.height() - 4 * line))
        reach = metrics.horizontalAdvance(shown) // 2 + line
        middle = self.height() // 2
        for top in (middle - reach - line, middle + reach):
            painter.drawText(QRect(0, top, self.width(), line), Qt.AlignmentFlag.AlignCenter, self._symbol)
        painter.save()
        painter.translate(self.width() / 2, middle)
        painter.rotate(90 if self._surface.placement.side.sign < 0 else -90)
        span = QRect(-reach, -self.width() // 2, 2 * reach, self.width())
        painter.drawText(span, Qt.AlignmentFlag.AlignCenter, shown)
        painter.restore()
        self._draw_trailing_splitter(painter)


class QtSidebarResizeHandle(QtGripPointer, SidebarResizeGrip, QWidget, metaclass=PyQtWidgetMeta):
    """The line between the content and the toggle strip, as Textual's
    `SidebarResizeHandle`: a drag resizes through the shared `SidebarResizeGrip` (released at
    the wall it folds the pane); a press without a drag shows or hides the slider and
    placement controls."""

    def __init__(self, surface: QtSideBar) -> None:
        super().__init__(surface)
        self.setToolTip(self.grip_tooltip)

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


class QtSideBar(StoredSidebarLayout, SidebarSurface, QWidget, metaclass=PyQtWidgetMeta):
    """One sidebar role's surface: its content over the extent slider and placement actions,
    the resize handle and the toggle strip, each where ``SidebarSurface.surface_parts`` puts
    it for the placement's edge. Folded, only the strip shows."""

    def __init__(self, layout: SidebarLayout, identity: type[SidebarPlacement], content: QWidget, *,
                 heading: Callable[[], str], laid_out: Callable[[], None],
                 client: ClientApplication, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        # `#SidebarPane` is the hook the scheme's sidebar-pane style selects.
        self.setObjectName("SidebarPane")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._layout = layout
        self._identity = identity
        self._heading = heading
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
    def client(self) -> ClientApplication:
        return self._client

    def lay_out(self) -> None:
        self._laid_out()

    def fold(self, collapsed: bool) -> None:
        if self._layout.set_collapsed(self._identity, collapsed):
            self.lay_out()

    def show_controls(self, shown: bool) -> None:
        self.controls.setVisible(shown)

    def present(self) -> None:
        """Draw the strip, the slider and the placement actions from the one layout."""
        self.toggle.present_toggle(self.collapsed, self.placement.side, self._heading())
        self.toggle.show_turned(self.placement.side.toggle_symbol(self.collapsed), self._heading())
        self.present_extent_track(self.slider)
        self.present_placement_controls(iter(self._actions), self._layout, self._identity)
        # Two actions to a row, as SidebarLayoutActions grids them; an action the layout
        # hides leaves no gap.
        drain_layout_items(self._grid)
        shown = [action for action in self._actions if not action.isHidden()]
        for index, action in enumerate(shown):
            self._grid.addWidget(action, index // 2, index % 2)
        folded = self.collapsed
        self.content_stack.setVisible(not folded)
        # Holding the window alone there is nothing beside the bar to fold it for or to
        # grip: only its content shows.
        alone = self.holds_alone
        self.toggle.setVisible(not alone)
        self.handle.setVisible(not folded and not alone)
        self.controls.setVisible(self.controls_wanted and not alone)

    def place(self, rect: QRect, cells: Size) -> None:
        """Take ``rect`` (``cells`` in the chrome's grid) and lay the parts inside it."""
        self.setGeometry(rect)
        self._cells = cells
        local = QRect(0, 0, rect.width(), rect.height())
        parts = self.surface_parts(cells)
        self.toggle.setGeometry(cells_to_pixels(parts.toggle, cells, local))
        self.handle.setGeometry(cells_to_pixels(parts.handle, cells, local))
        self.content_stack.setGeometry(self._held_content(cells_to_pixels(parts.content, cells, local)))

    def _held_content(self, content: QRect) -> QRect:
        """While a grip holds an extent the content keeps its length along the drag, against
        the wall: the bar's edge moves, and its rows are fitted to the new width once, when the
        hold ends, as the conversation's are."""
        held = self.content_stack.geometry()
        if not self._layout.holding or held.isEmpty() or self.collapsed:
            return content
        side = self.placement.side
        if side.coordinate(Offset(1, 0)) != 0:
            left = content.left() if side.sign > 0 else content.right() + 1 - held.width()
            return QRect(left, content.top(), held.width(), content.height())
        top = content.top() if side.sign > 0 else content.bottom() + 1 - held.height()
        return QRect(content.left(), top, content.width(), held.height())


class PaneSlide(TransitionTarget):
    """One sidebar sliding open or folded on the shared clock, as ui_theme's
    ``SIDEBAR_ENTER`` / ``SIDEBAR_EXIT`` ease it. The pane keeps its open size and only moves,
    so nothing inside it lays out again per frame: opening, it slides out from behind its strip
    over the pages, which narrow once it has arrived; folding, the pages widen at once and the
    pane slides back under its strip."""

    def __init__(self, chrome: QtWorkspaceChrome, bar: QtSideBar, opened: PlacedSidebar,
                 folded: PlacedSidebar, *, opening: bool, pages: QRect) -> None:
        self.chrome, self.bar = chrome, bar
        self.opening, self.pages = opening, pages
        self.target = opened if opening else folded
        self.opened = chrome.pixels(opened)
        travel = 2 * (chrome.pixels(folded).center() - self.opened.center())
        horizontal = bar.placement.side.coordinate(Offset(1, 0)) != 0
        self.away = QPoint(travel.x(), 0) if horizontal else QPoint(0, travel.y())
        bar.content_stack.setVisible(True)
        bar.place(self.opened, opened.region.size)
        self.apply_amount(0.0 if opening else 1.0)
        self.start_transition(chrome.clock, SIDEBAR_ENTER if opening else SIDEBAR_EXIT)

    @property
    def animation_visible(self) -> bool:
        return self.chrome.isVisible()

    def apply_amount(self, amount: float) -> None:
        """``amount`` is how much of the pane shows: 1 open, 0 behind its strip."""
        self.bar.move(self.opened.topLeft() + self.away * (1 - amount))

    def land(self) -> None:
        """Land where the arrangement put the bar, and let the pages take their place."""
        self.chrome.slides.pop(self.bar, None)
        self.bar.present()
        self.bar.place(self.chrome.pixels(self.target), self.target.region.size)
        if self.opening:
            self.chrome.pages.setGeometry(self.pages)


class QtWorkspaceChrome(StoredSidebarLayout, SidebarChromeArrangement[QtSideBar], QWidget, metaclass=PyQtWidgetMeta):
    """The conversation pages and the sidebars, placed where the shared arrangement resolves
    them for this widget's size in cells: a pushing sidebar narrows the pages by its gutter, a
    floating one lies over them, a folded one is its strip. A bar that folds or opens slides
    there on the shared animation clock."""

    def __init__(self, layout: SidebarLayout, pages: QWidget, *, clock: AnimationClock,
                 available: Callable[[type[SidebarPlacement]], bool], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._layout = layout
        self._available = available
        self.clock = clock
        self.pages = pages
        pages.setParent(self)
        self.sidebars: tuple[QtSideBar, ...] = ()
        self.placed: dict[QtSideBar, PlacedSidebar] = {}
        self.slides: dict[QtSideBar, PaneSlide] = {}

    def presented_sidebars(self) -> tuple[QtSideBar, ...]:
        return tuple(bar for bar in self.sidebars if self._available(bar.placement_identity))

    def cells(self) -> Size:
        """This widget's size in the window font's character cells: a cell is the font's
        average character across and one line down, so a row of text fits as many
        characters as a terminal row of that many cells does."""
        metrics = self.fontMetrics()
        return Size(max(1, self.width() // max(1, metrics.averageCharWidth())),
                    max(1, self.height() // max(1, metrics.lineSpacing())))

    def arrange(self, *, animate: bool = True) -> None:
        cells = self.cells()
        pixels = self.rect()
        arranged = self.arrange_chrome(cells)
        pages = cells_to_pixels(arranged.content, cells, pixels)
        collapsed = {bar.placement_identity: bar.collapsed for bar in self.sidebars if bar in arranged.bars}
        hold_pages = False
        order = {identity: index for index, identity in enumerate(self._layout.ordered())}
        for bar in sorted(self.sidebars, key=lambda bar: order[bar.placement_identity]):
            region = arranged.bars.get(bar)
            if region is None:
                self._land(bar)
                self.placed.pop(bar, None)
                bar.toggle.set_trailing_splitter(False)
                bar.hide()
                continue
            bar.toggle.set_trailing_splitter(self._layout.splits_after(bar.placement_identity, collapsed))
            now = PlacedSidebar(region, bar.collapsed)
            slide = self.slides.get(bar)
            if slide is not None and slide.target == now:
                slide.pages = pages
                hold_pages = hold_pages or slide.opening
                bar.raise_()
                continue
            self._land(bar)
            before = self.placed.get(bar)
            self.placed[bar] = now
            if (animate and before is not None and before.folded != now.folded
                    and self.clock.enabled and self.isVisible()):
                opening = not now.folded
                self.slides[bar] = PaneSlide(self, bar, now if opening else before,
                                             before if opening else now,
                                             opening=opening, pages=pages)
                hold_pages = hold_pages or opening
            else:
                bar.place(cells_to_pixels(region, cells, pixels), region.size)
            bar.show()
            bar.raise_()
        if not hold_pages:
            self.pages.setGeometry(pages)

    def pixels(self, placed: PlacedSidebar) -> QRect:
        """A placed sidebar's cells as this chrome's pixels."""
        return cells_to_pixels(placed.region, self.cells(), self.rect())

    def _land(self, bar: QtSideBar) -> None:
        slide = self.slides.get(bar)
        if slide is not None:
            slide.finish()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.arrange(animate=False)
