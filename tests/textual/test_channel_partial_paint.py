"""Textual-facing: read marks follow the message text the viewport has painted; scrolling the window reveals the rest."""

from support.textual_steps import text_rows_of


async def test_partial_viewport_marks_only_painted_text_and_scrolling_marks_the_remaining_messages(workspace):
    from toad.widgets.comms_chat import CommsChatView
    from toad.wire_history import IrcMessageStyle, MarkdownMessageStyle

    workspace.thread("peer", "team", running=True)
    comms = workspace.comms
    viewer = workspace.viewer
    rows = [comms.messaging.send_message("peer", "#team", f"row {i}\n" + "body\n" * 10) for i in range(8)]

    def seen():
        return comms.bus.reads.seen_sequences(viewer, comms.registry.snapshot())

    async with workspace.app(size=(90, 24)) as ui:
        app = ui.textual[0]
        await ui.open_channel("#team", actor=viewer)
        chat = app.screen.query_one(CommsChatView)
        history, window = chat.message_history, chat.window
        await ui.until(lambda: seen() and not history.marking, why="the first viewport to be marked")
        in_view = {fragment.message.seq for fragment in history.read_fragments()}
        assert 0 < len(seen()) < len(rows)
        assert seen() == in_view
        # Messages beyond the first viewport stay unread until their text is scrolled to.
        for message in reversed(rows):
            if message.seq in seen():
                continue
            if text_rows_of(chat, message) is None:
                # Earlier messages are laid out as the reader nears them.
                window.scroll_to(y=0, animate=False, immediate=True)
                await ui.until(lambda: text_rows_of(chat, message) is not None, why=f"row {message.seq} laid out")
            window.scroll_to(y=text_rows_of(chat, message).start, animate=False, immediate=True)
            await ui.until(lambda: message.seq in seen(), why=f"row {message.seq} to be marked once scrolled to")
        assert seen() == {row.seq for row in rows}
        # A wholly read history has nothing left to mark: no further worker or route read.
        await ui.until(lambda: not history.marking, why="marking to settle")
        assert all(fragment.evidence is None for fragment in history.wire_fragments)
        for _ in range(50):
            history.mark_visible()
            assert not history.marking
        recorded = tuple(message.view_key for message in history.messages)
        await ui.press("ctrl+t")
        await ui.until(lambda: isinstance(history.style, MarkdownMessageStyle), why="the Markdown style")
        assert ui.shows("row 7")
        await ui.press("ctrl+t")
        await ui.until(lambda: isinstance(history.style, IrcMessageStyle), why="the IRC style")
        assert tuple(message.view_key for message in history.messages) == recorded
        assert seen() == {row.seq for row in rows}
