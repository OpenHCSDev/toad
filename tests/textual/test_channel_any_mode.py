"""Textual-facing: the channel row's context menu (a modal screen opened by a right click) toggles member activity."""

from support.textual_steps import channel_roster


ACTION = "channel-activity"


def bodies(comms):
    return [message.body for message in comms.views.channel_display_page("#team").messages]


async def open_menu_item(ui, sidebar, channel, action):
    from toad.widgets.comms_menu import ContextMenuItem
    from toad.widgets.comms_sidebar import ChannelGroup

    app, pilot = ui.textual
    group = next(row for row in sidebar.query(ChannelGroup) if row.row.target_name == channel)
    await pilot.click(group.row, button=3)
    await ui.until(lambda: app.screen.query(ContextMenuItem), why=f"the menu of {channel}")
    return next((item for item in app.screen.query(ContextMenuItem) if item.action == action), None)


async def test_channel_menu_toggles_member_activity_and_keeps_unpainted_traffic_unread(workspace):
    from toad.widgets.comms_sidebar import CommsSidebar

    workspace.thread("alice", "team")
    workspace.thread("bob", "other")
    comms = workspace.comms
    comms.messaging.send("alice", "#team", "exact route")
    comms.messaging.send("alice", "bob", "outbound from member")
    comms.messaging.send("bob", "alice", "inbound to member")
    comms.messaging.send("bob", "#other", "unrelated route")
    assert bodies(comms) == ["exact route"]

    async with workspace.app(size=(100, 30)) as ui:
        app, pilot = ui.textual
        owner = ui.selected_tab
        sidebar = await channel_roster(ui, "#team")
        item = await open_menu_item(ui, sidebar, "#team", ACTION)
        await pilot.click(item)
        await ui.step()
        assert comms.channels.catalog.read().resolve("#team").any_mode
        assert bodies(comms) == ["exact route", "outbound from member", "inbound to member"]
        assert comms.views.viewer_snapshot(str(workspace.project)).channel_unread["#team"] == 3

        await ui.open_channel("#team", actor="alice")
        await ui.until_shows("inbound to member")
        assert ui.shows("outbound from member") and ui.shows("exact route")
        await ui.select_tab(owner)
        sidebar = app.screen.query_one(CommsSidebar)

        item = await open_menu_item(ui, sidebar, "#team", ACTION)
        await pilot.click(item)
        await ui.step()
        assert not comms.channels.catalog.read().resolve("#team").any_mode
        assert bodies(comms) == ["exact route"]


async def test_menu_labels_say_which_way_the_toggle_goes(workspace):
    workspace.thread("alice", "team")
    workspace.comms.messaging.send("alice", "#team", "exact route")
    async with workspace.app(size=(100, 30)) as ui:
        _, pilot = ui.textual
        sidebar = await channel_roster(ui, "#team")
        item = await open_menu_item(ui, sidebar, "#team", ACTION)
        assert "Show member activity" in item.render().plain
        await pilot.click(item)
        await ui.step()
        sidebar = await channel_roster(ui, "#team")
        item = await open_menu_item(ui, sidebar, "#team", ACTION)
        assert "Show channel only" in item.render().plain


async def test_the_all_feed_has_no_member_activity_toggle(workspace):
    workspace.thread("alice", "team")
    async with workspace.app(size=(100, 30)) as ui:
        sidebar = await channel_roster(ui, "#team")
        from toad.widgets.comms_menu import ContextMenuItem
        from toad.widgets.comms_sidebar import ChannelGroup
        app, pilot = ui.textual
        group = next(row for row in sidebar.query(ChannelGroup) if row.row.target_name == "#any")
        await pilot.click(group.row, button=3)
        await ui.until(lambda: app.screen.query(ContextMenuItem), why="the menu of #any")
        assert all(item.action != ACTION for item in app.screen.query(ContextMenuItem))
        await ui.press("escape")
