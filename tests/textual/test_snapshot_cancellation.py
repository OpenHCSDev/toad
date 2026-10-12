"""Textual-facing: cancelling a snapshot or checkpoint publication leaves exactly one live history widget and no stranded stream block.

Textual owns mounting, pruning and unmount of the history widgets that the publication replaces.
"""

import asyncio
import os
from unittest.mock import patch

from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.threads import Thread
import pytest
from textual.await_complete import AwaitComplete
from textual.worker import WorkerCancelled

from support import agents, journals
from toad.live_output import ResponseStream
from toad.transcript_publication import SnapshotPublication
from toad.widgets.transcript_history import TranscriptHistory


def saved_page(workspace, name):
    entries = []
    for i in range(6):
        entries.append(journals.assistant_entry(f"## {name} saved row {i}\n\nNative resource retirement.",
                                                id=f"{name}-{i}", parent=entries[-1]["id"] if entries else None))
    source = journals.write_journal(workspace.project / f"{name}.jsonl", *entries)
    workspace.comms.registry.declare(Thread(name, frozenset(), str(workspace.project), session_file=str(source)))
    return workspace.comms.transcripts.thread_transcript_page(name)


async def cancelled(task):
    task.cancel()
    result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
    assert isinstance(result[0], asyncio.CancelledError), result


async def test_cancelling_before_the_new_history_is_accepted_removes_it_and_keeps_the_old_one(workspace):
    old_page, new_page = saved_page(workspace, "old"), saved_page(workspace, "replacement")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        ui.attach_agent(agents.detached(workspace.project))
        old = TranscriptHistory(old_page)
        await view.contents.mount(old)
        await ui.until(lambda: old in view.window.histories and old.state.reports_coverage, why="the old history")
        entered, release = asyncio.Event(), asyncio.Event()
        mount = view.contents.mount

        def held_mount(*widgets, **kwargs):
            actual = mount(*widgets, **kwargs)

            async def wait():
                await actual
                entered.set()
                await release.wait()

            return AwaitComplete(wait())

        # The native mount has completed, but the publication has not accepted it.
        with patch.object(view.contents, "mount", held_mount):
            task = asyncio.create_task(SnapshotPublication(
                view.transcript, view, view.window, view.contents, new_page).publish())
            try:
                await asyncio.wait_for(entered.wait(), 5)
                provisional = next(h for h in view.window.histories if h is not old)
                assert provisional.is_attached and not provisional.state.reports_coverage
                await cancelled(task)
                assert not provisional.is_attached and provisional not in view.window.histories
                assert old.is_attached and old in view.window.histories
            finally:
                release.set()
                if not task.done():
                    await cancelled(task)


async def test_cancelling_after_acceptance_still_finishes_retiring_the_old_history(workspace):
    old_page, new_page = saved_page(workspace, "old"), saved_page(workspace, "replacement")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        ui.attach_agent(agents.detached(workspace.project))
        old = TranscriptHistory(old_page)
        await view.contents.mount(old)
        await ui.until(lambda: old in view.window.histories, why="the old history")
        entered, release = asyncio.Event(), asyncio.Event()
        unmount = TranscriptHistory.on_unmount

        async def held_unmount(history):
            if history is old:
                entered.set()
                await release.wait()
            unmount(history)

        # Hold the old history's own Unmount handler: Prune is admitted before the caller reaches its await.
        with patch.object(TranscriptHistory, "on_unmount", held_unmount):
            task = asyncio.create_task(SnapshotPublication(
                view.transcript, view, view.window, view.contents, new_page).publish())
            try:
                await asyncio.wait_for(entered.wait(), 5)
                accepted = next(h for h in view.window.histories if h is not old)
                assert accepted.is_attached and accepted.state.reports_coverage
                assert not old.state.can_draw
                task.cancel()
                await ui.step(0.05)
                assert accepted.is_attached and accepted in view.window.histories
                # Teardown stays pending until the old history completes Unmount.
                release.set()
                result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
                assert isinstance(result[0], asyncio.CancelledError), result
                await ui.until(lambda: not old.is_attached and old not in view.window.histories,
                               why="the old history retired")
                assert set(view.window.histories) == {accepted}
                assert list(view.contents.query(TranscriptHistory)) == [accepted]
            finally:
                release.set()
                if not task.done():
                    await cancelled(task)


