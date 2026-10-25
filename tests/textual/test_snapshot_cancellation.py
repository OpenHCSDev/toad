"""Textual-facing: cancelling a commit publication leaves exactly one live history widget and no stranded stream block.

Textual owns mounting, pruning and unmount of the history widgets that the publication replaces.
"""

from agent_comms.session_file import RegistrySessionLocation
import asyncio
from dataclasses import replace
import os
from unittest.mock import patch

from agent_comms.acp_extension import CoordinationChangedUpdate
import pytest
from textual.worker import WorkerCancelled

from support import journals
from toad.live_output import ResponseStream
from support.textual_steps import saved_history


def saved_page(workspace, name):
    entries = []
    for i in range(6):
        entries.append(journals.assistant_entry(f"## {name} saved row {i}\n\nNative resource retirement.",
                                                id=f"{name}-{i}", parent=entries[-1]["id"] if entries else None))
    source = journals.write_journal(workspace.project / f"{name}.jsonl", *entries)
    workspace.comms.registry.declare(replace(workspace.thread(name), session_file=RegistrySessionLocation.from_path(source, workspace.comms.root)))
    return workspace.comms.transcripts.capture_page_read(name).read()


async def test_cancelled_commit_with_the_output_owner_busy_retires_the_old_history_and_covered_stream(workspace):
    """Cancel an accepted commit while the live output owner is held."""
    old_page, new_page = saved_page(workspace, "old"), saved_page(workspace, "replacement")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        agent = ui.detached_agent()
        ui.attach_agent(agent)
        old = await saved_history(view, old_page, view.transcript.get_transcript_page)
        await view.contents.mount(old)
        await ui.until(lambda: old in view.window.histories, why="the old history")
        thread = workspace.comms.registry.require("replacement")
        agent.coordination = CoordinationChangedUpdate(
            thread.incarnation, str(workspace.roots.wire), os.getpid(), str(workspace.project),
            None, None, thread.name, None)
        agent.session.settled.set()
        # A live stream block that the saved page already covers.
        block = await view.output.append(ResponseStream(), new_page.events[0].text)
        view.window.anchor()
        view.prompt.focus()
        entered = asyncio.Event()
        retire = view.output.retire_presentations
        covered = {}

        async def observe_retirement(candidates):
            covered["old"] = old in candidates
            covered["stream"] = block in candidates
            entered.set()
            await retire(candidates)

        with patch.object(view.output, "retire_presentations", observe_retirement):
            async with view.output.lock:
                # The transcript owner runs its own commit; a second one built here would race it.
                view.transcript.require_commit()
                await asyncio.wait_for(entered.wait(), 5)
                # While the output owner is held, finishing must still be able to take the source and tree locks.
                async with asyncio.timeout(5):
                    async with view.window.history_lock:
                        async with view.window.lock:
                            pass
                assert not old.display
                # The owner may have restarted its commit; the one retiring now is its current worker.
                worker = view.transcript.worker
                worker.cancel()
                await ui.step(0.05)
            with pytest.raises(WorkerCancelled):
                await asyncio.wait_for(worker.wait(), 5)
            await ui.step(0.1)
        assert covered["old"], "The source did not cover the old history"
        assert covered["stream"], "Source did not cover the live stream"
        assert not old.is_attached, "Accepted cancellation abandoned the old history"
        assert old not in view.window.histories, "Accepted cancellation kept two histories"
        assert not block.is_attached, "The covered live stream block survived retirement"
        assert ResponseStream not in view.output.streams, "The retired source kept its stream association"
