"""The ordinary channel tree retains long names behind its bottom scrollbar."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from textual.containers import VerticalScroll

from toad.acp.messages import CoordinationUpdate
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.side_bar import SideBar
from toad.widgets.thread_comms import ThreadCommsSidebar


async def check_left() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-nonvirtual-scroll-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"),
                          TOAD_BENCH_VIRTUAL_CHANNELS="")
        name = "long-thread-name-" * 5
        wire(root / "wire").register(Thread(name, frozenset({"alpha"}), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.pause()
            await app.screen.query_one(CommsSidebar).sync_sessions()
            bar = app.screen.query_one("#channels-sidebar", SideBar)
            panels = bar.query_one("#sidebar-panels", VerticalScroll)
            assert panels.max_scroll_x > 0
            assert panels.show_horizontal_scrollbar
            assert not bar.query("#sidebar-horizontal-slider")
            await pilot.click(panels.horizontal_scrollbar,
                              offset=(panels.horizontal_scrollbar.size.width - 1, 0))
            await pilot.pause()
            assert panels.scroll_x > 0
            # The row's source content remains full length; the viewport moves.
            assert any(name in row.render().plain for row in app.screen.query("ThreadStatusRow"))
            assert app._exception is None

async def check_right() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-relationship-scroll-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        name = "long-collaborator-" * 5
        for peer in ("owner", name):
            comms.register(Thread(peer, frozenset(), str(root)))
        comms.relationships.edit("owner", "add", name, "Review the whole implementation")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.pause()
            await app.screen.on_coordination_update(CoordinationUpdate(
                thread="owner", wire_root=str(root / "wire"),
                persistence="persistent", transport="stdio",
            ))
            bar = app.screen.query_one("#thread-sidebar", SideBar)
            bar.reveal()
            tree = bar.query_one(ThreadCommsSidebar)
            async with asyncio.timeout(5):
                while tree._snapshot is None:
                    await pilot.pause(.05)
            panels = bar.query_one("#sidebar-panels", VerticalScroll)
            assert panels.max_scroll_x > 0
            assert panels.show_horizontal_scrollbar
            assert not bar.query("#sidebar-horizontal-slider")
            await pilot.click(panels.horizontal_scrollbar,
                              offset=(panels.horizontal_scrollbar.size.width - 1, 0))
            await pilot.pause()
            assert panels.scroll_x > 0
            assert name in tree.groups["collaborating"].model.entries[0].target
            assert app._exception is None


async def main() -> None:
    await check_left()
    await check_right()
    await asyncio.get_running_loop().shutdown_default_executor()
    print("both ordinary sidebars preserve long rows behind one native horizontal scrollbar")


if __name__ == "__main__":
    asyncio.run(main())
