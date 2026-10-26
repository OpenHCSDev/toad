"""Textual-facing: the channel row's context menu (a modal screen opened by a right click) toggles member activity."""

from agent_comms.repo import Checkout
from agent_comms.ui_model.unread import ExactUnread
from support.textual_steps import channel_roster


ACTION = "channel-activity"


def bodies(comms):
    return [message.body for message in comms.views.channel_display_page("#team").messages]


async def open_menu(ui, sidebar, channel):
    from toad.widgets.comms_sidebar import ChannelGroup

    _, pilot = ui.textual
    group = next(row for row in sidebar.query(ChannelGroup) if row.row.target_name == channel)
    await pilot.click(group.row, button=3)
    return await ui.menu(f"the menu of {channel}")


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
        app, _ = ui.textual
        owner = ui.selected_tab
        sidebar = await channel_roster(ui, "#team")
        assert ACTION in await open_menu(ui, sidebar, "#team")
        await ui.choose_menu_action(ACTION)
        await ui.step()
        assert comms.bus.require_channel("#team").any_mode
        assert bodies(comms) == ["exact route", "outbound from member", "inbound to member"]
        assert comms.views.viewer_snapshot(Checkout(workspace.project)).channel_unread["#team"] == ExactUnread(count=3)

        await ui.open_channel("#team", actor="alice")
        await ui.until_shows("inbound to member")
        assert ui.shows("outbound from member") and ui.shows("exact route")
        await ui.select_tab(owner)
        sidebar = app.screen.query_one(CommsSidebar)

        assert ACTION in await open_menu(ui, sidebar, "#team")
        await ui.choose_menu_action(ACTION)
        await ui.step()
        assert not comms.bus.require_channel("#team").any_mode
        assert bodies(comms) == ["exact route"]


async def test_the_menu_item_carries_cores_label_before_and_after_the_toggle(workspace):
    workspace.thread("alice", "team")
    workspace.comms.messaging.send("alice", "#team", "exact route")
    async with workspace.app(size=(100, 30)) as ui:
        sidebar = await channel_roster(ui, "#team")
        assert "Toggle member activity" in (await open_menu(ui, sidebar, "#team"))[ACTION]  # Core's own label for the command
        await ui.choose_menu_action(ACTION)
        await ui.step()
        sidebar = await channel_roster(ui, "#team")
        assert "Toggle member activity" in (await open_menu(ui, sidebar, "#team"))[ACTION]


async def test_the_all_feed_has_no_member_activity_toggle(workspace):
    workspace.thread("alice", "team")
    async with workspace.app(size=(100, 30)) as ui:
        sidebar = await channel_roster(ui, "#team")
        assert ACTION not in await open_menu(ui, sidebar, "#any")
        await ui.press("escape")