async def retire_while_output_is_busy(workspace, *, checkpoint):
    """Cancel an accepted publication while the live output owner is held; return what is left afterwards."""
    old_page, new_page = saved_page(workspace, "old"), saved_page(workspace, "replacement")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        agent = agents.detached(workspace.project)
        ui.attach_agent(agent)
        old = TranscriptHistory(old_page)
        await view.contents.mount(old)
        await ui.until(lambda: old in view.window.histories, why="the old history")
        block = None
        if checkpoint:
            thread = workspace.comms.registry.require("replacement")
            agent.coordination = CoordinationChangedUpdate(
                thread.incarnation, str(workspace.roots.wire), os.getpid(), str(workspace.project),
                None, None, thread.name, None)
            view.set_reactive(type(view).agent_ready, True)
            # A live stream block that the saved page already covers.
            block = await view.output.append(ResponseStream(), new_page.events[0].text)
            view.window.anchor()
            view.prompt.focus()
        entered = asyncio.Event()
        retire = view.output.retire_presentations
        covered = {}

        async def observe_retirement(candidates):
            covered["old"] = old in candidates
            if checkpoint:
                covered["stream"] = block in candidates
            entered.set()
            await retire(candidates)

        task = worker = None
        try:
            with patch.object(view.output, "retire_presentations", observe_retirement):
                async with view.output.lock:
                    if checkpoint:
                        # The transcript owner runs its own checkpoint; a second one built here would race it.
                        view.transcript.require_checkpoint()
                    else:
                        task = asyncio.create_task(SnapshotPublication(
                            view.transcript, view, view.window, view.contents, new_page).publish())
                    await asyncio.wait_for(entered.wait(), 5)
                    # While the output owner is held, finishing must still be able to take the source and tree locks.
                    async with asyncio.timeout(5):
                        async with view.window.history_lock:
                            async with view.window.lock:
                                pass
                    assert not old.display
                    if checkpoint:
                        # The owner may have restarted its checkpoint; the one retiring now is its current worker.
                        worker = view.transcript.worker
                    (worker or task).cancel()
                    await ui.step(0.05)
                if checkpoint:
                    with pytest.raises(WorkerCancelled):
                        await asyncio.wait_for(worker.wait(), 5)
                else:
                    result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
                    assert isinstance(result[0], asyncio.CancelledError), result
                await ui.step(0.1)
                assert covered["old"], "The source did not cover the old history"
                if checkpoint:
                    assert covered["stream"], "Source did not cover the live stream"
                return dict(old_attached=old.is_attached, old_registered=old in view.window.histories,
                            stream_attached=block.is_attached if checkpoint else None,
                            stream_kept=ResponseStream in view.output.streams)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_cancelled_snapshot_with_the_output_owner_busy_still_retires_the_old_history(workspace):
    left = await retire_while_output_is_busy(workspace, checkpoint=False)
    assert not left["old_attached"], "Accepted cancellation abandoned the old history"
    assert not left["old_registered"], "Accepted cancellation kept two histories"


async def test_cancelled_checkpoint_with_the_output_owner_busy_retires_the_old_history_and_covered_stream(workspace):
    left = await retire_while_output_is_busy(workspace, checkpoint=True)
    assert not left["old_attached"], "Accepted cancellation abandoned the old history"
    assert not left["old_registered"], "Accepted cancellation kept two histories"
    assert not left["stream_attached"], "The covered live stream block survived retirement"
    assert not left["stream_kept"], "The retired source kept its stream association"
