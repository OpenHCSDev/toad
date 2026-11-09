"""Textual-facing: cancelling a commit publication leaves exactly one live history widget and no stranded stream block.

Textual owns mounting, pruning and unmount of the history widgets that the publication replaces.
"""

import asyncio
import os
from dataclasses import replace

import pytest
from agent_comms.execution.child_process import ProcessIdentity
from agent_comms.execution.session_file import RegistrySessionLocation
from support import journals
from support.agents import deliver
from support.coordination import carrying, coordination_fact
from textual.worker import WorkerCancelled

from toad.live_output import ResponseStream


def saved_page(workspace, name):
    entries = []
    for i in range(6):
        entries.append(journals.assistant_entry(f"## {name} saved row {i}\n\nNative resource retirement.",
                                                id=f"{name}-{i}", parent=entries[-1]["id"] if entries else None))
    source = journals.write_journal(workspace.project / f"{name}.jsonl", *entries)
    workspace.comms.registry.declare(replace(workspace.thread(name), session_file=RegistrySessionLocation.from_path(source, workspace.comms.root)))
    return workspace.comms.transcripts.capture_page_read(name).read()


async def test_a_source_change_replaces_the_history_and_a_cancelled_commit_retires_the_covered_stream(workspace):
    """The source change retires the old history at delivery; the output lock holds only its own
    stream blocks, so a commit cancelled under it detaches the covered block once released."""
    old_page, new_page = saved_page(workspace, "old"), saved_page(workspace, "replacement")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        agent = ui.detached_agent("snapshot-cancel")
        ui.attach_agent(agent)
        owner = ProcessIdentity.capture(os.getpid())
        # The conversation owns its history: the agent coordinates a saved thread, and the
        # binding reads that thread's page as its own history.
        await deliver(agent, carrying(coordination_fact(
            workspace.comms, "old", owner=owner, worktree=workspace.project, model="test-model")))
        await ui.until(lambda: view.transcript.binding.history.page_source.through == old_page.after,
                       why="the old thread's saved page as the conversation's history")
        old = view.transcript.binding.history
        await deliver(agent, carrying(coordination_fact(
            workspace.comms, "replacement", owner=owner, worktree=workspace.project, model="test-model")))
        await ui.until(lambda: not old.is_attached and old not in view.window.histories,
                       why="the source change replacing the old history at delivery")
        agent.session.settled.set()
        # A live stream block that the saved page already covers.
        block = await view.output.append(ResponseStream(), new_page.events[0].text)
        view.window.anchor()
        view.prompt.focus()
        async with view.output.lock:
            # The transcript owner runs its own commit; a second one built here would race it.
            view.transcript.require_commit()
            await ui.until(lambda: not block.display, why="the commit withdrawing the covered block")
            # Withdrawal is synchronous; the output lock holds its own stream's teardown.
            assert block.is_attached
            # Joining retirement must not retain the source and tree locks.
            async with asyncio.timeout(5):
                async with view.window.history_lock:
                    async with view.window.lock:
                        pass
            work = view.transcript.worker
            work.cancel()
            await ui.step(0.05)
        with pytest.raises(WorkerCancelled):
            await asyncio.wait_for(work.worker.wait(), 5)
        await ui.step(0.1)
        assert len(view.window.histories) == 1, "The cancelled commit left two histories"
        assert not block.is_attached, "The covered live stream block survived retirement"
        assert ResponseStream not in view.output.streams, "The retired source kept its stream association"
