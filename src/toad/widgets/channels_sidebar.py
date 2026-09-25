"""The shared Channels view, including during a destination's loading frame."""

from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.session_sort import ChannelListSort
from toad.widgets.side_bar import SideBar


class ChannelsSidebar(SideBar):
    def __init__(self, session_thread: str = "", selected_target: str = "", *, observe: bool = True) -> None:
        super().__init__(
            SideBar.Panel(
                "Channels",
                CommsSidebar(session_thread=session_thread, selected_target=selected_target, observe=observe),
                flex=True,
                header_control=ChannelListSort(),
            ),
            id="channels-sidebar",
        )
