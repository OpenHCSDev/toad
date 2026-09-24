"""Real screen mounts and core-backed relationship updates in an isolated wire."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.acp.messages import CoordinationUpdate
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar

from agent_comms import ActivityState, Thread, ThreadSort, wire
from agent_comms.tools import invoke_tool


async def wait_until(pilot, condition):
    async with asyncio.timeout(8):
        while not condition():
            await pilot.pause(.02)


async def reveal(screen, pilot):
    sidebar = screen.query_one("#thread-sidebar", SideBar)
    sidebar.reveal()
    tree = sidebar.query_one(ThreadCommsSidebar)
    tree.query_ancestor(SideBarCollapsible).collapsed = False
    await pilot.pause()
    await wait_until(pilot, lambda: len(tree.groups) == 5)
    return tree


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-comms-integrated-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        for name, parent in (("origin", None), ("owner", "origin"), ("peer", None),
                             ("child-one", "owner"), ("child-two", "owner")):
            comms.register(Thread(name, frozenset({"team"}), str(root), parent=parent))
        comms.send("peer", "owner", "Review request")
        comms.send("owner", "#team", "Published status")
        comms.relationships.edit("owner", "add", "peer", "Review the sidebar")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(130, 44)) as pilot:
            await pilot.pause()
            owner_mode = app.current_mode
            await app.screen.on_coordination_update(CoordinationUpdate(
                thread="owner", wire_root=str(root / "wire"), persistence="persistent",
                transport="stdio"))
            main = app.screen
            draft = "Keep the native thread draft"
            main.conversation.prompt.text = draft
            service = app.coordination_wire.relationships
            with patch.object(service, "snapshot", wraps=service.snapshot) as read:
                await pilot.pause()
                assert read.call_count == 0, "Collapsed right panel fetched source data"
                assert not main.query_one("#thread-comms-panel", SideBarCollapsible).collapsed
                tree = await reveal(main, pilot)
                assert read.call_count >= 1
            assert tree._snapshot.owner == "owner"
            assert tree.groups["parent"].model.entries[0].target == "origin"
            assert set(row.target for row in tree.groups["children"].model.entries) == {
                "child-one", "child-two"}
            assert tree.groups["inbound"].model.entries[0].target == "peer"
            assert tree.groups["outbound"].model.entries[0].target == "#team"
            # The peer's core projection is the same shared pair. A removal
            # from that side updates the owner's already-mounted panel.
            peer_group = comms.relationships.snapshot("peer").groups[4]
            assert peer_group.entries[0].target == "owner"
            assert peer_group.entries[0].detail == "Review the sidebar"
            with patch.dict(os.environ, {"PI_AGENT_ID": "peer"}):
                invoke_tool(comms, "comms_collaboration", {
                    "action": "remove", "peer": "owner"})
            await wait_until(pilot, lambda: not tree.groups["collaborating"].model.entries)
            assert comms.relationships.snapshot("peer").groups[4].entries == ()
            with patch.dict(os.environ, {"PI_AGENT_ID": "peer"}):
                invoke_tool(comms, "comms_collaboration", {
                    "action": "add", "peer": "owner", "note": "Review the sidebar"})
            await wait_until(pilot, lambda: ("thread", "peer") in
                             tree.groups["collaborating"].rows)
            row = tree.groups["collaborating"].rows["thread", "peer"]
            assert row.available and "Review the sidebar" in str(row.tooltip)

            # Exercise actual declared agent tools on the disposable wire.
            with patch.dict(os.environ, {"PI_AGENT_ID": "owner"}):
                invoke_tool(comms, "comms_collaboration", {
                    "action": "add", "peer": "child-one", "note": "Joint implementation"})
            await wait_until(pilot, lambda: ("thread", "child-one") in
                             tree.groups["collaborating"].rows)
            assert tree.groups["collaborating"].rows["thread", "peer"] is row
            with patch.dict(os.environ, {"PI_AGENT_ID": "owner"}):
                invoke_tool(comms, "comms_collaboration", {"action": "remove", "peer": "child-one"})
            await wait_until(pilot, lambda: ("thread", "child-one") not in
                             tree.groups["collaborating"].rows)
            sort = tree.query_ancestor(SideBarCollapsible).query_one(RelationshipSort)
            sort.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(sort)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            activity_item = next(item for item in app.screen.query(ContextMenuItem)
                                 if item.action == ThreadSort.LAST_ACTIVITY.value)
            assert await pilot.click(activity_item)
            await pilot.pause()
            assert comms.relationships.snapshot("owner").groups[3].order is ThreadSort.LAST_ACTIVITY
            comms.set_activity("child-one", ActivityState.WORKING, "Building shared components")
            await wait_until(pilot, lambda: tree.groups["children"].model.entries[0].target
                             == "child-one")

            # Navigation goes through the real screen handler and reuses a tab.
            target_row = tree.groups["outbound"].rows["channel", "#team"]
            target_row.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(target_row)
            await wait_until(pilot, lambda: getattr(app.screen, "target", None) == "#team")
            await app.screen.wait_content_ready()
            channel_mode = app.current_mode
            assert not app.screen.query_one("#thread-comms-panel", SideBarCollapsible).collapsed
            channel_tree = await reveal(app.screen, pilot)
            assert channel_tree._snapshot.owner == "owner", "Channel became the relationship owner"
            await app.switch_mode(owner_mode)
            await pilot.pause()
            assert main.conversation.prompt.text == draft
            tree.groups["outbound"].rows["channel", "#team"].action_open_selected()
            await wait_until(pilot, lambda: app.current_mode == channel_mode)
            await app.switch_mode(owner_mode)
            await pilot.pause()

            # A menu opened before deletion/name reuse remains bound to the old
            # relationship. Choosing Open must not navigate to the new thread.
            row.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(row, button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            old_peer = comms.registry.require("peer")
            comms.stop("peer")
            comms.delete("peer")
            comms.register(Thread("peer", frozenset(), str(root),
                                  created_at=old_peer.created_at + 1))
            open_item = next(item for item in app.screen.query(ContextMenuItem)
                             if item.action == "open")
            assert await pilot.click(open_item)
            await wait_until(pilot, lambda: not row.available)
            assert "Unavailable" in row.render().plain
            assert "Review the sidebar" in str(row.tooltip)
            row.action_open_selected()
            await pilot.pause()
            assert app.current_mode == owner_mode
            with patch.object(app, "copy_to_clipboard") as copy:
                row.scroll_visible(animate=False)
                await pilot.pause()
                assert await pilot.click(row, button=3)
                await pilot.pause()
                items = list(app.screen.query(ContextMenuItem))
                assert [item.action for item in items] == ["copy"]
                assert await pilot.click(items[0])
                await pilot.pause()
                copy.assert_called_once_with("peer")
            # Owner rename propagates to native and already-open channel panels.
            with patch.dict(os.environ, {"PI_AGENT_ID": "owner"}):
                comms.rename_self("renamed-owner")
            await main.on_coordination_update(CoordinationUpdate(
                thread="renamed-owner", wire_root=str(root / "wire"),
                persistence="persistent", transport="stdio"))
            await wait_until(pilot, lambda: tree._snapshot is not None
                             and tree._snapshot.owner == "renamed-owner")
            await app.switch_mode(channel_mode)
            await pilot.pause()
            await wait_until(pilot, lambda: channel_tree._snapshot is not None
                             and channel_tree._snapshot.owner == "renamed-owner")
            await app.switch_mode(owner_mode)
            await pilot.pause()
            assert main.conversation.prompt.text == draft
            if path := os.environ.get("TOAD_RIGHT_SIDEBAR_SVG"):
                app.save_screenshot(path)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("right Comms integrated: native/channel mounts, real tools, live sort, "
          "tab reuse, drafts, unavailable/copy semantics")


if __name__ == "__main__":
    asyncio.run(main())
