"""Textual-facing: an older-page read that started on a history widget is published only if the widget's source is unchanged."""

import asyncio
from dataclasses import replace

from agent_comms.session_file import RegistrySessionLocation
from support import journals
import pytest
from support.textual_steps import saved_history
from toad.transcript_preparation import SavedHistory
from toad.widgets.presentation_window import OLDER_END


@pytest.mark.parametrize("cause", ("current", "revision", "edge", "parked", "loader"))
async def test_older_page_is_published_only_when_the_source_did_not_change_during_the_read(workspace, cause):
    journal = journals.write_journal(workspace.project / "saved.jsonl", *(
        journals.assistant_entry(f"Saved row {i}.", id=f"a{i}", parent=f"a{i - 1}" if i else None) for i in range(21)))
    transcripts = workspace.comms.transcripts
    workspace.comms.registry.declare(replace(workspace.thread("saved"), session_file=RegistrySessionLocation.from_path(str(journal), workspace.comms.root)))
    page = transcripts.capture_page_read("saved").read()
    assert page.has_older
    async with workspace.app(size=(110, 35)) as ui:
        view = ui.conversation
        entered, release = asyncio.Event(), asyncio.Event()

        async def loader(**bounds):
            entered.set()
            await release.wait()
            return await asyncio.to_thread(lambda: transcripts.capture_page_read("saved", **bounds).read())

        history = await saved_history(view, page, loader)
        await view.contents.mount(history)
        # Reserved source work keeps automatic edge requests from reading before this controlled read.
        history.reserve_source_work()
        task = asyncio.create_task(history._load_page(OLDER_END))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            pages, fragments = tuple(history.pages), history.fragments_in_range
            if cause == "revision":
                history.invalidate_projection()
            elif cause == "edge":
                edge = history.pages[0]
                async with view.window.history_lock:
                    async with view.window.preserve_history():
                        edge.prepared.set_fragment_range(slice(0, 0))
                        edge.range_changed()
                fragments = history.fragments_in_range
            elif cause == "parked":
                await history.retire_source(parked=True)
            elif cause == "loader":
                async def replacement(**bounds):
                    return await loader(**bounds)
                previous = history.page_source
                history.page_source = SavedHistory(replacement, previous.through, ui.app.preparation)
                previous.close()
            release.set()
            result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10))[0]
            if isinstance(result, BaseException):
                # Closing a replaced source cancels its read: a terminal answer, not permission to publish old content.
                assert cause != "current" and isinstance(result, asyncio.CancelledError), result
            if cause == "current":
                assert len(history.pages) > len(pages)
                assert len(tuple(history.coverage_events)) == 2
                assert ui.failure() is None
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
        journals.assistant_entry(f"Saved row {i}.", id=f"a{i}", parent=f"a{i - 1}" if i else None) for i in range(21)))
    transcripts = workspace.comms.transcripts
    workspace.comms.registry.declare(replace(workspace.thread("saved"), session_file=RegistrySessionLocation.from_path(str(journal), workspace.comms.root)))
    page = transcripts.capture_page_read("saved").read()

    async def loader(**bounds):
        return await asyncio.to_thread(lambda: transcripts.capture_page_read("saved", **bounds).read())

    async with workspace.app(size=(110, 35)) as ui:
        scheduled = await saved_history(ui.conversation, page, loader)
        await ui.conversation.contents.mount(scheduled)
        scheduled.window.lookahead.request_older()
        scheduled.request_page(OLDER_END)
        await ui.until(lambda: len(scheduled.pages) >= 2 and scheduled.source_ready, why="the older page read")
        assert ui.failure() is None
