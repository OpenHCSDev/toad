"""Textual-facing: read marks follow the message text the viewport has painted; scrolling the window reveals the rest."""

from agent_comms.read_basis import ChannelConversation


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
        await history.read_worker.wait()
        in_view = {fragment.message.seq for fragment in history.read_fragments()}
        assert 0 < len(in_view) < len(rows)
        cursor = ledger.cursor(viewer, snapshot).for_conversation(channel)
        assert all((message.seq in cursor) == (message.seq in in_view) for message in rows)
        # Address each original message through the history's own source
        # fragments; revealing its head prepares virtualized rows on demand.
        for message in reversed(rows):
            if message.seq in ledger.cursor(viewer, snapshot).for_conversation(channel):
                continue
            fragment = next(part for part in history.fragments
                            if part.message.view_key == message.view_key)
            for _ in rows:
                if history.draws_fragment(fragment):
                    break
                window.scroll_page_up(animate=False)
                await ui.step()
                await ui.until(lambda: window.reader_position.laid_out(window),
                               why="the scrolled viewport to finish layout")
            await history.reveal_message_head(fragment, lambda: True)
            history.show_fragment(fragment)
            await ui.until(lambda: message.seq in ledger.cursor(
                viewer, snapshot).for_conversation(channel),
                why=f"row {message.seq} to be marked once scrolled to")
        cursor = ledger.cursor(viewer, snapshot).for_conversation(channel)
        assert all(row.seq in cursor for row in rows)
        # A wholly read history has nothing left to mark: no further worker or route read.
        await history.read_worker.wait()
        assert all(fragment.evidence is None for fragment in history.fragments)
        completed = history.read_worker
        for _ in range(50):
            history.mark_visible()
            assert history.read_worker is completed
        window.scroll_end(animate=False, immediate=True)
        await ui.until(lambda: ui.shows("row 7"), why="the newest row after returning to the bottom")
        recorded = tuple(fragment.message.view_key for fragment in history.fragments)
        await ui.press("ctrl+t")
        await ui.until(lambda: isinstance(history.page_source.loader.style, MarkdownMessageStyle), why="the Markdown style")
        assert ui.shows("row 7")
        await ui.press("ctrl+t")
        await ui.until(lambda: isinstance(history.page_source.loader.style, IrcMessageStyle), why="the IRC style")
        assert tuple(fragment.message.view_key for fragment in history.fragments) == recorded
        cursor = ledger.cursor(viewer, snapshot).for_conversation(channel)
        assert all(row.seq in cursor for row in rows)
