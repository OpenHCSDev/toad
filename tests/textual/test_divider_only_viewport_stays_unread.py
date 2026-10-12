"""Textual-facing: whether a channel message counts as read depends on which rows Textual painted, and a divider painted without its text is not enough."""

from unittest.mock import patch

from support.textual_steps import text_rows_of
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.wire_history import WireHistory


async def test_divider_without_body_leaves_the_message_unread(workspace):
    workspace.thread("peer", "team")
    comms = workspace.comms
    project = str(workspace.project)
    for index in range(7):
        comms.messaging.send("peer", "#team", f"earlier {index} " + "body " * 20)
    comms.views.mark_user_view_read("#team", worktree=project)
    last = comms.messaging.send_message("peer", "#team", "LAST " + "body " * 250)

    # Hold read marks while arranging the divider-only viewport; the first
    # viewport shows the text and may legitimately mark it.
    mark_visible = WireHistory.mark_visible
    with patch.object(WireHistory, "mark_visible"):
        async with workspace.app(size=(80, 22)) as ui:
            app, _ = ui.textual
            await ui.open_channel("#team", actor="peer")
            chat = app.screen.query_one(CommsChatView)
            history, window = chat.message_history, chat.window
            await ui.until(lambda: text_rows_of(chat, last) is not None, seconds=5, why="the last message laid out")
            # Its caption is the row above its text: make that the last row in view.
            window.scroll_to(y=text_rows_of(chat, last).start - window.outer_size.height,
                             animate=False, immediate=True)
            await ui.step()
            assert not ui.shows("LAST")
            assert any(fragment.message.seq == last.seq for fragment in history.visible_fragments())
            assert all(fragment.message.seq != last.seq for fragment in history.read_fragments())

            mark_visible(history)
            await ui.until(lambda: not history.marking, why="marking to settle")
            await ui.step(.2)
            assert comms.views.viewer_snapshot(project).channel_unread["#team"] == 1
