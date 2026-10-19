"""Textual-facing: transcript presentations queue behind Textual's callback pump and paint into the conversation window."""

import asyncio

from support.coordination import registered_coordination_fact
from support.journals import assistant_entry, write_journal
from toad.transcript_publication import CanonicalSourcePublication, TranscriptPublication
from toad.widgets.agent_response import AgentResponse


class DeclaredCase(TranscriptPublication):
    """A newly declared case: it paints one response, unless it is no longer current."""

    def __init__(self, owner, view, window, contents, entered, release):
        super().__init__(owner, view, window, contents)
        self.entered, self.release = entered, release

    async def publish_applied(self):
        self.entered.set()
        await self.release.wait()
        if self.current():
            await self.contents.mount(AgentResponse("Declared case painted"))
        return True


class HeldSourceCase(CanonicalSourcePublication):
    """A real certified read, held before its application is joined."""

    def __init__(self, owner, view, window, contents, entered, release):
        super().__init__(owner, view, window, contents)
        self.entered, self.release = entered, release

    async def read_page(self):
        page = await super().read_page()
        self.entered.set()
        await self.release.wait()
        return page


async def settle_ready(ui):
    await ui.app.screen.prepare_navigation()
    await ui.app.screen.layout_navigation()


async def hold_application(ui, view):
    """Occupy the view's callback pump until the returned event is set."""
    started, release = asyncio.Event(), asyncio.Event()

    async def held():
        started.set()
        await release.wait()

    view.call_later(held)
    # The pump is busy once the callback runs, so the pilot cannot step: wait on the event itself.
    await asyncio.wait_for(started.wait(), 10)
    return release


async def stays_waiting(task) -> bool:
    """Whether `task` is still unfinished after the loop had time to run it (the pump is held)."""
    done, _ = await asyncio.wait({task}, timeout=0.03)
    return not done


async def finish(ui, task, why):
    await ui.until(task.done, why=why)
    return await task


async def test_a_case_queued_behind_the_pump_does_not_adopt_a_replacement_generation(workspace):
    async with workspace.app() as ui:
        await settle_ready(ui)
        view = ui.conversation
        release_pump = await hold_application(ui, view)
        entered, release = asyncio.Event(), asyncio.Event()
        release.set()
        case = view.transcript.capture(DeclaredCase, entered, release)
        pending = asyncio.create_task(case.publish())
        assert await stays_waiting(pending) and not entered.is_set()
        view.transcript.invalidate()
        release_pump.set()
        await finish(ui, pending, "the queued case to return")
        assert not entered.is_set()


async def test_cancelling_a_waiting_caller_leaves_the_pump_and_runs_nothing(workspace):
    async with workspace.app() as ui:
        await settle_ready(ui)
        view = ui.conversation
        release_pump = await hold_application(ui, view)
        entered, release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(view.transcript.publish(DeclaredCase, entered, release))
        assert await stays_waiting(pending)
        pending.cancel()
        result = await asyncio.gather(pending, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert not entered.is_set() and not view.task.done()
        release_pump.set()
        await ui.step()


async def test_a_case_invalidated_while_applying_paints_nothing_and_the_next_one_paints(workspace):
    async with workspace.app() as ui:
        await settle_ready(ui)
        view = ui.conversation
        entered, release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(view.transcript.publish(DeclaredCase, entered, release))
        await ui.until(entered.is_set, why="the case to start applying")
        view.transcript.invalidate()
        release.set()
        await finish(ui, pending, "the invalidated case to return")
        assert not view.contents.query(AgentResponse)
        await view.transcript.publish(DeclaredCase, entered, release)
        await ui.until(lambda: "Declared case painted" in ui.painted(view.window), why="the declared case painted in the window")


async def test_a_pending_request_does_not_paint_a_replacement_source(workspace):
    async with workspace.app() as ui:
        await settle_ready(ui)
        view = ui.conversation
        requests = view.transcript.source_requests
        entered, release = asyncio.Event(), asyncio.Event()
        requests.request(DeclaredCase, entered, release)
        await ui.until(entered.is_set, why="the running request to start")
        queued_entered, queued_release = asyncio.Event(), asyncio.Event()
        queued_release.set()
        requests.request(DeclaredCase, queued_entered, queued_release)
        view.transcript.invalidate()
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
    from agent_comms.threads import Thread
    workspace.comms.registry.declare(Thread("journal-source", frozenset(), str(workspace.project), session_file=str(journal)))
    async with workspace.app() as ui:
        await settle_ready(ui)
        view = ui.conversation
        agent = ui.detached_agent("journal-source")
        agent.coordination = registered_coordination_fact(workspace.comms, "journal-source", worktree=str(workspace.project))
        view.agent = agent
        entered, release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(view.transcript.publish(HeldSourceCase, entered, release))
        await ui.until(entered.is_set, why="the certified read to be held")
        view.transcript.invalidate()
        release.set()
        await finish(ui, pending, "the expired read to return")
        assert not view.transcript.histories, "Expired read acquired a replacement application"
        await view.transcript.publish(HeldSourceCase, entered, release)
        await ui.until(lambda: len(view.transcript.histories) == 1, why="the current read to acquire its application")
        assert view.transcript.histories[0].page_source.through.session_file == str(journal)


async def test_closing_the_transcript_mid_application_paints_nothing(workspace):
    async with workspace.app() as ui:
        await settle_ready(ui)
        view = ui.conversation
        entered, release = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(view.transcript.publish(DeclaredCase, entered, release))
        await ui.until(entered.is_set, why="the case to start applying")
        await view.transcript.close()
        release.set()
        await finish(ui, pending, "the case to return after close")
        assert not view.contents.query(AgentResponse)
        assert view.transcript.view is None
