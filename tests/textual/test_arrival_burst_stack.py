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


async def test_burst_stack_covers_visible_header_without_overlap(workspace, tmp_path):
    """When a burst message's header is the viewport's top row (pinned.headers empty),
    the overlay draws 'N new' + stacked earlier headers + that header as its last line,
    covering the flow's copy so no other header sits on top of it."""
    workspace.thread("sender", "bstack", running=True)
    comms = workspace.comms
    for index in range(10):
        comms.messaging.send("sender", "#bstack", f"fill {index}: " + "padding " * 6)
    shots = Path(os.environ.get("BURST_SHOTS", tmp_path))
    async with workspace.app(size=(80, 30)) as ui:
        app, pilot = ui.textual
        await ui.open_channel("#bstack", actor="sender")
        chat = app.screen.query_one(CommsChatView)
        history, window = chat.message_history, chat.window
        await ui.until(lambda: history.state.accepts_source_work, why="the channel's messages")
        await ui.until(lambda: window.follows_tail, why="the reader on the tail")

        for index in range(BURST):
            comms.messaging.send("sender", "#bstack", f"BURST {index}\n" + "\n".join(
                f"line {row} of burst message {index}" for row in range(8)))
        await refresh_chat(chat)
        await ui.until_shows(f"BURST {BURST - 1}")
        pin = window.sticky_header
        await ui.until(lambda: pin.stacked.keys, why="the burst stacked", seconds=15)

        burst = window.arrival_burst.messages
        assert len(burst) == BURST
        latest = burst[-1]
        top = window.message_top(latest.key)
        assert top is not None, "latest burst message on screen"

        # Put the latest message's first row (Gap) at the viewport top.
        # Its header divider is visible; pinned.headers is empty.
        with window.layout_scroll():
            window.scroll_y = top
        window.repin_header()
        await pilot.pause()
        app.save_screenshot("burst-header-at-top.svg", str(shots))

        above = [m for m in burst[:-1]
                 if (t := window.message_top(m.key)) is not None and t < window.scroll_y]
        assert above, "earlier burst heads are above the top row"
        assert pin.display, "pin visible when burst heads are above"
        assert pin.stacked.keys, "stacked keys present"
        assert pin.headers[0].label == f"{BURST} new", pin.headers[:1]
        # The latest header appears exactly once — as the overlay's last line,
        # never A's header covering visible B.
        latest_label = latest.header.label
        overlay_labels = [h.label for h in pin.headers]
        assert overlay_labels.count(latest_label) == 1, (
            f"latest header once in overlay, got {overlay_labels}")
        assert overlay_labels[-1] == latest_label, (
            f"latest header is the overlay's last line, got {overlay_labels}")
