"""Textual-facing: a transcript history widget's source state follows its real mount, commit, worker and removal."""

import asyncio

from agent_comms.threads import Thread

from support import journals
from toad.transcript_state import DetachedTranscript, LiveTranscript, ProvisionalTranscript
from toad.widgets.transcript_history import TranscriptHistory


async def test_source_state_follows_mount_commit_worker_retirement_and_removal(workspace):
    source = journals.write_journal(workspace.project / "session.jsonl",
                                    journals.assistant_entry("Retain the source", id="a1"))
    workspace.comms.registry.declare(Thread("source", frozenset(), str(workspace.project), session_file=str(source)))
    page = workspace.comms.transcripts.thread_transcript_page("source")
    history = TranscriptHistory(page, committed=False)
    assert isinstance(history.state, DetachedTranscript)
    assert not history.state.can_draw
    async with workspace.app() as ui:
        await ui.conversation.post(history)
        await ui.until(lambda: history.is_mounted, why="the history mounted")
        assert isinstance(history.state, ProvisionalTranscript)
        assert not history.state.can_draw
        coverage = []
        history.publish_core = coverage.append
        history.publish_committed()
        assert not coverage, "source coverage escaped before the first painted frame"
        await ui.step()
        assert coverage and coverage[-1].events == page.events
        assert isinstance(history.state, LiveTranscript)
        assert history.state.can_draw
        assert history.state.reports_coverage
        assert history.checkpoint_available

        entered, release = asyncio.Event(), asyncio.Event()

        async def pending_source_read():
            entered.set()
            await release.wait()
            return page

        operation = history.reserve_source_work()
        operation.schedule(history, pending_source_read)
        await entered.wait()
        assert history.state.can_draw
        assert history.state.reports_coverage
        assert not history.state.accepts_source_work
        assert not history.checkpoint_available
        history.request_latest()
        # A parked tab cancels its running operation and the pending End.
        # Resuming accepts work on the same source, never a dead worker.
        await history.retire_source(parked=True)
        assert not history.state.can_draw
        history.resume_source()
        await ui.until(lambda: history.state.accepts_source_work, why="source work accepted after resume")
        assert history.checkpoint_available
        # The framework worker is cancelled during retirement; its completion
        # cannot restore the earlier live source.
        await history.retire_source()
        await ui.until(lambda: not history.state.accepts_source_work, why="source work refused after retirement")
        assert not history.state.can_draw
        assert not history.state.reports_coverage
        # remove() marks the node before its Prune message is processed; publication is refused in between.
        removal = history.remove()
        assert not history.state.can_draw
        await removal
        await ui.until(lambda: not history.is_attached, why="the history removed")
        assert not history.state.can_draw
    assert "Retain the source" in source.read_text()
