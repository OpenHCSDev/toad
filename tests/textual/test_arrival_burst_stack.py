"""A burst of arrivals: the window shows the latest, and its pin stacks the others' headers.

Tristan, 2026-11-18: "when there's a lot of messages that come in at once, maybe we should
show the headers for all of them, like stacked, and then scroll up and show the most recent
one. So it'd be like, three came in, here's the latest." Qt's `arrival` drive (BURST=5)
checks the same state on the phone's layout; this is the terminal's.
"""

import os
from pathlib import Path

from support.textual_steps import refresh_chat
from toad.widgets.comms_chat import CommsChatView

BURST = 5


async def test_a_burst_stacks_the_earlier_headers_and_a_click_opens_one(workspace, tmp_path):
    workspace.thread("sender", "burst", running=True)
    comms = workspace.comms
    for index in range(30):
        comms.messaging.send("sender", "#burst", f"Message {index}: " + "earlier body " * 6)
    shots = Path(os.environ.get("BURST_SHOTS", tmp_path))
    async with workspace.app(size=(80, 30)) as ui:
        app, pilot = ui.textual
        await ui.open_channel("#burst", actor="sender")
        chat = app.screen.query_one(CommsChatView)
        history, window = chat.message_history, chat.window
        await ui.until(lambda: history.state.accepts_source_work, why="the channel's messages")
        await ui.until(lambda: window.follows_tail, why="the reader on the tail")

        # Messages a third of the window tall, all at once: the earlier heads leave the top row.
        for index in range(BURST):
            comms.messaging.send("sender", "#burst", f"BURST {index}\n" + "\n".join(
                f"line {row} of burst message {index}" for row in range(8)))
        await refresh_chat(chat)
        await ui.until_shows(f"BURST {BURST - 1}")
        pin = window.sticky_header
        await ui.until(lambda: pin.stacked.keys, why="the burst's earlier headers stacked", seconds=15)
        app.save_screenshot("burst-stack.svg", str(shots))

        burst = window.arrival_burst.messages
        assert len(burst) == BURST, [message.header.label for message in burst]
        above = [message for message in burst[:-1] if window.message_top(message.key) < window.scroll_y]
        assert above, "every burst head is on screen"
        lines = pin.prepared_lines(pin.size.width)
        assert pin.display and pin.headers[0].label == f"{BURST} new", pin.headers[:1]
        assert [header.label for header in pin.stacked.headers[1:]] == [
            message.header.label for message in above[-type(window.arrival_burst).shown:]]
        latest = window.message_top(burst[-1].key)
        assert latest is not None and latest < window.scroll_y + window.scrollable_content_region.height, \
            "the latest message is not on screen"

        # A click on the first stacked header opens its message: its head on the top row.
        chosen = pin.stacked.keys[1]
        first = lines.block_span(lambda span: span.index == 1).first
        await pilot.click(pin, offset=(2, first))
        await ui.until(lambda: window.message_top(chosen) == window.scroll_y,
                       why="the clicked message's head on the top row")
        await pilot.pause()
        app.save_screenshot("burst-opened.svg", str(shots))
        assert not window.arrival_burst.messages and not pin.stacked.keys
        assert not window.follows_tail
