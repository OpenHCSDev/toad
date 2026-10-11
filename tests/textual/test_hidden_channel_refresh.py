"""Textual-facing: a hidden channel view's refresh callback (a widget lifecycle) reads nothing; the shown one fetches current data."""

from unittest.mock import patch

from support.textual_steps import refresh_chat


async def test_hidden_channel_refresh_does_no_root_check_and_resumed_window_fetches_current_message(workspace):
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
        await ui.until(lambda: history.reader is not None and not history.reader.source.loading
                       and history.state.accepts_source_work, why="the first channel's history read")
        await ui.open_channel("#two", actor="peer")
        # Mark the current page loaded before instrumenting the hidden reader.
        await ui.until(lambda: history.state.accepts_source_work and not history.ack_inflight,
                       why="the hidden channel to settle")
        comms.messaging.send("peer", "#one", "ARRIVED-WHILE-HIDDEN")
        with patch("agent_comms.route_selection.root_is_current", side_effect=AssertionError("hidden route check")):
            # Exercise the real hidden callback, not a mocked visibility test.
            for _ in range(40):
                await refresh_chat(chat)
            assert not any(m.body == "ARRIVED-WHILE-HIDDEN" for m, _ in history.rows)
        await ui.select_tab(first)
        await ui.until(lambda: any(m.body == "ARRIVED-WHILE-HIDDEN" for m, _ in history.rows),
                       why="the resumed channel to fetch the current message")
        assert ui.shows("ARRIVED-WHILE-HIDDEN")
    assert not history.reader._pending
