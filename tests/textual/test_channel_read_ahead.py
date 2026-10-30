"""Textual-facing: scrolling consumes prepared pages on the original channel reading."""

from toad.widgets.comms_chat import CommsChatView


async def test_a_channel_reads_the_next_older_page_before_scrolling_reaches_its_edge(workspace):
    workspace.thread("sender", "scroll", running=True)
    for index in range(200):
        workspace.comms.messaging.send("sender", "#scroll", f"Message {index}: " + "wrapped body " * 6)
    async with workspace.app(size=(145, 50)) as ui:
        app, _pilot = ui.textual
        await ui.open_channel("#scroll", actor="sender")
        chat = app.screen.query_one(CommsChatView)
        history = chat.message_history
        await ui.until(lambda: history.fragments, why="channel messages")
        source = history.page_source.loader
        assert source.comms.views is app.coordination_access.service.views
        # Earlier pages are prepared before the reader starts scrolling.
        await ui.until(lambda: len(history.fragments) > source.tail_limit
                       and history.state.accepts_source_work, why="earlier messages prepared")
        scope = history.page_source.scope
        reading = scope.reading
        oldest = history.fragments[0].message.seq
        hits = app.preparation.hits
        chat.window.focus()
        for _ in range(6):
            await ui.press("pageup")
        await ui.until(lambda: history.fragments[0].message.seq <= oldest - 24,
                       why="earlier messages drawn while paging up")
        assert history.page_source.scope is scope and scope.reading is reading
        assert not scope.closed
        assert app.preparation.hits > hits
