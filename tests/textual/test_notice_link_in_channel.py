"""Textual-facing: a failure notice's "[Open diagnostic](file://…)" is drawn in a channel as the link "Open diagnostic", highlighted under the pointer and opening the file's preview when clicked, with the click a thread's saved history gives the same text."""

from agent_comms.message_reference import MessageReference
from agent_comms.messages import MessageType
from agent_comms.routing import MessageRoute
from agent_comms.transcript_events import IncomingTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage

from toad.line_blocks import OpenUrl
from toad.widgets.project_panel import FilePreview
from toad.widgets.transcript_history import TranscriptHistory


def linked(ui):
    """What a click on the label runs, once the label is drawn."""
    return ui.link_at("Open diagnostic") if "Open diagnostic" in ui.visible_text() else None


async def test_a_notice_link_to_a_file_is_drawn_as_its_label_and_opens_the_file(workspace):
    workspace.thread("owner", "team", running=True)
    workspace.thread("peer", "team", running=True)
    diagnostic = workspace.project / "diagnostics" / "turn-failure.json"
    diagnostic.parent.mkdir(parents=True)
    diagnostic.write_text('{"failure": "DIAGNOSTIC_CONTENT"}\n')
    text = f"Request failed. [Open diagnostic]({diagnostic.as_uri()})"
    workspace.comms.messaging.send("peer", "#team", text, MessageType.ALERT, notice=True)
    cursor = TranscriptCursor("fixture", 1)
    saved = TranscriptPage((IncomingTranscript(text, route=MessageRoute("peer", ("owner",)), timestamp=1_700_000_000.0,
                                               source=MessageReference(1, "incoming-1")),), cursor, cursor, False, False)
    async with workspace.app(size=(120, 36)) as ui:
        app, pilot = ui.textual
        owner = ui.selected_tab
        click = OpenUrl(diagnostic.as_uri()).click

        # A thread's own view draws the notice as Markdown: the label is the link.
        await ui.conversation.post(TranscriptHistory(saved))
        await ui.until(lambda: linked(ui) == click, why="the link in the thread's saved history")

        await ui.open_channel("#team", actor="owner", owner=owner)
        await ui.until_shows("Request failed")
        assert "Open diagnostic" in ui.visible_text()
        assert "](file:" not in ui.visible_text(), "the link's address is drawn as text"
        await ui.until(lambda: linked(ui) == click, why="the same link in the channel")

        cell = ui._cell_of("Open diagnostic", 0)
        page, _ = app.screen.get_widget_at(*cell)
        resting = app.screen.get_style_at(*cell).bgcolor
        await pilot.hover(offset=cell)
        await ui.until(lambda: app.screen.get_style_at(*cell).bgcolor != resting,
                       why="the link under the pointer drawn differently")
        assert app.screen.get_style_at(*cell).bgcolor == page.link_style_hover.bgcolor

        await ui.click("Open diagnostic")
        await ui.until(lambda: bool(app.selected_session.query(FilePreview)), seconds=5, why="the file's preview tab")
        assert app.selected_session.query_one(FilePreview).path == diagnostic.resolve()
        assert ui.failure() is None
