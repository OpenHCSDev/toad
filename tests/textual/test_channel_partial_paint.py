"""Textual-facing: read marks follow the message text the viewport has painted; scrolling the window reveals the rest."""

from agent_comms.read_basis import ChannelConversation
from support.textual_steps import text_rows_of


async def test_partial_viewport_marks_only_painted_text_and_scrolling_marks_the_remaining_messages(workspace):
    from toad.widgets.comms_chat import CommsChatView
    from toad.message_rows import IrcMessageStyle, MarkdownMessageStyle

    workspace.thread("peer", "team", running=True)
    comms = workspace.comms
    viewer = workspace.viewer
    rows = [comms.messaging.send("peer", "#team", f"row {i}\n" + "body\n" * 10).message for i in range(8)]

    ledger = comms.bus.reads
    snapshot = comms.registry.snapshot()
    channel = ChannelConversation("#team")

    async with workspace.app(size=(90, 24)) as ui:
        app = ui.textual[0]
        await ui.open_channel("#team", actor=viewer)
        chat = app.screen.query_one(CommsChatView)
        history, window = chat.message_history, chat.window
        await ui.until(lambda: any(row.seq in ledger.cursor(
            viewer, snapshot).for_conversation(channel) for row in rows),
            why="the first viewport to be marked")
        await history._read_worker.wait()
        in_view = {fragment.message.seq for fragment in history.read_fragments()}
        assert 0 < len(in_view) < len(rows)
        cursor = ledger.cursor(viewer, snapshot).for_conversation(channel)
        assert all((message.seq in cursor) == (message.seq in in_view) for message in rows)
        # Messages beyond the first viewport stay unread until their text is scrolled to.
        for message in reversed(rows):
            if message.seq in ledger.cursor(viewer, snapshot).for_conversation(channel):
                continue
            if text_rows_of(chat, message) is None:
                # Earlier messages are laid out as the reader nears them.
                window.scroll_to(y=0, animate=False, immediate=True)
                await ui.until(lambda: text_rows_of(chat, message) is not None, why=f"row {message.seq} laid out")
            window.scroll_to(y=text_rows_of(chat, message).start, animate=False, immediate=True)
            await ui.until(lambda: message.seq in ledger.cursor(
                viewer, snapshot).for_conversation(channel),
                why=f"row {message.seq} to be marked once scrolled to")
        cursor = ledger.cursor(viewer, snapshot).for_conversation(channel)
        assert all(row.seq in cursor for row in rows)
        # A wholly read history has nothing left to mark: no further worker or route read.
        await history._read_worker.wait()
        assert all(fragment.evidence is None for fragment in history.wire_fragments)
        completed = history._read_worker
        for _ in range(50):
            history.mark_visible()
            assert history._read_worker is completed
        recorded = tuple(message.view_key for message in history.messages)
        await ui.press("ctrl+t")
        await ui.until(lambda: isinstance(history.style, MarkdownMessageStyle), why="the Markdown style")
        assert ui.shows("row 7")
        await ui.press("ctrl+t")
        await ui.until(lambda: isinstance(history.style, IrcMessageStyle), why="the IRC style")
        assert tuple(message.view_key for message in history.messages) == recorded
        cursor = ledger.cursor(viewer, snapshot).for_conversation(channel)
        assert all(row.seq in cursor for row in rows)
