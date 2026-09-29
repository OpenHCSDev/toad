"""The shared Channels view, including during a destination's loading frame."""

from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.session_sort import ChannelListSort
from toad.widgets.side_bar import SideBar, CommsSideBar
from textual.widget import Widget


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


class ChannelsSlot(Widget):
    """A tab declares where shared navigation belongs; it owns no channel rows."""

    DEFAULT_CSS = "ChannelsSlot { display: none; }"
