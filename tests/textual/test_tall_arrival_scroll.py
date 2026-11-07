"""A tall channel arrival does not park a following reader at its bottom.

Written to reproduce Tristan's report that a large message "comes in in one shot and it
scrolls to the bottom of the message". It does not: this path behaves, which is why it is
kept as the guard for that, and his case is the session conversation's own history rather
than a channel's.
"""

from support.textual_steps import refresh_chat
from toad.frame_presentation import ARRIVAL
from toad.widgets.comms_chat import CommsChatView


async def tailing_channel(workspace, ui):
    app, _pilot = ui.textual
    await ui.open_channel("#tall", actor="sender")
    chat = app.screen.query_one(CommsChatView)
    history = chat.message_history
    await ui.until(lambda: history.state.accepts_source_work, why="the channel's messages")
    return chat, history, chat.window


async def test_a_tall_arrival_does_not_land_a_following_reader_at_its_bottom(workspace):
    workspace.thread("sender", "tall", running=True)
    comms = workspace.comms
    for index in range(40):
        comms.messaging.send("sender", "#tall", f"Message {index}: " + "wrapped body " * 10)
    async with workspace.app(size=(110, 35)) as ui:
        chat, history, window = await tailing_channel(workspace, ui)
        await ui.until(lambda: window.follows_tail, why="the reader on the tail")
        viewport = window.scrollable_content_region.height

        # One message taller than the viewport, arriving in one shot.
        comms.messaging.send("sender", "#tall", "TALL ARRIVAL\n" + "\n".join(
            f"row {row} of a message taller than the window" for row in range(viewport + 12)))
        await refresh_chat(chat)
        await ui.until_shows("TALL ARRIVAL")

        # The reader reads the arrival rather than sitting below all of it. The state is in
        # the message because a print here is swallowed: the app owns the terminal.
        assert window.scroll_y < window.max_scroll_y, (
            f"parked at the bottom of a message taller than the window: scroll_y="
            f"{window.scroll_y} max_scroll_y={window.max_scroll_y} viewport={viewport} "
            f"unrevealed={history.unrevealed_rows()} "
            f"phase={type(history.effect_phase(ARRIVAL)).__name__} "
            f"reader={type(window.reader_position).__name__}")
