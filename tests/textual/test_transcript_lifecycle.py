"""Textual-facing: a transcript history widget's source state follows its real mount, commit, worker and removal."""

from agent_comms.session_file import RegistrySessionLocation
import asyncio
from dataclasses import replace
import pytest
from textual.await_complete import AwaitComplete
from textual.worker import DeadlockError, get_current_worker

from support import journals
from support.agents import RecordedEvents
from support.textual_steps import saved_history
from toad.core.source_events import TranscriptCoverage
from toad.paths import get_log
from toad.transcript_state import DetachedTranscript, LiveTranscript, ProvisionalTranscript


async def test_source_state_follows_mount_commit_worker_retirement_and_removal(workspace):
    source = journals.write_journal(workspace.project / "session.jsonl",
                                    journals.assistant_entry("Retain the source", id="a1"))
    workspace.comms.registry.declare(replace(workspace.thread("source"), session_file=RegistrySessionLocation.from_path(source, workspace.comms.root)))
    page = workspace.comms.transcripts.capture_page_read("source").read()
    async with workspace.app() as ui:
        async def loader(**bounds):
            return await asyncio.to_thread(
                lambda: workspace.comms.transcripts.capture_page_read("source", **bounds).read())

        history = await saved_history(ui.conversation, page, loader, committed=False)
        assert isinstance(history.state, DetachedTranscript)
        assert not history.state.can_draw
        await ui.conversation.post(history)
        await ui.until(lambda: history.is_mounted, why="the history mounted")
        assert isinstance(history.state, ProvisionalTranscript)
        assert not history.state.can_draw
        coverage = RecordedEvents()
        subscription = history.core_publications.subscribe(TranscriptCoverage, coverage.receive)
        history.publish_committed()
        assert not coverage, "source coverage escaped before the first painted frame"
        await ui.step()
        assert coverage and coverage[-1].events == page.events
        assert isinstance(history.state, LiveTranscript)
        assert history.state.can_draw
        assert history.state.reports_coverage

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
        history.window.action_scroll_end()
        # A parked tab cancels its running operation and the pending End.
        # Resuming accepts work on the same source, never a dead worker.
        await history.retire_source(parked=True)
        assert not history.state.can_draw
        history.resume_source()
        await ui.until(lambda: history.state.accepts_source_work, why="source work accepted after resume")
        # A pager can initiate retirement from its own operation. Its independent
        # join must not inherit that worker's self-wait identity.
        retired: asyncio.Future[AwaitComplete] = asyncio.get_running_loop().create_future()

        async def retire_from_source():
            retired.set_result(history.retire_source(parked=True))

        history.reserve_source_work().schedule(history, retire_from_source)
        await (await retired)
        assert not history.state.can_draw
        history.resume_source()
        await ui.until(lambda: history.state.accepts_source_work, why="source accepts work after its own retirement")

        # Context isolation must not weaken a genuine worker self-wait.
        async def reject_self_wait():
            with pytest.raises(DeadlockError):
                await get_current_worker().wait()

        await ui.app.run_worker(reject_self_wait).wait()
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
        subscription.close()
    assert "Retain the source" in source.read_text()


async def test_unexpected_source_failure_is_shown_once_and_retires_the_history(workspace):
    from toad.widgets.comms_chat import CommsChatView

    workspace.thread("peer", "one")
    workspace.comms.messaging.send("peer", "#one", "Visible before the failed read")
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    unhandled: list[dict[str, object]] = []

    def record_unhandled(loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        unhandled.append(context)

    loop.set_exception_handler(record_unhandled)
    try:
        async with workspace.app() as ui:
            await ui.open_channel("#one", actor="peer")
            chat = ui.app.screen.query_one(CommsChatView)
            history = chat.message_history
            await ui.until(lambda: not history.undrawn and history.state.accepts_source_work,
                           why="the initial message body")
            error = RuntimeError("source read failed loudly")
            before = set(get_log().glob("*.txt"))

            async def failed_read():
                raise error

            worker = history.reserve_source_work().schedule(history, failed_read)
            await ui.until(lambda: worker.is_finished, why="the failed pager finishes")
            logs = set(get_log().glob("*.txt")) - before
            assert len(logs) == 1
            assert str(error) in next(iter(logs)).read_text()
            assert not history.state.accepts_source_work
            workspace.comms.messaging.send("peer", "#one", "A later observation must not retry")
            await ui.step(.2)
            assert set(get_log().glob("*.txt")) - before == logs
            assert worker not in ui.app.workers
            assert not history.state.accepts_source_work
        assert not unhandled
    finally:
        loop.set_exception_handler(previous_handler)
