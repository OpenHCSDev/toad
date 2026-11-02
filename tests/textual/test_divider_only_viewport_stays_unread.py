"""Textual-facing: whether a channel message counts as read depends on which rows Textual painted, and a divider painted without its text is not enough."""

import asyncio

from agent_comms.repo import Checkout
from agent_comms.ui_model.unread import ExactUnread

from support.textual_steps import text_rows_of
from toad.widgets.comms_chat import CommsChatView


async def test_divider_without_body_leaves_the_message_unread(workspace):
    workspace.thread("peer", "team")
    comms = workspace.comms
    project = Checkout(workspace.project)
    for index in range(7):
        comms.messaging.send("peer", "#team", f"earlier {index} " + "body " * 20)
    comms.views.mark_user_view_read("#team", worktree=project)

    async with workspace.app(size=(80, 22)) as ui:
        app, _ = ui.textual
        await ui.open_channel("#team", actor="peer")
        chat = app.screen.query_one(CommsChatView)
        history, window = chat.message_history, chat.window
        # The initial source must have committed scrollable rows before moving
        # the reader; opening the tab alone does not establish that state.
        await ui.until(lambda: history.state.accepts_source_work and window.max_scroll_y > 0
                       and window.reader_position.laid_out(window), why="the initial scrollable history")
        # Move away from the tail before the new message exists. Its text must
        # never paint during setup; no patched read-marker can hide a mistake.
        window.release_anchor()
        window.scroll_home(animate=False, immediate=True)
        await ui.step()
        assert not window.follows_tail
        last = comms.messaging.send("peer", "#team", "LAST " + "body " * 250).message
        # Offscreen rows are deliberately lazy. Approach through the viewport's
        # real input route until lookahead prepares the new message, stopping
        # before its body can paint or supply a read mark.
        async with asyncio.timeout(5):
            while text_rows_of(chat, last) is None:
                window.action_scroll_down()
                await ui.step()
                assert not ui.shows("LAST"), "Setup scrolled past the unread caption"
        assert not ui.shows("LAST")

        # Its caption is above its text: place that caption at the viewport's
        # last row. Paging can change the layout, so follow the committed rows.
        def caption_is_last_row():
            rows = text_rows_of(chat, last)
            return (history.state.accepts_source_work and rows is not None
                    and rows.start - window.scroll_y == window.outer_size.height)

        for _ in range(10):
            await ui.until(lambda: history.state.accepts_source_work and text_rows_of(chat, last) is not None,
                           why="the history idle")
            await ui.step(.2)
            if caption_is_last_row():
                break
            window.scroll_to(y=text_rows_of(chat, last).start - window.outer_size.height,
                             animate=False, immediate=True)
            await ui.step()
        assert caption_is_last_row()
        assert not ui.shows("LAST")
        assert any(fragment.message.seq == last.seq for fragment in history.visible_fragments())
        assert all(fragment.message.seq != last.seq for fragment in history.read_fragments())

        history.mark_visible()
        if (worker := history._read_worker) is not None:
            await worker.wait()
        await ui.step(.2)
        assert comms.views.viewer_snapshot(project).channel_unread["#team"] == ExactUnread(count=1)
