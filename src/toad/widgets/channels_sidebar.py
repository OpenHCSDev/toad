"""The shared Channels view, including during a destination's loading frame."""

from toad.native_style import StartsHidden
from toad.sidebar_layout import CHANNELS_PANEL
from toad.sidebar_placement import ChannelsSidebarPlacement
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.session_sort import ChannelListSort
from toad.widgets.side_bar import SideBar
from textual.widget import Widget


class ChannelsSidebar(SideBar):
    COMPOSITING_LAYER = True
    def __init__(self, *, observe: bool = True, defer_mount: bool = False) -> None:
        self.roster = CommsSidebar(observe=observe)
        super().__init__(
            SideBar.Panel(
                title=CHANNELS_PANEL.title,
                widget=self.roster,
                flex=CHANNELS_PANEL.flex,
                header_control=ChannelListSort(),
            ),
            placement_identity=ChannelsSidebarPlacement,
            defer_mount=defer_mount,
        )


class ChannelsSlot(StartsHidden, Widget):
    """A tab declares where shared navigation belongs; it owns no channel rows."""

