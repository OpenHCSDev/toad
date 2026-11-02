"""Textual-facing: transcript presentations queue behind Textual's callback pump and paint into the conversation window."""

from agent_comms.repo import Checkout
import asyncio
from contextlib import asynccontextmanager
import pytest

from support.journals import assistant_entry, write_journal
from agent_comms.session_file import RegistrySessionLocation
from agent_comms.threads import Thread
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
    workspace.comms.registry.declare(Thread("journal-source", frozenset(), Checkout(workspace.project), session_file=RegistrySessionLocation.from_path(str(journal), workspace.comms.root)))
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


async def test_followed_saved_append_keeps_painted_page_and_fragments(workspace):
    import json
    from dataclasses import replace

    thread = workspace.thread("append-source")
    journal = write_journal(
        thread.project_path / "append.jsonl",
        assistant_entry("FIRST_RETAINED_ROW", id="first"),
        assistant_entry("SECOND_RETAINED_ROW", id="second", parent="first"),
        assistant_entry("THIRD_RETAINED_ROW", id="third", parent="second"),
    )
    workspace.comms.registry.declare(replace(
        thread, session_file=RegistrySessionLocation.from_path(str(journal), workspace.comms.root)))
    async with workspace.app(resume="append-source") as ui:
        await ui.until_shows("THIRD_RETAINED_ROW")
        view = ui.conversation
        await ui.app.coordination_access.stop_observing()
        await view.transcript.suspend()
        history = view.transcript.binding.history
        assert view.window.follows_tail
        pages = tuple(history.pages)
        fragments = tuple(history.fragments_in_range)
        assert pages and fragments
        with journal.open("a") as output:
            output.write(json.dumps(assistant_entry(
                "APPENDED_SAVED_ROW", id="appended", parent="third")) + "\n")
        view.transcript.require_commit()
        await ui.until_shows("APPENDED_SAVED_ROW")
        assert view.transcript.binding.history is history
        assert all(page in history.pages for page in pages)
        current = tuple(history.fragments_in_range)
        assert all(any(fragment is kept for kept in current) for fragment in fragments)
        painted = ui.painted(view.window)
        assert all(marker in painted for marker in (
            "FIRST_RETAINED_ROW", "SECOND_RETAINED_ROW", "THIRD_RETAINED_ROW"))
        assert ui.failure() is None


async def test_followed_commit_publishes_a_known_undrawn_gap_before_settling(workspace):
    import json
    from dataclasses import replace

    thread = workspace.thread("gap-source")
    journal = write_journal(thread.project_path / "gap.jsonl",
                            assistant_entry("BEFORE_SOURCE_GAP", id="before"))
    workspace.comms.registry.declare(replace(
        thread, session_file=RegistrySessionLocation.from_path(str(journal), workspace.comms.root)))
    async with workspace.app(resume="gap-source") as ui:
        await ui.until_shows("BEFORE_SOURCE_GAP")
        view = ui.conversation
        await ui.app.coordination_access.stop_observing()
        await view.transcript.suspend()
        history = view.transcript.binding.history
        await ui.until(lambda: history.source_ready, why="the original source work to finish")
        with journal.open("a") as output:
            output.write(json.dumps(assistant_entry(
                "AFTER_SOURCE_GAP", id="after", parent="before")) + "\n")
        view.transcript.dirty = view.transcript.commit_required = True
        entered, release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(view.transcript.publish(HeldSourceCase, entered, release))
        try:
            # A successful publication return can also mean a guarded no-op.
            # Hold the existing real read only AFTER the commit was admitted.
            await ui.until(entered.is_set, why="the admitted commit to acquire its real source")
            page = workspace.comms.transcripts.capture_page_read("gap-source").read()
            history.retain_committed(page.after)
            assert view.window.follows_tail and history.drawn_end_more
        finally:
            release.set()
            await pending
        # Check the publication contract before a later lookahead can hide it.
        assert not history.drawn_end_more
        assert history.pages[-1].prepared.page.after.same_position(page.after)
        await ui.until_shows("AFTER_SOURCE_GAP")
        assert ui.failure() is None


@pytest.mark.parametrize("following", (False, True))
async def test_closed_same_source_commit_acquires_complete_coverage(workspace, following):
    import json
    from dataclasses import replace

    thread = workspace.thread("closed-prefix")
    journal = write_journal(thread.project_path / "closed.jsonl",
                            assistant_entry("CLOSED_PREFIX_MUST_SURVIVE", id="before"))
    workspace.comms.registry.declare(replace(
        thread, session_file=RegistrySessionLocation.from_path(str(journal), workspace.comms.root)))
    async with workspace.app(resume="closed-prefix") as ui:
        await ui.until_shows("CLOSED_PREFIX_MUST_SURVIVE")
        view = ui.conversation
        await ui.app.coordination_access.stop_observing()
        await view.transcript.suspend()
        history = view.transcript.binding.history
        history.close()
        if not following:
            view.window.release_anchor()
        pages = tuple(history.pages)
        fragments = tuple(history.fragments_in_range)
        position = view.window.reader_position
        with journal.open("a") as output:
            output.write(json.dumps(assistant_entry(
                "CLOSED_PREFIX_SUCCESSOR", id="after", parent="before")) + "\n")
        view.transcript.dirty = view.transcript.commit_required = True
        await view.transcript.publish(CommitPublication)
        if following:
            await ui.until_shows("CLOSED_PREFIX_SUCCESSOR")
        else:
            await ui.step()
            assert tuple(history.pages) == pages
            assert all(actual is original for actual, original in
                       zip(history.fragments_in_range, fragments, strict=True))
            assert view.window.reader_position == position
            assert "CLOSED_PREFIX_SUCCESSOR" not in ui.painted(view.window)
        assert "CLOSED_PREFIX_MUST_SURVIVE" in ui.painted(view.window)
        assert view.transcript.binding.history is history
        assert ui.failure() is None


