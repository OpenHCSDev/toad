"""A displayed channel page clears its own unread rows after every navigation."""


def unread_badge_gone(ui, identity):
    return "(1)" not in next(tab.title for tab in ui.tabs() if tab.identity == identity)


async def test_channel_unread_clears_on_opening_and_on_return_to_the_open_tab(workspace):
    workspace.thread("sender")
    comms = workspace.comms
    comms.messaging.send("sender", "#all", "first-pending")

    def unread() -> int:
        return comms.views.viewer_snapshot(str(workspace.project)).channel_unread["#all"]

    assert unread() == 1
    async with workspace.app(size=(110, 36)) as ui:
        owner = ui.selected_tab
        channel = await ui.open_channel("#all", actor=workspace.viewer)
        await ui.until_shows("first-pending", seconds=5)
        await ui.until(lambda: unread() == 0, seconds=5, why="the channel to be read")
        await ui.until(lambda: unread_badge_gone(ui, channel), seconds=5, why="the unread badge to clear")

        await ui.select_tab(owner)
        comms.messaging.send("sender", "#all", "second-pending")
        assert unread() == 1
        await ui.select_tab(channel)
        await ui.until_shows("second-pending", seconds=5)
        await ui.until(lambda: unread() == 0, seconds=5, why="the returned channel to be read")
        await ui.until(lambda: unread_badge_gone(ui, channel), seconds=5, why="the unread badge to clear on return")


async def test_direct_message_unread_clears_on_opening(workspace):
    workspace.thread("sender")
    comms = workspace.comms

    def unread() -> int:
        return comms.views.viewer_snapshot(str(workspace.project)).unread.get("sender", 0)

    async with workspace.app(size=(110, 36)) as ui:
        owner = ui.selected_tab
        comms.messaging.send("sender", workspace.viewer, "dm-pending")
        assert unread() == 1
        direct = await ui.open_direct("sender", actor=workspace.viewer, owner=owner)
        await ui.until_shows("dm-pending", seconds=5)
        await ui.until(lambda: unread() == 0, seconds=5, why="the direct messages to be read")
        await ui.until(lambda: unread_badge_gone(ui, direct), seconds=5, why="the unread badge to clear")


async def test_aggregate_feed_unread_clears_on_opening(workspace):
    workspace.thread("sender")
    comms = workspace.comms

    def unread() -> int:
        return comms.views.viewer_snapshot(str(workspace.project)).channel_unread.get("#any", 0)

    async with workspace.app(size=(110, 36)) as ui:
        owner = ui.selected_tab
        comms.messaging.send("sender", "#all", "aggregate-pending")
        assert unread() >= 1
        feed = await ui.open_channel("#any", actor=workspace.viewer, owner=owner)
        await ui.until_shows("aggregate-pending", seconds=5)
        await ui.until(lambda: unread() == 0, seconds=5, why="the feed to be read")
        await ui.until(lambda: unread_badge_gone(ui, feed), seconds=5, why="the unread badge to clear")
