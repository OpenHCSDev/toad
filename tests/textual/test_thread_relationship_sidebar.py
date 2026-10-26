"""Textual-facing: the right-hand relationship panel (collapsible side bar, row widgets, menus) follows Core's relationships."""

from unittest.mock import patch

from agent_comms.activity import ActivityState
from agent_comms.display_order import LastActivityThreadSort
from agent_comms.relationships import (
    AddRelationshipEdit,
    ChildrenRelationshipGroup,
    CollaboratingRelationshipGroup,
    InboundRelationshipGroup,
    OutboundRelationshipGroup,
    ParentRelationshipGroup,
)
from agent_comms.thread_creation import RecordedCreationTime
from agent_comms.thread_text import ForkedParent, NoParent
from agent_comms.threads import Thread
from agent_comms.tool_caller import ThreadCaller
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
    from textual.widgets import Select

    from toad.widgets.comms_menu import ContextMenu
    from toad.widgets.session_sort import SortDialog
    from toad.widgets.side_bar import SideBar, SideBarCollapsible
    from toad.widgets.thread_comms import RelationshipSort

    comms = workspace.comms
    project = str(workspace.project)
    for name, parent in (("origin", NoParent()), ("owner", ForkedParent("origin")),
                         ("peer", NoParent()), ("child-one", ForkedParent("owner")),
                         ("child-two", ForkedParent("owner"))):
        comms.registry.declare(Thread(name, frozenset({"team"}), project, parent=parent))
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
        observed = await app.preparation.run_thread(app.coordination_access.observation.observed)
        service = observed.service.relationships
        with patch.object(service, "snapshot", wraps=service.snapshot) as read:
            await ui.step()
            assert read.call_count == 0, "Collapsed right panel fetched source data"
            assert not main.query_one("#thread-sidebar", SideBar)._panels_loaded
            tree = await reveal(ui, main)
            assert not tree.query_ancestor(SideBarCollapsible).collapsed
            assert read.call_count >= 1
        assert tree._snapshot.owner == "owner"
        assert tree.groups[ParentRelationshipGroup].model.entries["origin"].target == "origin"
        assert {row.target for row in tree.groups[ChildrenRelationshipGroup].model.entries.values()} == {"child-one", "child-two"}
        assert tree.groups[InboundRelationshipGroup].model.entries["peer"].target == "peer"
        assert tree.groups[OutboundRelationshipGroup].model.entries["#team"].target == "#team"
        peer_group = comms.relationships.snapshot("peer").groups_by_type[CollaboratingRelationshipGroup]
        assert peer_group.entries["owner"].target == "owner"
        assert peer_group.entries["owner"].detail == "Review the sidebar"

        invoke_tool(comms, "comms_collaboration", {"action": "remove", "peer": "owner"},
                    caller=ThreadCaller("peer"))
        await ui.until(lambda: not tree.groups[CollaboratingRelationshipGroup].model.entries
                       and "peer" not in tree.groups[CollaboratingRelationshipGroup].rows,
                       why="the removed collaboration to leave the panel")
        assert comms.relationships.snapshot("peer").groups_by_type[CollaboratingRelationshipGroup].entries == {}
        invoke_tool(comms, "comms_collaboration",
                    {"action": "add", "peer": "owner", "note": "Review the sidebar"},
                    caller=ThreadCaller("peer"))
        await ui.until(lambda: "peer" in tree.groups[CollaboratingRelationshipGroup].rows, why="the restored collaboration")
        row = tree.groups[CollaboratingRelationshipGroup].rows["peer"]
        assert row.available and "Review the sidebar" in str(row.tooltip)
        invoke_tool(comms, "comms_collaboration",
                    {"action": "add", "peer": "child-one", "note": "Joint implementation"},
                    caller=ThreadCaller("owner"))
        await ui.until(lambda: "child-one" in tree.groups[CollaboratingRelationshipGroup].rows, why="a second collaboration")
        assert tree.groups[CollaboratingRelationshipGroup].rows["peer"] is row
        invoke_tool(comms, "comms_collaboration", {"action": "remove", "peer": "child-one"},
                    caller=ThreadCaller("owner"))
        await ui.until(lambda: "child-one" not in tree.groups[CollaboratingRelationshipGroup].rows,
                       why="the second collaboration to leave")

        sort = tree.query_ancestor(SideBarCollapsible).query_one(RelationshipSort)
        sort.scroll_visible(animate=False)
        await ui.step()
        assert await pilot.click(sort)
        await ui.until(lambda: isinstance(app.screen, SortDialog), why="the sort dialog")
        app.screen.query_one(Select).value = LastActivityThreadSort
        await ui.until(lambda: comms.relationships.snapshot("owner").groups_by_type[
            ChildrenRelationshipGroup].order is LastActivityThreadSort,
            why="the chosen order to be stored")
        comms.agents.set_activity("child-one", ActivityState.WORKING, "Building shared components")
        await ui.until(lambda: next(iter(tree.groups[ChildrenRelationshipGroup].model.entries.values())).target == "child-one",
                       why="the working child to sort first")

        target_row = tree.groups[OutboundRelationshipGroup].rows["#team"]
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
        tree.groups[OutboundRelationshipGroup].rows["#team"].open_selected()
        await ui.until(lambda: ui.selected_tab == channel_tab, why="the channel to open again")
        await ui.select_tab(owner_tab)
        row.scroll_visible(animate=False)
        await ui.step()
        assert await pilot.click(row, button=3)
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the row menu")
        old_peer = comms.registry.require("peer")
        comms.owners.stop("peer")
        comms.registry.remove("peer")
        comms.registry.declare(Thread("peer", frozenset(), project,
                                      created_at=RecordedCreationTime(old_peer.created_at + 1)))
        options = app.screen.options
        open_index = next(index for index in range(options.option_count)
                          if options.get_option_at_index(index).action == "open")
        options.focus()
        await pilot.press("home", *(["down"] * open_index), "enter")
        await ui.until(lambda: not tree.groups[CollaboratingRelationshipGroup].rows["peer"].available,
                       why="the replaced peer to be unavailable")
        row = tree.groups[CollaboratingRelationshipGroup].rows["peer"]
        await ui.until(lambda: "Unavailable" in ui.painted(row),
                       why="the unavailable row to be drawn")
        assert "Review the sidebar" in str(row.tooltip)
        row.open_selected()
        await ui.step()
        assert ui.selected_tab == owner_tab
        with patch.object(app, "copy_to_clipboard") as copy:
            row.scroll_visible(animate=False)
            await ui.step()
            assert await pilot.click(row, button=3)
            await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the unavailable row's menu")
            options = app.screen.options
            assert [options.get_option_at_index(index).action
                    for index in range(options.option_count)] == ["copy"]
            options.focus()
            await pilot.press("home", "enter")
            await ui.step()
            copy.assert_called_once_with("peer")

        comms.threads.rename_self("renamed-owner", caller=ThreadCaller("owner"))
        await main.on_coordination_update(comms.configuration.answer("renamed-owner"))
        await ui.until(lambda: tree._snapshot is not None and tree._snapshot.owner == "renamed-owner",
                       why="the panel to follow the rename")
        await ui.select_tab(channel_tab)
        await ui.until(lambda: channel_tree._snapshot is not None and channel_tree._snapshot.owner == "renamed-owner",
                       why="the channel tab's panel to follow the rename")
        await ui.select_tab(owner_tab)
        assert ui.draft() == draft