@pytest.mark.parametrize("following", (False, True))
async def test_rewritten_saved_file_replaces_paint_even_when_its_cursor_grew(workspace, following):
    from dataclasses import replace
    from agent_comms.errors import TranscriptChanged

    thread = workspace.thread("rewritten-source")
    journal = write_journal(thread.project_path / "rewritten.jsonl",
                            assistant_entry("SUPERSEDED_SOURCE_ROW", id="old"))
    workspace.comms.registry.declare(replace(
        thread, session_file=RegistrySessionLocation.from_path(str(journal), workspace.comms.root)))
    async with workspace.app(resume="rewritten-source") as ui:
        await ui.until_shows("SUPERSEDED_SOURCE_ROW")
        view = ui.conversation
        await ui.app.coordination_access.stop_observing()
        await view.transcript.suspend()
        history = view.transcript.binding.history
        original = history.page_source.through
        if not following:
            view.window.release_anchor()
        # Reuse the path, but replace its native bytes with a longer record.
        # Filename/offset containment alone cannot witness this old prefix.
        write_journal(journal, assistant_entry(
            "REPLACEMENT_SOURCE_ROW " * 80, id="new"))

        def read_replacement():
            read = workspace.comms.transcripts.capture_page_read("rewritten-source")
            with pytest.raises(TranscriptChanged):
                read.read(position=original.later_page())
            return read.read()

        replacement = await asyncio.to_thread(read_replacement)
        assert replacement.after.contains(original)
        view.transcript.dirty = view.transcript.commit_required = True
        await view.transcript.publish(CommitPublication)
        await ui.until_shows("REPLACEMENT_SOURCE_ROW")
        assert "SUPERSEDED_SOURCE_ROW" not in ui.painted(view.window)
        assert view.transcript.binding.history is history
        assert ui.failure() is None


@pytest.mark.parametrize("pressure", (False, True))
async def test_prune_pressure_counts_live_blocks_not_saved_history(workspace, pressure):
    from dataclasses import replace
    from toad.preferences import SETTINGS

    thread = workspace.thread("pressure-source")
    journal = write_journal(thread.project_path / "pressure.jsonl",
                            assistant_entry("SAVED_PRESSURE_ROW_ONE\n\nSAVED_PRESSURE_ROW_TWO", id="saved"))
    workspace.comms.registry.declare(replace(
        thread, session_file=RegistrySessionLocation.from_path(str(journal), workspace.comms.root)))
    async with workspace.app(resume="pressure-source") as ui:
        await ui.until_shows("SAVED_PRESSURE_ROW_TWO")
        view = ui.conversation
        await ui.app.coordination_access.stop_observing()
        await view.post(AgentResponse("\n\n".join(
            f"Actual live response paragraph {number}" for number in range(128))))
        await ui.until(lambda: view.contents.virtual_size.height
                       - view.transcript.binding.history.outer_size.height > 100,
                       why="the real live response to have its laid-out height")
        await view.transcript.suspend()
        history = view.transcript.binding.history
        live_height = view.contents.virtual_size.height - history.outer_size.height
        threshold = live_height + 1 - 2 * int(pressure)
        assert threshold >= 100 and history.outer_size.height > 2
        assert view.contents.virtual_size.height > threshold
        ui.app.saved_settings.set(SETTINGS.ui.prune_low_mark, threshold)
        ui.app.saved_settings.set(SETTINGS.ui.prune_excess, 0)
        view.transcript.dirty = view.transcript.commit_required = False
        view._require_check_prune = True
        await view.check_prune()
        assert view.transcript.commit_required is pressure
        assert ui.failure() is None


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




@pytest.mark.parametrize("empty", (False, True))
async def test_a_closed_history_accepts_a_prepared_replacement_without_a_storage_read(workspace, empty):
    from dataclasses import replace
    from toad.transcript_preparation import ClosedHistory, TranscriptPageRenderTask
    from toad.transcript_state import PreparedReplacementViewportRequest
    from toad.widgets.history_anchor import LatestPosition
    from toad.work_preparation import RenderPreparation

    old = write_journal(workspace.project / "old.jsonl", assistant_entry("OLD_RETAINED_ROWS", id="old"))
    thread = workspace.thread("source")
    workspace.comms.registry.declare(replace(thread, session_file=RegistrySessionLocation.from_path(str(old), workspace.comms.root)))
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
        workspace.comms.registry.declare(replace(thread, session_file=RegistrySessionLocation.from_path(str(new), workspace.comms.root)))
        page = workspace.comms.transcripts.capture_page_read("source").read()
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
