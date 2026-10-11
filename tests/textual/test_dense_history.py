"""Textual-facing: scrolling a dense history to its top admits the next earlier range each time until the first record is reached.

Not carried over from the old script: that newer records stay available while older ones are admitted and that older history remains available
after ten scrolls (both came from widget-budget eviction; the fragment budget is far larger than this fixture), and the peak count of materialized widgets against the widget budget (history is
line-drawn; there are no per-message widget trees to count).
"""

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage

from toad.widgets.transcript_history import TranscriptHistory


async def test_each_scroll_to_the_top_admits_earlier_records_and_until_the_first_record_is_reached(workspace):
    cursor = TranscriptCursor("fixture", 1)
    page = TranscriptPage(tuple(
        AssistantTranscript(f"Record {i}\n\n" + "\n".join(f"- item {j}" for j in range(20))) for i in range(30)),
        cursor, cursor, False, False)
    async with workspace.app(size=(110, 38)) as ui:
        view = ui.conversation
        history = TranscriptHistory(page)
        await view.post(history)
        await ui.until(lambda: history.is_mounted, why="the history mounted")
        steps = 0
        while history.pages[0].start > 0:
            steps += 1
            assert steps <= 40, "Scrolling to the top stopped admitting earlier records"
            before = history.pages[0].start
            view.window.scroll_home(animate=False, immediate=True)
            await ui.until(lambda: history.pages[0].start < before and history.state.accepts_source_work,
                           seconds=5, why=f"records earlier than {before} admitted")
        assert steps > 1, "The history was admitted in one step, not progressively"
        assert not history.has_older
