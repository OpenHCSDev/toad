"""Textual-facing: an older-page read that started on a history widget is published only if the widget's source is unchanged."""

import asyncio

from agent_comms.threads import Thread

from support import journals
from toad.widgets.transcript_history import TranscriptHistory

import pytest


@pytest.mark.parametrize("cause", ("current", "revision", "edge", "parked", "loader"))
async def test_older_page_is_published_only_when_the_source_did_not_change_during_the_read(workspace, cause):
    journal = journals.write_journal(workspace.project / "saved.jsonl", *(
        journals.assistant_entry(f"Saved row {i}.", id=f"a{i}", parent=f"a{i - 1}" if i else None) for i in range(4)))
    transcripts = workspace.comms.transcripts
    workspace.comms.registry.declare(Thread("saved", frozenset(), str(workspace.project), session_file=str(journal)))
    page = transcripts.thread_transcript_page("saved", max_messages=1)
    assert page.has_older
    async with workspace.app(size=(110, 35)) as ui:
        view = ui.conversation
        entered, release = asyncio.Event(), asyncio.Event()

        async def loader(**bounds):
            entered.set()
            await release.wait()
            return await asyncio.to_thread(transcripts.thread_transcript_page, "saved", max_messages=1, **bounds)

        history = TranscriptHistory(page, loader)
        await view.contents.mount(history)
        # Reserved source work keeps automatic edge requests from reading before this controlled read.
        history.reserve_source_work()
        task = asyncio.create_task(history._load_page(True))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            pages, fragments = tuple(history.pages), history.fragments_in_range
            if cause == "revision":
                history.invalidate_projection()
            elif cause == "edge":
                edge = history.pages[0]
                async with view.window.history_lock:
                    async with view.window.preserve_history():
                        edge.prepared.trim(edge, 1, older=True)
                fragments = history.fragments_in_range
            elif cause == "parked":
                await history.retire_source(parked=True)
            elif cause == "loader":
                async def replacement(**bounds):
                    return await loader(**bounds)
                history.loader = replacement
            release.set()
            result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10))[0]
            if isinstance(result, BaseException):
                # Closing a replaced source cancels its read: a terminal answer, not permission to publish old content.
                assert cause != "current" and isinstance(result, asyncio.CancelledError), result
            if cause == "current":
                assert len(history.pages) > len(pages)
            else:
                assert tuple(history.pages) == pages
                assert history.fragments_in_range == fragments
        finally:
            release.set()
            if not task.done():
                await asyncio.wait_for(task, 10)
            await history.remove()


async def test_requested_older_page_is_read_by_the_history_worker(workspace):
    journal = journals.write_journal(workspace.project / "saved.jsonl", *(
        journals.assistant_entry(f"Saved row {i}.", id=f"a{i}", parent=f"a{i - 1}" if i else None) for i in range(4)))
    transcripts = workspace.comms.transcripts
    workspace.comms.registry.declare(Thread("saved", frozenset(), str(workspace.project), session_file=str(journal)))
    page = transcripts.thread_transcript_page("saved", max_messages=1)

    async def loader(**bounds):
        return await asyncio.to_thread(transcripts.thread_transcript_page, "saved", max_messages=1, **bounds)

    async with workspace.app(size=(110, 35)) as ui:
        scheduled = TranscriptHistory(page, loader)
        await ui.conversation.contents.mount(scheduled)
        scheduled._request_page(True)
        await ui.until(lambda: len(scheduled.pages) >= 2 and scheduled.checkpoint_available, why="the older page read")
