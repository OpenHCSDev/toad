"""Textual-facing: repeated earlier-page admission through the history window keeps the admitted fragments bounded and the source whole.

Not carried over from the old script: keeping a selected paragraph widget alive through admission and trimming
(selection lived in per-message Markdown widgets; there are none), the widget count, and the admission durations.
"""

from unittest.mock import patch

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcript_sources import TranscriptCursor, NativeCursor
from agent_comms.transcripts import TranscriptPage

from toad.widgets.transcript_history import TranscriptHistory


async def test_admitting_earlier_pages_repeatedly_keeps_admission_bounded_and_the_source_untruncated(workspace):
    events = tuple(AssistantTranscript(f"Record {index}\n\n" + "long paragraph words " * 28) for index in range(120))
    cursor = NativeCursor("fixture", 0)
    async with workspace.app(size=(150, 80)) as ui:
        history = TranscriptHistory(TranscriptPage(events, cursor, cursor, False, False))
        await ui.conversation.contents.mount(history)
        await ui.until(lambda: history.is_mounted, why="the history mounted")
        window = history.window
        window.release_anchor()
        admitted = []
        with patch.object(history, "_check_edges", lambda: None):
            for _ in range(20):
                window.scroll_to(y=1, animate=False, immediate=True)
                await ui.step()
                await history._load_page(True)
                await ui.step()
                admitted.append(history.fragment_count)
        assert max(admitted) <= 32, admitted
        assert history.pages[0].page.events == events, "Source history was truncated"
