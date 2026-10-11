"""Textual-facing: whether a channel message counts as read depends on which rows Textual painted, and a divider painted without its body is not enough."""

from unittest.mock import patch

from textual.geometry import Region

from toad.mounted_message_history import MountedMessageHistory
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.irc_message import IRCMessageText


async def test_divider_without_body_leaves_the_message_unread(workspace):
    workspace.thread("peer", "team")
    comms = workspace.comms
    project = str(workspace.project)
    for index in range(7):
        comms.messaging.send("peer", "#team", f"earlier {index} " + "body " * 20)
    comms.views.mark_user_view_read("#team", worktree=project)
    last = comms.messaging.send_message("peer", "#team", "LAST " + "body " * 250)

    # Hold automatic acknowledgements while arranging the divider-only viewport;
    # the initial tail paint may legitimately acknowledge the body.
    mark_visible = MountedMessageHistory.mark_visible
    with patch.object(MountedMessageHistory, "mark_visible"):
        async with workspace.app(size=(80, 22)) as ui:
            app, _ = ui.textual
            await ui.open_channel("#team", actor="peer")
            chat = app.screen.query_one(CommsChatView)
            history = chat.message_history
            await ui.until(lambda: history.reader is not None and not history.reader.source.loading,
                           seconds=5, why="the channel history to load")
            block = next(widget for message, widget in history.rows if message.seq == last.seq)
            body = block.query_one(IRCMessageText)
            await ui.step()
            caption = Region(block.region.x, block.region.y, block.region.width, 1)
            viewport = chat.window.content_region
            chat.window.scroll_to(y=chat.window.scroll_y + caption.bottom - viewport.bottom,
                                  animate=False, immediate=True)
            await ui.step()
            assert Region(block.region.x, block.region.y, block.region.width, 1).overlaps(chat.window.content_region)
            assert not body.region.overlaps(chat.window.content_region)
            assert last.seq not in {seq for source, seq in history.painted_keys() if not source}

            page = await history.reader.page(after=last.seq - 1, limit=history.reader.source.page_limit)
            history.channel_receipts[last.seq] = page
            mark_visible(history)
            await ui.step(.2)
            assert comms.views.viewer_snapshot(project).channel_unread["#team"] == 1
