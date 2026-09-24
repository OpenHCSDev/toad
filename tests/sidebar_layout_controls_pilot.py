"""Mounted sidebar move/swap/size/float controls and real untruncated row scroll."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from textual.content import Content
from textual.containers import VerticalScroll

from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import SideBar, SidebarAction, SidebarSlider, TabHistoryControls
from toad.widgets.virtual_channel_list import VirtualChannelList


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-sidebar-controls-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"),
                          TOAD_BENCH_VIRTUAL_CHANNELS="1")
        name = "very-long-thread-name-with-an-explanatory-suffix-that-exceeds-the-sidebar-width"
        comms = wire(root / "wire")
        comms.register(Thread(name, frozenset({"alpha"}), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            left = app.screen.query_one("#channels-sidebar", SideBar)
            right = app.screen.query_one("#thread-sidebar", SideBar)
            content = app.screen.query_one("#session-content")
            tabs = app.screen.query_one(SessionsTabs)
            assert left.region.x == 0 and right.right
            assert tabs.region.x == app.screen.query_one(TabHistoryControls).region.right
            left.query_one("#sidebar-width-slider", SidebarSlider).action_step(1)
            await pilot.pause()
            assert app.sidebar_layout.get("channels-sidebar").width_percent == 41
            assert left.region.width >= 40

            left.query_one("#sidebar-move", SidebarAction).action_activate()
            await pilot.pause()
            assert left.right and right.right
            assert right.region.x > left.region.x, "New right bar belongs inside the existing outer one"
            assert content.region.x == 0
            assert tabs.region.x == app.screen.query_one(TabHistoryControls).region.right
            left.query_one("#sidebar-swap", SidebarAction).action_activate()
            await pilot.pause()
            assert left.region.x > right.region.x
            assert content.region.x == 0

            pushing_width = content.region.width
            left.query_one("#sidebar-float", SidebarAction).action_activate()
            await pilot.pause()
            assert app.sidebar_layout.get("channels-sidebar").floating
            # An inner pushed handle reserves space through its inside edge.
            assert content.region.width >= pushing_width
            assert left.region.x >= content.region.x and left.region.width > 3
            assert content.region.x == 0
            left.query_one("#sidebar-float", SidebarAction).action_activate()
            await pilot.pause()
            assert not app.sidebar_layout.get("channels-sidebar").floating

            sidebar = app.screen.query_one(CommsSidebar)
            async with asyncio.timeout(5):
                while sidebar._last_snapshot is None:
                    await pilot.pause(.02)
            listing = sidebar.query_one(VirtualChannelList)
            member = next(option for option in listing.options
                          if isinstance(option.prompt, Content) and name in option.prompt.plain)
            assert name in member.prompt.plain, "Source label must not be pre-truncated"
            panels = left.query_one("#sidebar-panels", VerticalScroll)
            assert panels.max_scroll_x > 0 and listing.size.width > panels.size.width
            assert not left.query("#sidebar-horizontal-slider")
            await pilot.click(panels.horizontal_scrollbar,
                              offset=(panels.horizontal_scrollbar.size.width - 1, 0))
            await pilot.pause()
            assert panels.scroll_x > 0 and app._exception is None

            owner = app.current_mode
            await app.open_comms_session(owner_mode=owner, project_path=root,
                                         me=name, target="#alpha", kind="channel")
            comms_bar = app.screen.query_one("#channels-sidebar", SideBar)
            comms_tabs = app.screen.query_one(SessionsTabs)
            chat = app.screen.query_one("#comms-content")
            assert comms_bar.right and chat.region.x == 0, (
                comms_bar.region, comms_tabs.region, chat.region,
                app.sidebar_layout.ordered(), app.screen.query_one("#tab-navigation-header").styles.padding,
            )
            comms_bar.query_one("#sidebar-move", SidebarAction).action_activate()
            await pilot.pause()
            assert not comms_bar.right
            assert chat.region.x == comms_bar.region.width
            assert comms_tabs.region.x == app.screen.query_one(TabHistoryControls).region.right
            await pilot.resize_terminal(76, 34)
            assert chat.region.x == comms_bar.region.width
            assert comms_tabs.region.right == 76
            await app.switch_mode(owner)
            assert not left.right and content.region.x == left.region.width
            assert tabs.region.x == app.screen.query_one(TabHistoryControls).region.right
        await asyncio.get_running_loop().shutdown_default_executor()
    print("sidebar controls: move/swap/width/float and untruncated horizontal row scroll")


if __name__ == "__main__":
    asyncio.run(main())
