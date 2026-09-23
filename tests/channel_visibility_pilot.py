"""Sort menu checkboxes persist stopped/archived visibility across views."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, ThreadStatus, wire
from runtime_fixture import ToadApp
from toad.screens.comms import CommsScreen
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar, CommsRow
from toad.widgets.session_sort import ChannelListSort


async def sync(app, pilot):
    sidebar = app.screen.query_one(CommsSidebar)
    await sidebar.sync_sessions()
    await pilot.pause()
    group = next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#team")
    if not group.expanded:
        group.toggle_members()
        await pilot.pause()
    return group


async def choose(app, pilot, action, checked):
    selector = app.screen.query_one(ChannelListSort)
    selector.action_choose_sort()
    await pilot.pause()
    item = next(item for item in app.screen.query(ContextMenuItem) if item.action == action)
    assert item.render().plain.strip().startswith("✓") == checked
    await pilot.click(item)
    await pilot.pause()


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-channel-visibility-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        owner = root.name
        for name in (owner, "stopped", "archived"):
            source = root / f"{name}.jsonl"
            source.touch()
            comms.register(Thread(name, frozenset({"team"}), str(root), session_file=str(source)))
        comms.stop("stopped")
        comms.stop("archived")
        comms.archive("archived")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            group = await sync(app, pilot)
            assert set(group._members) == {owner, "stopped"}
            selector = app.screen.query_one(ChannelListSort)
            selector.action_choose_sort()
            await pilot.pause()
            items = {item.action: item.render().plain.strip() for item in app.screen.query(ContextMenuItem)}
            assert items["show_stopped"].startswith("✓")
            assert not items["show_archived"].startswith("✓")
            await pilot.click(next(item for item in app.screen.query(ContextMenuItem)
                                   if item.action == "show_stopped"))
            group = await sync(app, pilot)
            assert set(group._members) == {owner}
            await choose(app, pilot, "show_archived", False)
            group = await sync(app, pilot)
            assert set(group._members) == {owner, "archived"}
            assert app.settings.get("sidebar.show_archived", bool)
            assert not app.settings.get("sidebar.show_stopped", bool)
            assert group._members["archived"].kind == "dm"
            await choose(app, pilot, "show_archived", True)
            group = await sync(app, pilot)
            assert set(group._members) == {owner}
            await choose(app, pilot, "show_archived", False)
            group = await sync(app, pilot)
            archived = group._members["archived"]
            assert isinstance(archived, CommsRow)
            archived.action_open_selected()
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen) and app.screen.kind == "dm"
            assert comms.registry.status("archived") is ThreadStatus.ARCHIVED
            assert not comms.registry.status("stopped").active
            await app.switch_mode("session-1")
            await pilot.pause()
            assert app.screen.query_one(CommsSidebar).visible_filters == (False, True)
        fresh = ToadApp(project_dir=str(root))
        async with fresh.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            assert fresh.screen.query_one(CommsSidebar).visible_filters == (False, True)
            group = await sync(fresh, pilot)
            assert set(group._members) == {owner, "archived"}
        await asyncio.get_running_loop().shutdown_default_executor()
    print("channel visibility: checked stopped/archived options persist; archived DM does not restart owner")


if __name__ == "__main__":
    asyncio.run(main())
