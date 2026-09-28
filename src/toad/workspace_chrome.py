"""Application-owned navigation presentations, independent of session identity."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar, cast

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widget import Widget
from toad.widgets.channels_sidebar import ChannelsSidebar

if TYPE_CHECKING:
    from toad.app import ToadApp


class NavigationSlot(Widget):
    """A host location; it never constructs another global tab list."""

    DEFAULT_CSS = "NavigationSlot { display: none; }"


class WorkspaceHeader(Horizontal):
    def __init__(self) -> None:
        super().__init__(id="tab-navigation-header")

    def compose(self) -> ComposeResult:
        from toad.widgets.session_tabs import SessionsTabs
        from toad.widgets.side_bar import TabHistoryControls

        yield TabHistoryControls()
        yield SessionsTabs()


Presentation = TypeVar("Presentation", bound=Widget)


class WorkspaceProjection(ABC, Generic[Presentation]):
    """One retained presentation, with behavior supplied by its nominal owner."""

    def __init__(self, widget: Presentation) -> None:
        self.widget = widget

    @abstractmethod
    def slot(self, screen: Screen) -> Widget | None: ...

    async def prepare(self, screen: Screen, slot: Widget | None) -> None:
        """Resolve any source binding before the presentation changes custody."""

    def activate(self, screen: Screen, slot: Widget | None) -> None:
        self.widget.display = slot is not None

    async def attach(self, screen: Screen, slot: Widget | None) -> None:
        parent = slot.parent if slot is not None else screen
        assert isinstance(parent, Widget)
        widget = self.widget
        if widget.is_mounted:
            if widget.parent is not parent:
                captured = screen.app.mouse_captured
                if captured is not None and widget in captured.ancestors_with_self:
                    captured.release_mouse()
                widget.reparent(parent, before=slot)
        else:
            await parent.mount(widget, before=slot)
        self.activate(screen, slot)


class NavigationProjection(WorkspaceProjection[WorkspaceHeader]):
    def __init__(self) -> None:
        super().__init__(WorkspaceHeader())

    def slot(self, screen: Screen) -> NavigationSlot | None:
        return screen.query_one_optional(NavigationSlot)


class ChannelsProjection(WorkspaceProjection[ChannelsSidebar]):
    def __init__(self) -> None:
        super().__init__(ChannelsSidebar())

    def slot(self, screen: Screen) -> Widget | None:
        from toad.widgets.channels_sidebar import ChannelsSlot

        return screen.query_one_optional(ChannelsSlot)

    async def prepare(self, screen: Screen, slot: Widget | None) -> None:
        if slot is not None and self.widget.is_mounted:
            await self.widget.roster.bind_wire(cast("ToadApp", screen.app).coordination_wire)

    def activate(self, screen: Screen, slot: Widget | None) -> None:
        super().activate(screen, slot)
        self.widget._presented_layout = None
        self.widget.roster.set_observation_enabled(slot is not None)
        if slot is not None:
            from toad.screens.session_view import SessionView

            assert isinstance(screen, SessionView)
            actor, target = screen.channels_context()
            self.widget.roster.session_thread = actor
            self.widget.roster.selected = target


class WorkspaceChrome:
    """Single ownership of the workspace header and Channels presentation."""

    def __init__(self) -> None:
        self.navigation = NavigationProjection()
        self.channels = ChannelsProjection()

    async def attach(self, screen: Screen, *, mode: str) -> bool:
        app = cast("ToadApp", screen.app)
        placements = tuple((projection, projection.slot(screen))
                           for projection in (self.navigation, self.channels))
        for projection, slot in placements:
            await projection.prepare(screen, slot)
        stack = app._screen_stacks.get(mode)
        if (not stack or stack[0] is not screen or not screen.is_attached
                or screen._closing or screen._pruning):
            return False
        for projection, slot in placements:
            await projection.attach(screen, slot)
        return True
