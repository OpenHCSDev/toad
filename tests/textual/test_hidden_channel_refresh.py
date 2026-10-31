"""A hidden channel does no route check; returning fetches current data."""

from unittest.mock import patch

from agent_comms.route_selection import RouteSelection
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
        await ui.until(lambda: not history.undrawn and history.state.accepts_source_work, why="the first channel's history read")
        await ui.open_channel("#two", actor="peer")
        # Let the hidden reader settle before the next message arrives.
        await ui.until(lambda: history.state.accepts_source_work,
                       why="the hidden channel to settle")
        await history.read_worker.wait()
        comms.messaging.send("peer", "#one", "ARRIVED-WHILE-HIDDEN")
        with patch.object(RouteSelection, "root_is_current", side_effect=AssertionError("hidden route check")):
            for _ in range(40):
                await refresh_chat(chat)
            assert not any(fragment.message.body == "ARRIVED-WHILE-HIDDEN" for fragment in history.fragments)
        await ui.select_tab(first)
        await ui.until(lambda: any(fragment.message.body == "ARRIVED-WHILE-HIDDEN"
                                   for fragment in history.fragments),
                       why="the resumed channel to fetch the current message")
        # The history holds the message before layout has measured its rows; the next layout draws it.
        await ui.until(lambda: ui.shows("ARRIVED-WHILE-HIDDEN"), why="the fetched message drawn")
