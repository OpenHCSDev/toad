"""Textual-facing: the mounted channel history asks the window's lookahead to read older pages before its edge needs them."""

from unittest.mock import patch

from toad.widgets.comms_chat import CommsChatView


async def test_a_channel_reads_the_next_older_page_before_scrolling_reaches_its_edge(workspace):
    workspace.thread("sender", "scroll", running=True)
    for index in range(200):
        workspace.comms.messaging.send("sender", "#scroll", f"Message {index}: " + "wrapped body " * 6)
    async with workspace.app(size=(145, 50)) as ui:
        app, _pilot = ui.textual
        views = app.coordination_access.service.views
        older_reads = []
        original = views.channel_display_page

        def counted(target, **bounds):
            if bounds.get("before") is not None:
                older_reads.append(bounds["limit"])
            return original(target, **bounds)

        with patch.object(views, "channel_display_page", side_effect=counted):
            await ui.open_channel("#scroll", actor="sender")
            chat = app.screen.query_one(CommsChatView)
            history = chat.message_history
            await ui.until(lambda: history.rows, why="channel rows")
            assert history.reader.source.comms.views is views
            page_limit = history.reader.source.page_limit
            # The first older rows are a few taken from a whole transport page, and the next page is read ahead.
            await ui.until(lambda: len(history.rows) > 8 and len(older_reads) >= 2, why="older rows and a page read ahead")
            assert set(older_reads) == {page_limit}, older_reads
            oldest, reads = history.rows[0][0].seq, len(older_reads)
            chat.window.focus()
            for _ in range(6):
                await ui.press("pageup")
            await ui.until(lambda: history.rows[0][0].seq <= oldest - 24, why="six more admissions of older rows")
            # Six admissions of four rows did not cost six Core reads.
            assert len(older_reads) - reads <= 3 and set(older_reads) == {page_limit}, older_reads
