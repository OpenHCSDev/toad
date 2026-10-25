"""An already-open channel tab paints each new sidebar observation."""

from toad.widgets.session_tabs import SessionLabel, SessionsTabs


async def test_open_channel_tab_tracks_unread_without_switching(workspace):
    workspace.thread("peer", "team")
    comms = workspace.comms
    for index in range(12):
        comms.messaging.send("peer", "#team", f"message {index}\n" + "body\n" * 80)

    async with workspace.app(size=(100, 30)) as ui:
        app, _ = ui.textual
        await ui.open_channel("#team", actor="peer")
        selected = ui.selected_tab
        tabs = app.screen.query_one(SessionsTabs)
        label = tabs.query_one(f"#{selected}", SessionLabel)

        def unread():
            observed = app.coordination_access.observation.observed()
            return observed.sidebar.observation.channel_unread("#team")

        await ui.until(
            lambda: bool(unread().label) and unread().label in label.content.plain,
            why="the open tab showing unread messages outside its viewport",
        )
        before = label.content.plain
        comms.views.mark_user_view_read("#team", worktree=str(workspace.project))
        await ui.until(
            lambda: not unread().label and label.content.plain == "#team",
            why="the same tab repainting the sidebar's zero-unread observation",
        )
        assert ui.selected_tab == selected
        assert label.content.plain != before
