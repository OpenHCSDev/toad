"""Textual-facing: the channel history reads earlier pages from Core before the reader's scrolling reaches its edge."""

from unittest.mock import patch

from toad.widgets.comms_chat import CommsChatView


async def test_a_channel_reads_the_next_older_page_before_scrolling_reaches_its_edge(workspace):
    workspace.thread("sender", "scroll", running=True)
    for index in range(200):
        workspace.comms.messaging.send("sender", "#scroll", f"Message {index}: " + "wrapped body " * 6)
    async with workspace.app(size=(145, 50)) as ui:
        app, _pilot = ui.textual
        views = app.coordination_access.service.views
        earlier_reads = []
        original = views.channel_display_page

        def counted(target, **bounds):
            if bounds.get("before") is not None:
                earlier_reads.append(bounds["limit"])
            return original(target, **bounds)

        with patch.object(views, "channel_display_page", side_effect=counted):
            await ui.open_channel("#scroll", actor="sender")
            chat = app.screen.query_one(CommsChatView)
            history = chat.message_history
            await ui.until(lambda: history.messages, why="channel messages")
            source = history.source
            assert source.comms.views is views
            # The newest messages come as a short page drawn at once; every earlier read is a whole page.
            await ui.until(lambda: len(history.messages) > source.tail_limit and len(earlier_reads) >= 3
                           and history.state.accepts_source_work, why="earlier messages and a page read ahead")
            assert earlier_reads[0] == source.tail_limit and set(earlier_reads[1:]) == {source.page_limit}, earlier_reads
            oldest, reads = history.messages[0].seq, len(earlier_reads)
            chat.window.focus()
            for _ in range(6):
                await ui.press("pageup")
            await ui.until(lambda: history.messages[0].seq <= oldest - 24, why="earlier messages drawn while paging up")
            # Six pages of scrolling did not cost six Core reads.
            assert len(earlier_reads) - reads <= 3 and set(earlier_reads[1:]) == {source.page_limit}, earlier_reads
