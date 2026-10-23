"""A declared destination opens through the real app's mounted sidebar row."""

from toad.navigation_target import NavigationTarget
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar


async def test_new_destination_uses_existing_row(workspace):
    opened = []

    class TestReportTarget(NavigationTarget):
        async def open(self, context):
            opened.append(context)
            return context.owner_mode

    workspace.thread("row-peer", "team")
    async with workspace.app() as ui:
        app, pilot = ui.textual
        sidebar = app.workspace_chrome.channels
        if sidebar.collapsed:
            sidebar.toggle()
        tree = sidebar.query_one(CommsSidebar)
        await ui.until(
            lambda: "#team" in tree.groups, why="the real sidebar's channel group"
        )
        group = tree.groups["#team"]
        absent = app.workspace_sessions.visible_target(None)
        assert not absent.matches(app.selected_session.navigation_target)
        assert absent.rows_in(group) == ()
        if not group.expanded:
            group.toggle_members()
        row = CommsRow(TestReportTarget("report"), "Open report")
        await group.member_container.mount(row)
        row.scroll_visible(animate=False)
        await ui.step()
        context = app.selected_session.navigation_context
        assert await pilot.click(row)
        await ui.until(
            lambda: bool(opened), why="the row opening its declared destination"
        )
        assert opened == [context]
