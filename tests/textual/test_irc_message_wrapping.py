"""Textual-facing: IRC message rows wrap at the full terminal width; their routing spans are clickable at every width."""

import inspect
from pathlib import Path
import sys

from agent_comms.messages import Message, MessageType
from agent_comms.mro_dispatch import handles

from toad.app import ToadApp
from toad.core.input_events import SelectTarget
from toad.core_event_carrier import CoreEventMessage


class RecordingApp(ToadApp):
    """Records which targets the routing spans ask to open."""

    # Textual resolves a relative CSS_PATH against the module that defines the class.
    CSS_PATH = [Path(inspect.getfile(ToadApp)).parent / name for name in ToadApp.CSS_PATH]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.opened = []

    @handles(SelectTarget)
    def selected(self, event: CoreEventMessage):
        event.stop()
        self.opened.append((event.event.target.name, event.event.target.declared_name))


def message_rows():
    from toad.widgets.irc_message import IRCMessage

    for target in ("#all", "receiver-with-long-name"):
        yield IRCMessage(Message(sender="explorer-grandchild", target=target,
                                 body="payload " * 30 + "\nsecond paragraph [literal markup]",
                                 type=MessageType.INFO))


async def click_target(ui, screen, target):
    """Click the rendered routing span, including when the header wraps."""
    from toad.widgets.irc_message import IRCMessage, IRCMessageText

    pilot = ui.textual[1]
    for row in screen.query(IRCMessage):
        if target not in {row.message.sender, row.message.target}:
            continue
        row.scroll_visible(animate=False)
        await ui.step()
        text = row.query_one(IRCMessageText)
        for y in range(text.size.height):
            x = 0
            for segment in text.render_line(y):
                if segment.style and segment.style.meta.get("@click") == ("open_target", (target,)):
                    assert await pilot.click(text, offset=(x, y))
                    return
                x += segment.cell_length
    raise AssertionError(f"No clickable routing span for {target}")


async def shown_rows(ui):
    from textual.screen import Screen
    from toad.widgets.irc_message import IRCMessageText

    app = ui.textual[0]
    screen = Screen()
    await app.push_screen(screen)
    await screen.mount(*message_rows())
    for text in screen.query(IRCMessageText):
        await text.wait_ready()
    await ui.step()
    return screen


async def test_restyling_a_prepared_body_republishes_its_text_without_a_second_layout(workspace):
    from toad.widgets.irc_message import IRCMessageText

    async with workspace.app(size=(80, 50), application=RecordingApp) as ui:
        screen = await shown_rows(ui)
        body = screen.query_one(IRCMessageText)
        previous = body._prepared
        published_layout = []

        def observe_publication(frame, event, argument):
            if (event == "call" and frame.f_code.co_name == "refresh"
                    and frame.f_locals.get("self") is body and frame.f_back.f_code.co_name == "_prepare"):
                published_layout.append(frame.f_locals["layout"])

        sys.setprofile(observe_publication)
        try:
            body.styles.color = "green"
            await ui.until(lambda: body._prepared is not previous and body.paint_ready, seconds=15,
                           why="the body to republish")
            await ui.step()
        finally:
            sys.setprofile(None)
        assert body._prepared.text == previous.text
        assert (body._prepared.width, len(body._prepared.lines)) == (previous.width, len(previous.lines))
        assert published_layout == [False], published_layout


async def test_rows_fill_the_width_and_their_routing_spans_open_targets_at_every_width(workspace):
    from toad.widgets.irc_message import IRCMessage, IRCMessageText

    async with workspace.app(size=(80, 50), application=RecordingApp) as ui:
        app = ui.textual[0]
        screen = await shown_rows(ui)
        for width in (80, 36, 120):
            await ui.resize(width, 50)
            for text in screen.query(IRCMessageText):
                await text.wait_ready()
            await ui.step()
            row = screen.query(IRCMessage).first()
            text = row.query_one(IRCMessageText)
            lines = [text.render_line(y).text for y in range(text.size.height)]
            assert row.size.width == width
            assert text.region.x == row.region.x, (row.region, text.region)
            assert text.size.width == width, (width, row.region, text.region)
            assert lines[1].startswith("payload"), (width, lines)
            assert any(line.startswith("second paragraph") for line in lines)
            assert "[literal markup]" in " ".join(" ".join(lines).split()), (width, lines)
            await click_target(ui, screen, "explorer-grandchild")
            await click_target(ui, screen, "#all")
            await click_target(ui, screen, "receiver-with-long-name")
            await ui.step()
            assert app.opened[-3:] == [("explorer-grandchild", "thread"), ("#all", "channel"),
                                       ("receiver-with-long-name", "thread")]


async def test_keyboard_opens_sender_and_destination_and_select_all_copies_the_whole_body(workspace):
    from textual.selection import SELECT_ALL
    from toad.widgets.irc_message import IRCMessage, IRCMessageText

    async with workspace.app(size=(80, 50), application=RecordingApp) as ui:
        app = ui.textual[0]
        screen = await shown_rows(ui)
        row = screen.query(IRCMessage).first()
        body = screen.query_one(IRCMessageText)
        row.focus()
        await ui.press("enter", "shift+enter")
        assert app.opened[-2:] == [("explorer-grandchild", "thread"), ("#all", "channel")]
        app.screen.selections = {body: SELECT_ALL}
        await body.wait_ready()
        await ui.step()
        assert body.get_selection(SELECT_ALL)[0] == body._source.materialize().plain
        assert body._wanted.task.source.selection is not None
