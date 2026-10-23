"""Textual-facing: the pointer over one name in a chat highlights that name only, not every equal name on screen."""


from toad.line_blocks import OpenTarget
from toad.message_rows import MessageRow

async def test_the_pointer_over_one_sender_highlights_that_one_and_leaves_equal_names_as_drawn(workspace):
    workspace.thread("owner", "team", running=True)
    workspace.thread("peer", "team", running=True)
    sent = tuple(
        workspace.comms.messaging.send("peer", "#team", f"message {number} from the same thread").message
        for number in range(3)
    )
    header = MessageRow(sent[0], "owner").header
    sender = OpenTarget("peer")
    async with workspace.app(size=(100, 36)) as ui:
        app, pilot = ui.textual
        await ui.open_channel("#team", actor="owner", owner=ui.selected_tab)
        await ui.until(lambda: ui.visible_text().count(header.label) == 3, why="three messages from one sender")
        await ui.until(lambda: all(app.screen.get_style_at(*ui.link_cell(header, sender, occurrence=n)).meta.get("@click") == sender.click for n in range(3)),
                       why="three messages whose sender is the same link")
        cells = [ui.link_cell(header, sender, occurrence=n) for n in range(3)]
        body, _ = app.screen.get_widget_at(*cells[1])
        resting = [app.screen.get_style_at(*cell).bgcolor for cell in cells]

        await pilot.hover(offset=cells[1])
        await ui.until(lambda: app.screen.get_style_at(*cells[1]).bgcolor != resting[1],
                       why="the name under the pointer drawn differently")
        assert app.screen.get_style_at(*cells[1]).bgcolor == body.link_style_hover.bgcolor
        assert [app.screen.get_style_at(*cells[n]).bgcolor for n in (0, 2)] == [resting[0], resting[2]]
        # The destination on the same row is another link: it stays as drawn too.
        target = ui.link_cell(header, OpenTarget("#team"), occurrence=1)
        assert app.screen.get_style_at(*target).meta["@click"] == OpenTarget("#team").click
        assert app.screen.get_style_at(*target).bgcolor == resting[1]
        assert ui.failure() is None
