"""Textual-facing: a history of one-line pages fills the viewport by reading older pages as the window's layout asks, then goes idle."""

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import NativeTranscriptCursor, TranscriptPage
from support.roots import FIXTURE_SNAPSHOT

from toad.widgets.transcript_history import TranscriptHistory


def page(index):
    return TranscriptPage((AssistantTranscript(f"Saved activity {index}"),),
                          NativeTranscriptCursor("test", index), NativeTranscriptCursor("test", index + 1),
                          index > 0, index < 29, FIXTURE_SNAPSHOT)


async def test_sparse_pages_fill_the_viewport_then_stop_reading_and_keep_the_tail(workspace):
    calls = []

    async def load(*, before=None, after=None, through=None):
        index = before.offset - 1 if before is not None else after.offset
        calls.append(index)
        return page(index)

    async with workspace.app(size=(100, 40)) as ui:
        conversation = ui.conversation
        history = TranscriptHistory(page(29), load)
        await conversation.post(history)
        await ui.until(lambda: history.is_mounted and calls, why="the first older page read")
        # Idle: the count of reads stays put while the history accepts work and is not at the older edge.
        stable = []

        def idle():
            at_older_edge = history.has_older and history.region.y >= history.window.content_region.y - 2
            stable.append(len(calls) if history.state.accepts_source_work and not at_older_edge else None)
            return len(stable) >= 4 and stable[-1] is not None and len(set(stable[-4:])) == 1

        await ui.until(idle, seconds=5, why="the history to go idle")
        count = len(calls)
        await ui.step(1)
        assert len(calls) == count, (calls, count)
        assert len(calls) == len(set(calls)), calls
        assert not history.has_newer
        assert history.pages[-1].page.after.offset == 30
        assert conversation.window.follows_tail
        assert conversation.window.scroll_y == conversation.window.max_scroll_y
