from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from agent_comms.mro_dispatch import handles
"""Full-width wrapping and routed spans at different terminal widths."""

import asyncio

from agent_comms.messages import Message, MessageType
from textual import on
from textual.app import App, ComposeResult

from toad.core.input_events import SelectTarget
from toad.widgets.irc_message import IRCMessage, IRCMessageText


async def click_target(app, pilot, target):
    """Click the rendered routing span, including when the header wraps."""
    for row in app.screen.query(IRCMessage):
        if target not in {row.message.sender, row.message.target}:
            continue
        row.scroll_visible(animate=False)
        await pilot.pause()
        text = row.query_one(IRCMessageText)
        for y in range(text.size.height):
            x = 0
            for segment in text.render_line(y):
                if segment.style and segment.style.meta.get("@click") == (
                    "open_target",
                    (target,),
                ):
                    assert await pilot.click(text, offset=(x, y))
                    return
                x += segment.cell_length
    raise AssertionError(f"No clickable routing span for {target}")


class WrapApp(CoreEventReceiver, App):
    def __init__(self):
        super().__init__()
        self.opened = []

    def compose(self) -> ComposeResult:
        for target in ("#all", "receiver-with-long-name"):
            yield IRCMessage(
                Message(
                    sender="explorer-grandchild",
                    target=target,
                    body="payload " * 30 + "\nsecond paragraph [literal markup]",
                    type=MessageType.INFO,
                )
            )

    @handles(SelectTarget)
    def selected(self, event: CoreEventMessage):
        event.stop()
        self.opened.append((event.event.target.name, event.event.target.declared_name))


async def main():
    app = WrapApp()
    async with app.run_test(size=(80, 50)) as pilot:
        for width in (80, 36, 120):
            await pilot.resize_terminal(width, 50)
            await pilot.pause()
            row = app.query(IRCMessage).first()
            text = row.query_one(IRCMessageText)
            lines = [text.render_line(y).text for y in range(text.size.height)]
            assert row.size.width == width
            assert text.region.x == row.region.x, (row.region, text.region)
            assert text.size.width == width, (width, row.region, text.region)
            assert lines[1].startswith("payload"), (width, lines)
            assert any(line.startswith("second paragraph") for line in lines)
            assert "[literal markup]" in " ".join(" ".join(lines).split()), (
                width,
                lines,
            )
            await click_target(app, pilot, "explorer-grandchild")
            await click_target(app, pilot, "#all")
            await click_target(app, pilot, "receiver-with-long-name")
            await pilot.pause()
            assert app.opened[-3:] == [
                ("explorer-grandchild", "thread"),
                ("#all", "channel"),
                ("receiver-with-long-name", "thread"),
            ]
        row.focus()
        await pilot.press("enter", "shift+enter")
        await pilot.pause()
        assert app.opened[-2:] == [
            ("explorer-grandchild", "thread"),
            ("#all", "channel"),
        ]
    print(
        "IRC wrapping: full-width body, newlines, clickable spans and keyboard navigation passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
