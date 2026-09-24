"""One-cell busy labels repaint in place; loading ring honors cell aspect ratio."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms import ActivityState, Thread, wire
from runtime_fixture import ToadApp
from textual.app import App, ComposeResult
from textual.content import Content

from toad.acp.messages import CoordinationUpdate
from toad.widgets.activity_spinner import FRAMES
from toad.widgets.comms_chat import session_thread_name
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.conversation import ThreadLoading
from toad.widgets.session_tabs import SessionLabel, SessionsTabs
from toad.widgets.side_bar import SideBar
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.widgets.virtual_channel_list import VirtualChannelList


class LoadingApp(App):
    def compose(self) -> ComposeResult:
        yield ThreadLoading()


async def check_loading_ring() -> None:
    app = LoadingApp()
    async with app.run_test(size=(86, 38)) as pilot:
        await pilot.pause()
        ring = app.query_one(ThreadLoading)
        rows = ring.render().plain.splitlines()
        dots = [(x, y) for y, row in enumerate(rows)
                for x, char in enumerate(row) if char in "●•·"]
        x_extent = max(x for x, _ in dots) - min(x for x, _ in dots) + 1
        y_extent = max(y for _, y in dots) - min(y for _, y in dots) + 1
        assert abs(x_extent / y_extent - 2.2) < .35, (x_extent, y_extent)


async def check_busy_labels() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-activity-spinners-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"),
                          TOAD_BENCH_VIRTUAL_CHANNELS="1")
        me = session_thread_name(root)
        comms = wire(root / "wire")
        for name in (me, "busy-worker"):
            comms.register(Thread(name, frozenset({"team"}), str(root), pid=os.getpid()))
            comms.set_activity(name, ActivityState.THINKING, "working")
        comms.relationships.edit(me, "add", "busy-worker", "Joint review")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.sync_sessions()
            listing = sidebar.query_one(VirtualChannelList)
            rows = [item for item in listing.options
                    if isinstance(item.prompt, Content) and "busy-worker" in item.prompt.plain]
            assert rows and any(frame in row.prompt.plain for frame in FRAMES for row in rows)
            tabs = app.screen.query_one(SessionsTabs)
            await tabs._sync_tabs()
            first = next(tab for tab in app.open_tabs if tab.mode_name == app.current_mode)
            label = app.screen.query_one(f"SessionLabel#{first.mode_name}", SessionLabel)
            assert first.title.startswith("⌛ ") and label.render().plain[0] in FRAMES
            before_sidebar = rows[0].prompt.plain
            before_tab = label.render().plain
            with patch.object(app.screen, "_refresh_layout", wraps=app.screen._refresh_layout) as layout:
                sidebar._animate_busy()
                tabs._animate_busy()
                await pilot.pause()
                assert rows[0].prompt.plain != before_sidebar
                assert label.render().plain != before_tab
                assert rows[0].prompt.plain[0] == " "  # Indent stays, marker remains one cell.
                assert layout.call_count == 0, "Spinner repaint triggered full layout"

            await app.screen.on_coordination_update(CoordinationUpdate(
                thread=me, wire_root=str(root / "wire"),
                persistence="persistent", transport="stdio",
            ))
            app.screen.query_one("#thread-sidebar", SideBar).reveal()
            tree = app.screen.query_one(ThreadCommsSidebar)
            async with asyncio.timeout(5):
                while tree._snapshot is None:
                    await pilot.pause(.05)
            row = tree.groups["collaborating"].rows[("thread", "busy-worker")]
            before_right = row.render().plain
            tree._animate_busy()
            await pilot.pause()
            assert row.render().plain != before_right
            assert any(frame in row.render().plain for frame in FRAMES)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


async def main() -> None:
    await check_loading_ring()
    await check_busy_labels()
    print("round loading ring and paint-only one-cell activity spinners")


if __name__ == "__main__":
    asyncio.run(main())
