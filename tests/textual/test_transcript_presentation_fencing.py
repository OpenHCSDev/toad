"""Textual-facing: transcript presentations queue behind Textual's callback pump and paint into the conversation window."""

import asyncio
from contextlib import asynccontextmanager
import pytest

from support.journals import assistant_entry, write_journal
from agent_comms.thread_text import SavedSessionFile
from toad.transcript_publication import CommitPublication, TranscriptPublication
from toad.widgets.agent_response import AgentResponse


class DeclaredCase(TranscriptPublication):
    """A newly declared case: it paints one response, unless it is no longer current."""

    def __init__(self, binding, owner, generation, entered, release):
        super().__init__(binding, owner, generation)
        self.entered, self.release = entered, release

    async def publish_applied(self):
        self.entered.set()
        await self.release.wait()
        if self.current():
            await self.binding.contents.mount(AgentResponse("Declared case painted"))
        return True


class HeldSourceCase(CommitPublication):
    """A real certified read, held before its application is joined."""

    def __init__(self, binding, owner, generation, entered, release):
        super().__init__(binding, owner, generation)
        self.entered, self.release = entered, release

    async def read_snapshot(self):
        page = await super().read_snapshot()
        self.entered.set()
        await self.release.wait()
        return page


@asynccontextmanager
async def hold_application(view):
    """Release the occupied callback pump even when its caller's assertion fails."""
    started, release = asyncio.Event(), asyncio.Event()

    async def held():
        started.set()
        await release.wait()

    view.call_later(held)
    # The pump is busy once the callback runs, so the pilot cannot step: wait on the event itself.
    try:
        await asyncio.wait_for(started.wait(), 10)
        yield
    finally:
        release.set()


async def stays_waiting(task) -> bool:
    """Whether `task` is still unfinished after the loop had time to run it (the pump is held)."""
    done, _ = await asyncio.wait({task}, timeout=0.03)
    return not done


async def finish(ui, task, why):
    await ui.until(task.done, why=why)
    return await task


