"""The shared Channels view, including during a destination's loading frame."""

from typing import TYPE_CHECKING, cast

from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.session_sort import ChannelListSort
from toad.widgets.side_bar import SideBar, CommsSideBar
from textual.widget import Widget
from textual.screen import Screen

if TYPE_CHECKING:
    from toad.app import ToadApp


class ChannelsSidebar(CommsSideBar):
    def __init__(self, session_thread: str = "", selected_target: str = "", *,
                 observe: bool = True, defer_mount: bool = False) -> None:
        self.roster = CommsSidebar(
            session_thread=session_thread, selected_target=selected_target, observe=observe,
        )
        super().__init__(
            SideBar.Panel(
                "Channels",
                self.roster,
                flex=True,
                header_control=ChannelListSort(),
            ),
            id="channels-sidebar",
            defer_mount=defer_mount,
        )

    def set_session_thread(self, thread: str) -> None:
        self.roster.session_thread = thread


class ChannelsSlot(Widget):
    """A tab declares where shared navigation belongs; it owns no channel rows."""

    DEFAULT_CSS = "ChannelsSlot { display: none; }"


class SharedChannels:
    """One application-owned Channels tree, transferred before mode presentation."""

    def __init__(self) -> None:
        self.bar: ChannelsSidebar | None = None

    async def attach(self, screen: Screen, *, mode: str) -> bool:
        """Transfer to a still-live native mode; a closed destination cancels it."""
        app = cast("ToadApp", screen.app)
        slot = screen.query_one_optional(ChannelsSlot)
        if self.bar is None:
            if slot is None:
                return True
            self.bar = ChannelsSidebar()
        bar = self.bar
        parent = slot.parent if slot is not None else screen
        assert isinstance(parent, Widget)
        if slot is not None and bar.is_mounted:
            # Route replacement can await an older publication. Keep custody on
            # the departing screen until that wait finishes, so cancellation
            # cannot prune the shared tree with a not-yet-selected destination.
            await bar.roster.bind_wire(app.coordination_wire)
        stack = app._screen_stacks.get(mode)
        if (not stack or stack[0] is not screen or not screen.is_attached
                or screen._closing or screen._pruning):
            return False
        if bar.is_mounted:
            if bar.parent is not parent:
                # Navigation ends an in-progress sidebar gesture through the
                # native release event; transfer must not move mouse capture.
                captured = app.mouse_captured
                if captured is not None and bar in captured.ancestors_with_self:
                    captured.release_mouse()
                bar.reparent(parent, before=slot)
                bar._presented_layout = None
        else:
            await parent.mount(bar, before=slot)
        bar.display = slot is not None
        bar.roster.set_observation_enabled(slot is not None)
        if slot is not None:
            from toad.screens.session_view import SessionView

            assert isinstance(screen, SessionView)
            actor, target = screen.channels_context()
            bar.roster.session_thread = actor
            bar.roster.selected = target
        return True
