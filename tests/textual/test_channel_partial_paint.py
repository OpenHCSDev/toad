"""Textual-facing: read marks follow the message bodies the viewport has painted; scrolling widgets reveals the rest."""

from unittest.mock import patch


async def test_partial_viewport_marks_only_painted_bodies_and_scrolling_marks_the_remaining_rows(workspace):
    from toad.mounted_message_history import IrcMessageStyle, MarkdownMessageStyle, MountedMessageHistory
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.irc_message import IRCMessageText

    workspace.thread("peer", "team", running=True)
    comms = workspace.comms
    viewer = workspace.viewer
    rows = [comms.messaging.send_message("peer", "#team", f"row {i}\n" + "body\n" * 10) for i in range(8)]
    marked = set()
    original_mark = MountedMessageHistory.mark_page

    def seen():
        return comms.bus.reads.seen_sequences(viewer, comms.registry.snapshot())

    async def checked_mark(chat, page, original_page, *, snapshot):
        selected = {message.seq for message in page.messages}
        assert selected <= {seq for source, seq in chat.painted_keys() if not source}
        assert page.display_scope is not None and page.display_scope.displayed is not None
        assert selected == {seq for item in page.display_scope.displayed.conversations for seq in item.sequences}
        marked.update(selected)
        await original_mark(chat, page, original_page, snapshot=snapshot)

    with patch.object(MountedMessageHistory, "mark_page", checked_mark):
        async with workspace.app(size=(90, 24)) as ui:
            app = ui.textual[0]
            await ui.open_channel("#team", actor=viewer)
            chat = app.screen.query_one(CommsChatView)
            await ui.until(lambda: marked and not chat.message_history.ack_inflight, why="the first viewport to be marked")
            assert 0 < len(seen()) < len(rows)
            assert seen() == marked
            # Revisit every mounted body. Rows beyond the first viewport stay pending
            # even though the first subset has already been marked.
            for message, widget in list(chat.message_history.rows):
                if message.seq in seen():
                    continue
                body = widget.read_ack_widget()
                if body is None:
                    # The viewport prepares a body once its row is exposed; waiting on an
                    # offscreen row first would depend on eager preparation.
                    widget.scroll_visible(animate=False, immediate=True)
                    await widget.query_one(IRCMessageText).wait_ready()
                    body = widget.read_ack_widget()
                    assert body is not None
                chat.window.scroll_to(y=chat.window.scroll_y + body.region.y - chat.window.content_region.y,
                                      animate=False, immediate=True)
                await ui.until(lambda: message.seq in seen(), why=f"row {message.seq} to be marked once scrolled to")
            assert seen() == {row.seq for row in rows}
            # Scrolling a marked page has nothing left to publish: no further worker or route read.
            history = chat.message_history
            await ui.until(lambda: not history.ack_inflight, why="marking to settle")
            assert not history.channel_receipts and not history.historical_receipts
            assert history.tail_receipt is None
            for _ in range(50):
                history.mark_visible()
                assert not history.ack_inflight
            recorded = tuple(message.view_key for message, _ in history.rows)
            await ui.press("ctrl+t")
            await ui.until(lambda: isinstance(history.style, MarkdownMessageStyle), why="the Markdown style")
            assert ui.shows("row 7")
            await ui.press("ctrl+t")
            await ui.until(lambda: isinstance(history.style, IrcMessageStyle), why="the IRC style")
            assert tuple(message.view_key for message, _ in history.rows) == recorded
            assert seen() == {row.seq for row in rows}