async def test_a_case_queued_behind_the_pump_does_not_adopt_a_replacement_generation(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        async with hold_application(view):
            entered, release = asyncio.Event(), asyncio.Event()
            release.set()
            case = view.transcript.binding.capture(view.transcript, DeclaredCase, entered, release)
            pending = asyncio.create_task(case.publish())
            assert await stays_waiting(pending) and not entered.is_set()
            view.transcript.invalidate_publications()
        await finish(ui, pending, "the queued case to return")
        assert not entered.is_set()


async def test_cancelling_a_waiting_caller_leaves_the_pump_and_runs_nothing(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        async with hold_application(view):
            entered, release = asyncio.Event(), asyncio.Event()
            pending = asyncio.create_task(view.transcript.publish(DeclaredCase, entered, release))
            assert await stays_waiting(pending)
            pending.cancel()
            result = await asyncio.gather(pending, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)
            assert not entered.is_set() and not view.task.done()
        await ui.step()


async def test_a_case_invalidated_while_applying_paints_nothing_and_the_next_one_paints(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        entered, release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(view.transcript.publish(DeclaredCase, entered, release))
        await ui.until(entered.is_set, why="the case to start applying")
        view.transcript.invalidate_publications()
        release.set()
        await finish(ui, pending, "the invalidated case to return")
        assert not view.contents.query(AgentResponse)
        await view.transcript.publish(DeclaredCase, entered, release)
        await ui.until(lambda: "Declared case painted" in ui.painted(view.window), why="the declared case painted in the window")


async def test_a_pending_request_does_not_paint_a_replacement_source(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        requests = view.transcript.source_requests
        entered, release = asyncio.Event(), asyncio.Event()
        requests.request(DeclaredCase, entered, release)
        await ui.until(entered.is_set, why="the running request to start")
        queued_entered, queued_release = asyncio.Event(), asyncio.Event()
        queued_release.set()
        requests.request(DeclaredCase, queued_entered, queued_release)
        view.transcript.invalidate_publications()
        release.set()
        await requests.worker.wait()
        await ui.step()
        assert not view.contents.query(AgentResponse), "A pending request painted the replacement source"
        assert not queued_entered.is_set()
        requests.request(DeclaredCase, queued_entered, queued_release)
        await requests.worker.wait()
        await ui.until(lambda: len(view.contents.query(AgentResponse)) == 1, why="the new source's request to paint once")


async def test_a_certified_read_that_expired_acquires_no_application(workspace):
    journal = write_journal(workspace.project / "source.jsonl", assistant_entry("Certified source", id="source"))
    workspace.comms.registry.declare(workspace.comms.registry.new_thread("journal-source", frozenset(), str(workspace.project), session_file=SavedSessionFile(str(journal))))
    async with workspace.app(resume="journal-source") as ui:
        view = ui.conversation
        await ui.until_shows("Certified source")
        await view.transcript.suspend()
        view.transcript.dirty = view.transcript.commit_required = True
        original = view.transcript.binding.history
        entered, release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(view.transcript.publish(HeldSourceCase, entered, release))
        await ui.until(entered.is_set, why="the certified read to be held")
        view.transcript.invalidate_publications()
        release.set()
        await finish(ui, pending, "the expired read to return")
        assert view.transcript.binding.history is original, "Expired read replaced the mounted history"
        await view.transcript.publish(HeldSourceCase, entered, release)
        assert view.transcript.binding.history is original
        assert view.transcript.binding.history.page_source.through.session_file == str(journal)


async def test_closing_the_transcript_mid_application_paints_nothing(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        entered, release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(view.transcript.publish(DeclaredCase, entered, release))
        await ui.until(entered.is_set, why="the case to start applying")
        await view.transcript.close()
        release.set()
        await finish(ui, pending, "the case to return after close")
        assert not view.contents.query(AgentResponse)
        assert not view.transcript.binding.matches(view)


@pytest.mark.parametrize("after_admission", (False, True))
async def test_cancelling_a_staged_replacement_keeps_old_rows_and_restores_the_read_bound(workspace, monkeypatch, after_admission):
    from dataclasses import replace
    from types import MethodType
    from textual.widget import Widget
    from toad.widgets.transcript_lines import TranscriptLinesBatchRenderTask

    old = write_journal(workspace.project / "old.jsonl", assistant_entry("OLD_VISIBLE_SOURCE", id="old"))
    thread = workspace.thread("source")
    workspace.comms.registry.declare(replace(thread, session_file=SavedSessionFile(str(old))))
    async with workspace.app(resume="source") as ui:
        await ui.until_shows("OLD_VISIBLE_SOURCE")
        view = ui.conversation
        await ui.app.coordination_access.stop_observing()
        await view.transcript.suspend()
        history = view.transcript.binding.history
        original_source, original_scope = history.page_source, history.page_source.scope
        pages, through = tuple(history.pages), history.page_source.through
        new = write_journal(workspace.project / "new.jsonl", assistant_entry("NEW_VISIBLE_SOURCE", id="new"))
        workspace.comms.registry.declare(replace(thread, session_file=SavedSessionFile(str(new))))
        entered, release = asyncio.Event(), asyncio.Event()
        render_for = TranscriptLinesBatchRenderTask.render_for
        dispatch = asyncio.to_thread
        remove_children = Widget.remove_children
        render_owners = []

        async def held_dispatch(function, *args, **kwargs):
            if (not after_admission and isinstance(function, MethodType)
                    and isinstance(function.__self__, TranscriptLinesBatchRenderTask)
                    and not release.is_set()):
                entered.set()
                await release.wait()
            return await dispatch(function, *args, **kwargs)

        async def held_removal(owner, *args, **kwargs):
            removal = remove_children(owner, *args, **kwargs)
            if after_admission and owner is history and not release.is_set():
                render_owners.append(asyncio.current_task())
                entered.set()
                await release.wait()
            return await removal

        monkeypatch.setattr(asyncio, "to_thread", held_dispatch)
        monkeypatch.setattr(Widget, "remove_children", held_removal)
        view.window.anchor()
        view.prompt.focus()
        view.transcript.dirty = view.transcript.commit_required = True
        pending = asyncio.create_task(view.transcript.publish(CommitPublication))
        try:
            await asyncio.wait_for(entered.wait(), 8)
            await ui.step()
            if not after_admission:
                render_owners.extend(task for task in asyncio.all_tasks()
                                     if any(entry.frame.f_code is render_for.__func__.__code__
                                            and entry.frame.f_locals["view"] is history
                                            for entry in asyncio.capture_call_graph(task).call_stack))
            if after_admission:
                assert history.page_source is not original_source
                accepted_source = history.page_source
                assert accepted_source.through.session_file == str(new)
                assert tuple(history.pages) != pages
            else:
                assert "OLD_VISIBLE_SOURCE" in ui.painted(view.window)
                assert "NEW_VISIBLE_SOURCE" not in ui.painted(view.window)
                assert history.page_source is original_source
                assert history.page_source.scope is original_scope and not original_scope.closed
                assert tuple(history.pages) == pages
            applying, = render_owners
            assert applying.cancel()
            await asyncio.gather(applying, return_exceptions=True)
            if after_admission:
                assert history.page_source is accepted_source and not accepted_source.closed
                assert original_scope.closed
                assert history.page_source.through.session_file == str(new)
            else:
                assert history.page_source is original_source
                assert history.page_source.scope is original_scope and not original_scope.closed
                assert history.page_source.through == through
                assert tuple(history.pages) == pages and all(page.display for page in pages)
            release.set()
            await view.transcript.publish(CommitPublication)
            await ui.until_shows("NEW_VISIBLE_SOURCE")
            assert "OLD_VISIBLE_SOURCE" not in ui.painted(view.window)
        finally:
            release.set()
            for applying in render_owners:
                if not applying.done():
                    applying.cancel()
            await asyncio.gather(*render_owners, return_exceptions=True)
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("empty", (False, True))
async def test_a_closed_history_accepts_a_prepared_replacement_without_a_storage_read(workspace, empty):
    from dataclasses import replace
    from toad.transcript_preparation import ClosedHistory, TranscriptPageRenderTask
    from toad.transcript_state import PreparedReplacementViewportRequest
    from toad.widgets.history_anchor import LatestPosition
    from toad.work_preparation import RenderPreparation

    old = write_journal(workspace.project / "old.jsonl", assistant_entry("OLD_RETAINED_ROWS", id="old"))
    thread = workspace.thread("source")
    workspace.comms.registry.declare(replace(thread, session_file=SavedSessionFile(str(old))))
    async with workspace.app(resume="source") as ui:
        await ui.until_shows("OLD_RETAINED_ROWS")
        view = ui.conversation
        await ui.app.coordination_access.stop_observing()
        await view.transcript.suspend()
        history = view.transcript.binding.history
        history.close()
        original = history.page_source
        new = write_journal(workspace.project / "new.jsonl", *(
            () if empty else (assistant_entry("PREPARED_REPLACEMENT", id="new"),)))
        workspace.comms.registry.declare(replace(thread, session_file=SavedSessionFile(str(new))))
        page = workspace.comms.transcripts.thread_transcript_page("source")
        prepared = await ui.app.preparation.submit(RenderPreparation(TranscriptPageRenderTask(page)))
        assert await history.show_newest(PreparedReplacementViewportRequest(
            LatestPosition.hold(history.window), prepared))
        await ui.step()
        assert original.closed
        assert isinstance(history.page_source, ClosedHistory) and history.page_source is not original
        assert not history.page_source.closed and history.page_source.through == page.after
        assert "OLD_RETAINED_ROWS" not in ui.painted(view.window)
        if empty:
            assert not history.fragments_in_range
        else:
            await ui.until_shows("PREPARED_REPLACEMENT")
        assert ui.failure() is None
