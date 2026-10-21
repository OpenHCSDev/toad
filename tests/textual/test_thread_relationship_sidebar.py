"""Textual-facing: the right-hand relationship panel (collapsible side bar, row widgets, menus) follows Core's relationships."""

import os
from unittest.mock import patch

from agent_comms.activity import ActivityState
from agent_comms.display_order import ThreadSort
from agent_comms.relationships import AddRelationshipEdit
from agent_comms.tools import invoke_tool


async def reveal(ui, session):
    from toad.widgets.side_bar import SideBar, SideBarCollapsible
    from toad.widgets.thread_comms import ThreadCommsSidebar

    sidebar = session.query_one("#thread-sidebar", SideBar)
    sidebar.reveal()
    await sidebar.wait_content_ready()
    tree = sidebar.query_one(ThreadCommsSidebar)
    tree.query_ancestor(SideBarCollapsible).collapsed = False
    await ui.step()
    await ui.until(lambda: len(tree.groups) == 5, why="the five relationship groups")
    return tree


async def test_relationship_groups_follow_core_edits_tools_sorting_and_renames(workspace):
    from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
    from toad.widgets.side_bar import SideBar, SideBarCollapsible
    from toad.widgets.thread_comms import RelationshipSort

    comms = workspace.comms
    project = str(workspace.project)
    for name, parent in (("origin", None), ("owner", "origin"), ("peer", None),
                         ("child-one", "owner"), ("child-two", "owner")):
        comms.registry.declare(comms.registry.new_thread(name, frozenset({"team"}), project, parent=parent))
    comms.messaging.send("peer", "owner", "Review request")
    comms.messaging.send("owner", "#team", "Published status")
    comms.relationships.edit("owner", AddRelationshipEdit, "peer", "Review the sidebar")

    async with workspace.app(size=(130, 44)) as ui:
        app, pilot = ui.textual
        owner_tab = ui.selected_tab
        main = app.selected_session
        await main.on_coordination_update(comms.configuration.answer("owner"))
        draft = "Keep the native thread draft"
        await ui.write_draft(draft)
        service = app.coordination_access.service.relationships
        with patch.object(service, "snapshot", wraps=service.snapshot) as read:
            await ui.step()
            assert read.call_count == 0, "Collapsed right panel fetched source data"
            assert not main.query_one("#thread-sidebar", SideBar)._panels_loaded
            tree = await reveal(ui, main)
            assert not tree.query_ancestor(SideBarCollapsible).collapsed
            assert read.call_count >= 1
        assert tree._snapshot.owner == "owner"
        assert tree.groups["parent"].model.entries[0].target == "origin"
        assert {row.target for row in tree.groups["children"].model.entries} == {"child-one", "child-two"}
        assert tree.groups["inbound"].model.entries[0].target == "peer"
        assert tree.groups["outbound"].model.entries[0].target == "#team"
        peer_group = comms.relationships.snapshot("peer").groups[4]
        assert peer_group.entries[0].target == "owner"
        assert peer_group.entries[0].detail == "Review the sidebar"

        with patch.dict(os.environ, {"PI_AGENT_ID": "peer"}):
            invoke_tool(comms, "comms_collaboration", {"action": "remove", "peer": "owner"})
        await ui.until(lambda: not tree.groups["collaborating"].model.entries
                       and ("thread", "peer") not in tree.groups["collaborating"].rows,
                       why="the removed collaboration to leave the panel")
        assert comms.relationships.snapshot("peer").groups[4].entries == ()
        with patch.dict(os.environ, {"PI_AGENT_ID": "peer"}):
            invoke_tool(comms, "comms_collaboration", {"action": "add", "peer": "owner", "note": "Review the sidebar"})
        await ui.until(lambda: ("thread", "peer") in tree.groups["collaborating"].rows, why="the restored collaboration")
        row = tree.groups["collaborating"].rows["thread", "peer"]
        assert row.available and "Review the sidebar" in str(row.tooltip)
        with patch.dict(os.environ, {"PI_AGENT_ID": "owner"}):
            invoke_tool(comms, "comms_collaboration",
                        {"action": "add", "peer": "child-one", "note": "Joint implementation"})
        await ui.until(lambda: ("thread", "child-one") in tree.groups["collaborating"].rows, why="a second collaboration")
        assert tree.groups["collaborating"].rows["thread", "peer"] is row
        with patch.dict(os.environ, {"PI_AGENT_ID": "owner"}):
            invoke_tool(comms, "comms_collaboration", {"action": "remove", "peer": "child-one"})
        await ui.until(lambda: ("thread", "child-one") not in tree.groups["collaborating"].rows,
                       why="the second collaboration to leave")

        sort = tree.query_ancestor(SideBarCollapsible).query_one(RelationshipSort)
        sort.scroll_visible(animate=False)
        await ui.step()
        assert await pilot.click(sort)
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the sort menu")
        activity_item = next(item for item in app.screen.query(ContextMenuItem)
                             if item.action == ThreadSort.LAST_ACTIVITY.value)
        assert await pilot.click(activity_item)
        await ui.until(lambda: comms.relationships.snapshot("owner").groups[3].order is ThreadSort.LAST_ACTIVITY,
                       why="the chosen order to be stored")
        comms.agents.set_activity("child-one", ActivityState.WORKING, "Building shared components")
        await ui.until(lambda: tree.groups["children"].model.entries[0].target == "child-one",
                       why="the working child to sort first")

        target_row = tree.groups["outbound"].rows["channel", "#team"]
        target_row.scroll_visible(animate=False)
        await ui.step()
        assert await pilot.click(target_row)
        await ui.until(lambda: ui.selected_tab != owner_tab, why="the channel tab to open")
        channel_tab = ui.selected_tab
        channel_session = app.selected_session
        assert not channel_session.query_one("#thread-comms-panel", SideBarCollapsible).collapsed
        channel_tree = await reveal(ui, channel_session)
        assert channel_tree._snapshot.owner == "owner", "Channel became the relationship owner"
        await ui.select_tab(owner_tab)
        assert ui.draft() == draft
        tree.groups["outbound"].rows["channel", "#team"].action_open_selected()
        await ui.until(lambda: ui.selected_tab == channel_tab, why="the channel to open again")
        await ui.select_tab(owner_tab)
        row.scroll_visible(animate=False)
        await ui.step()
        assert await pilot.click(row, button=3)
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the row menu")
        old_peer = comms.registry.require("peer")
        comms.owners.stop("peer")
        comms.registry.remove("peer")
        comms.registry.declare(comms.registry.new_thread("peer", frozenset(), project, created_at=old_peer.created_at + 1))
        open_item = next(item for item in app.screen.query(ContextMenuItem) if item.action == "open")
        assert await pilot.click(open_item)
        await ui.until(lambda: not tree.groups["collaborating"].rows["thread", "peer"].available,
                       why="the replaced peer to be unavailable")
        row = tree.groups["collaborating"].rows["thread", "peer"]
        assert "Unavailable" in row.render().plain
        assert "Review the sidebar" in str(row.tooltip)
        row.action_open_selected()
        await ui.step()
        assert ui.selected_tab == owner_tab
        with patch.object(app, "copy_to_clipboard") as copy:
            row.scroll_visible(animate=False)
            await ui.step()
            assert await pilot.click(row, button=3)
            await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the unavailable row's menu")
            items = list(app.screen.query(ContextMenuItem))
            assert [item.action for item in items] == ["copy"]
            assert await pilot.click(items[0])
            await ui.step()
            copy.assert_called_once_with("peer")

        with patch.dict(os.environ, {"PI_AGENT_ID": "owner"}):
            comms.threads.rename_self("renamed-owner")
        await main.on_coordination_update(comms.configuration.answer("renamed-owner"))
        await ui.until(lambda: tree._snapshot is not None and tree._snapshot.owner == "renamed-owner",
                       why="the panel to follow the rename")
        await ui.select_tab(channel_tab)
        await ui.until(lambda: channel_tree._snapshot is not None and channel_tree._snapshot.owner == "renamed-owner",
                       why="the channel tab's panel to follow the rename")
        await ui.select_tab(owner_tab)
        assert ui.draft() == draft
