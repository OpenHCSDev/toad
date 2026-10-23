"""Textual-facing: a mounted any-mode channel's message rows (widgets of the chat view) follow its scope."""

from support.textual_steps import refresh_chat
from toad.widgets.presentation_window import OLDER_END


async def test_any_mode_channel_rows_include_older_messages_after_a_refresh(workspace):
    from toad.widgets.comms_chat import CommsChatView

    for name, tags in (("alice", ("team",)), ("bob", ()), ("carol", ()), ("dave", ())):
        workspace.thread(name, *tags, running=True)
    comms = workspace.comms
    project = str(workspace.project)
    comms.messaging.send("carol", "dave", "older newly visible DM")
    comms.messaging.send("alice", "#team", "current channel message")
    comms.channels.set_channel_any_mode("#team", True)
    assert [m.body for m in comms.views.channel_display_page("#team", viewer=comms.views.display_viewer(project)).messages] == [
        "current channel message"]

    async with workspace.app(size=(100, 30)) as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        chat = ui.textual[0].screen.query_one(CommsChatView)
        await refresh_chat(chat)
        await ui.step()
        assert [fragment.message.body for fragment in chat.message_history.fragments_in_range] == ["current channel message"]
        assert not chat.message_history.has_more(OLDER_END)

        await ui.until(lambda: chat.message_history.source_ready, why="the channel read to finish")
        await ui.app.coordination_access.stop_observing()
        history = chat.message_history
        source, snapshot = history.page_source, history.source_snapshot()
        marked = comms.views.channel_display_page("#team", viewer=comms.views.display_viewer(project))
        comms.channels.update_tags("carol", add=frozenset({"team"}))
        expanded = comms.views.channel_display_page("#team", viewer=comms.views.display_viewer(project))
        assert [m.body for m in expanded.messages][:2] == ["older newly visible DM", "current channel message"]
        await history._mark_page(marked, (), snapshot)
        await ui.until(lambda: history.page_source is not source,
                       why="stale read evidence to replace its source without clearing the drawn history")
        await ui.until(lambda: source.closed and history.source_ready,
                       why="the replaced source to retire after its old views")
        assert source.closed
        await ui.step()
        assert [fragment.message.body for fragment in chat.message_history.fragments_in_range][:2] == [
            "older newly visible DM", "current channel message"]
