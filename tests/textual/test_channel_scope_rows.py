"""Textual-facing: a mounted any-mode channel's message rows (widgets of the chat view) follow its scope."""

from support.textual_steps import refresh_chat


async def test_any_mode_channel_rows_include_older_messages_after_a_refresh(workspace):
    from toad.widgets.comms_chat import CommsChatView

    for name, tags in (("alice", ("team",)), ("bob", ()), ("carol", ()), ("dave", ())):
        workspace.thread(name, *tags, running=True)
    comms = workspace.comms
    project = str(workspace.project)
    comms.messaging.send("carol", "dave", "older newly visible DM")
    comms.messaging.send("alice", "#team", "current channel message")
    comms.channels.set_channel_any_mode("#team", True)
    assert [m.body for m in comms.views.channel_display_page("#team", worktree=project).messages] == [
        "current channel message"]

    async with workspace.app(size=(100, 30)) as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        chat = ui.textual[0].screen.query_one(CommsChatView)
        await refresh_chat(chat)
        await ui.step()
        assert [m.body for m in chat.message_history.messages] == ["current channel message"]
        assert not chat.message_history.has_older

        comms.channels.update_tags("carol", add=frozenset({"team"}))
        expanded = comms.views.channel_display_page("#team", worktree=project)
        assert [m.body for m in expanded.messages][:2] == ["older newly visible DM", "current channel message"]
        await refresh_chat(chat)
        await ui.step()
        assert [m.body for m in chat.message_history.messages][:2] == [
            "older newly visible DM", "current channel message"]
