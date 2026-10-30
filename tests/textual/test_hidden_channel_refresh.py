"""A hidden channel leaves its history unchanged; returning fetches current data."""

from support.textual_steps import refresh_chat


async def test_hidden_channel_refresh_leaves_history_unchanged_and_resumed_window_fetches_current_message(workspace):
    from toad.widgets.comms_chat import CommsChatView

    workspace.thread("peer", "one", "two")
    comms = workspace.comms
    comms.messaging.send("peer", "#one", "FIRST")
    comms.messaging.send("peer", "#two", "SECOND")
    async with workspace.app(size=(100, 35)) as ui:
        app = ui.textual[0]
        first = await ui.open_channel("#one", actor="peer")
        chat = app.screen.query_one(CommsChatView)
        history = chat.message_history
        await ui.until(lambda: not history.undrawn and history.state.accepts_source_work, why="the first channel's history read")
        await ui.open_channel("#two", actor="peer")
        # Let the hidden reader settle before the next message arrives.
        await ui.until(lambda: history.state.accepts_source_work and not history.marking,
                       why="the hidden channel to settle")
        comms.messaging.send("peer", "#one", "ARRIVED-WHILE-HIDDEN")
        for _ in range(40):
            await refresh_chat(chat)
        assert not any(m.body == "ARRIVED-WHILE-HIDDEN" for m in history.messages)
        await ui.select_tab(first)
        await ui.until(lambda: any(m.body == "ARRIVED-WHILE-HIDDEN" for m in history.messages),
                       why="the resumed channel to fetch the current message")
        # The history holds the message before layout has measured its rows; the next layout draws it.
        await ui.until(lambda: ui.shows("ARRIVED-WHILE-HIDDEN"), why="the fetched message drawn")
