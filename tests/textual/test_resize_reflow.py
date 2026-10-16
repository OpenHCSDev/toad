"""Textual-facing: resizing the terminal (fullscreen and back) reflows saved history to the new width and keeps the tail, or the reader's place, on screen."""

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcript_sources import TranscriptCursor, NativeCursor
from agent_comms.transcripts import TranscriptPage

from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory


async def test_resize_keeps_tail_and_reader_position_visible(workspace):
    text = "## Resize test\n\n" + "A paragraph that wraps to the available viewport width. " * 80
    events = tuple(AssistantTranscript(f"Record {i}\n\n{text}") for i in range(20))
    page = TranscriptPage(events, NativeCursor("", 0), NativeCursor("", 0), False, False)

    async def load(**kwargs):
        raise AssertionError("No preceding file history in this fixture")

    async with workspace.app(size=(70, 25)) as ui:
        conversation = ui.conversation
        await conversation.contents.remove_children()
        await conversation.post(TranscriptHistory(page, load))
        await conversation.post(AgentResponse("FINAL_VISIBLE_MARKER\n\n" + "Last paragraph. " * 10))
        conversation.window.anchor()
        await ui.step()
        for width, height in ((145, 28), (70, 25), (180, 50), (95, 35), (70, 25), (145, 28)):
            await ui.resize(width, height)
            await ui.until_shows("FINAL_VISIBLE_MARKER")
            assert conversation.window.scroll_y <= conversation.window.max_scroll_y
        conversation.window.anchor(False)
        conversation.window.scroll_to(y=conversation.window.max_scroll_y // 2, animate=False, immediate=True)
        await ui.step()
        for width, height in ((70, 25), (145, 28), (95, 35), (180, 50), (70, 25)):
            await ui.resize(width, height)
            await ui.until(lambda: any(word in ui.visible_text() for word in ("paragraph", "Record", "Resize test")),
                           why="saved history on screen after the resize")
