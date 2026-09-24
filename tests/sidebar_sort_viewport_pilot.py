"""Sorting stays on the visible right edge while long sidebar rows scroll."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp

from toad.acp.messages import CoordinationUpdate
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.session_sort import SortControl
from toad.widgets.side_bar import SideBar
from toad.widgets.thread_comms import ThreadCommsSidebar


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-sort-viewport-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        comms = wire(root / "wire")
        comms.register(Thread("owner", frozenset({"team"}), str(root)))
        peer = "collaborator-with-a-long-label-" * 4
        comms.register(Thread(peer, frozenset({"team"}), str(root)))
        comms.relationships.edit("owner", "add", peer, "Review")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.screen.on_coordination_update(CoordinationUpdate(
                thread="owner", wire_root=str(root / "wire"),
                persistence="persistent", transport="stdio",
            ))
            await app.screen.query_one(CommsSidebar).sync_sessions()
            right = app.screen.query_one("#thread-sidebar", SideBar)
            right.reveal()
            tree = right.query_one(ThreadCommsSidebar)
            async with asyncio.timeout(5):
                while tree._snapshot is None:
                    await pilot.pause(.05)
            for identity in ("channels-sidebar", "thread-sidebar"):
                bar = app.screen.query_one(f"#{identity}", SideBar)
                panels = bar.query_one("#sidebar-panels")
                for width in (40, 25, 15):
                    app.sidebar_layout.width(identity, width)
                    app.sidebar_layout_changed.publish(None)
                    await pilot.pause()
                    assert panels.max_scroll_x > 0
                    for x in (0, panels.max_scroll_x, 0):
                        panels.scroll_to(x=x, animate=False, immediate=True)
                        await pilot.pause()
                        viewport = panels.scrollable_content_region
                        visible = [control for control in bar.query(SortControl)
                                   if viewport.y <= control.region.y < viewport.bottom]
                        assert visible, "Expected a visible sort header"
                        for control in visible:
                            assert viewport.x <= control.region.x < control.region.right <= viewport.right, (
                                identity, width, x, control.region, viewport,
                            )
                            assert control.region.right == viewport.right
                            assert await pilot.click(control)
                            assert isinstance(app.screen, ContextMenu)
                            await pilot.press("escape")
                            await pilot.pause()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("sort controls: fixed viewport-right alignment through resize and horizontal scrolling")


if __name__ == "__main__":
    asyncio.run(main())
