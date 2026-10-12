"""Textual-facing: where the scroll position goes when a block is clicked (the block cursor's scroll is the frontend's)."""

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage

from toad.widgets.agent_response import AgentResponse
from toad.widgets.note import Note
from toad.widgets.transcript_history import TranscriptHistory


async def settled_at_end(ui, view):
    """At the end of the content, once the content has stopped growing."""
    steady = 0
    while steady < 5:
        extent = view.window.max_scroll_y
        view.window.scroll_end(animate=False, immediate=True)
        await ui.step(0.05)
        steady = steady + 1 if extent == view.window.max_scroll_y == view.window.scroll_y > 0 else 0


def row_of(ui, text):
    return next(y for y, line in enumerate(ui.visible_lines()) if text in line)


async def clicked(ui, view, text, block):
    await ui.click(text)
    await ui.until(lambda: view.cursor_block is block, why=f"the cursor on the block showing {text!r}")
    await ui.step()
    await ui.step()


async def test_clicking_a_block_that_fits_the_viewport_does_not_scroll(workspace):
    async with workspace.app(size=(110, 38)) as ui:
        view = ui.conversation
        await view.contents.remove_children()
        notes = [Note(f"NOTE_{i}\nsecond line\nthird line") for i in range(30)]
        await view.contents.mount(*notes)
        await settled_at_end(ui, view)
        before = view.window.scroll_y

        await clicked(ui, view, "NOTE_29", notes[29])
        assert view.window.scroll_y == before
        await clicked(ui, view, "NOTE_24", notes[24])
        assert view.window.scroll_y == before


async def test_clicking_saved_history_does_not_scroll(workspace):
    cursor = TranscriptCursor("fixture", 1)
    page = TranscriptPage(tuple(AssistantTranscript(f"RECORD_{i} " + "word " * 60) for i in range(60)),
                          cursor, cursor, False, False)
    async with workspace.app(size=(110, 38)) as ui:
        view = ui.conversation
        history = TranscriptHistory(page)
        await view.post(history)
        await view.contents.mount(Note("LIVE_NOTE"))
        await ui.until(lambda: history.is_mounted, why="the history mounted")
        await settled_at_end(ui, view)
        await ui.until_shows("RECORD_59")
        before = view.window.scroll_y, row_of(ui, "RECORD_59")

        await clicked(ui, view, "RECORD_59", history)
        assert (view.window.scroll_y, row_of(ui, "RECORD_59")) == before


async def test_clicking_a_block_taller_than_the_viewport_shows_its_top(workspace):
    async with workspace.app(size=(110, 38)) as ui:
        view = ui.conversation
        await view.contents.remove_children()
        tall = Note("\n".join(f"TALL_LINE_{i}" for i in range(120)))
        await view.contents.mount(Note("ABOVE"), tall)
        await settled_at_end(ui, view)

        await clicked(ui, view, "TALL_LINE_119", tall)
        await ui.until(lambda: tall.region.y == view.window.content_region.y, why="the tall block's top at the viewport's top")
        assert ui.shows("TALL_LINE_0")


async def test_clicking_or_entering_a_live_agent_response_selects_its_text(workspace):
    async with workspace.app(size=(110, 38)) as ui:
        view = ui.conversation
        await view.contents.remove_children()
        response = await view.post(AgentResponse("RESPONSE_TEXT in **Markdown**"))
        await ui.until_shows("RESPONSE_TEXT")

        await clicked(ui, view, "RESPONSE_TEXT", response)
        assert view.cursor_block_child is response.body
        assert view.navigation.cursor.get_clipboard_text() == "RESPONSE_TEXT in **Markdown**"

        view.navigation.clear()
        view.action_cursor_up()
        await ui.step()
        assert view.cursor_block_child is response.body
        assert ui.failure() is None
