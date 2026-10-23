"""Textual-facing: closing Toad closes its sessions first and the Comms observation process after them,
so a closing view's last interest reaches a live observer and the app shuts down with no trace."""

from dataclasses import replace
import json
import os

import pytest
from agent_comms.acp_extension import CoordinationChangedUpdate, encode_updates
from agent_comms.child_process import ProcessIdentity
from agent_comms.context_reading import UnmeasuredContext
from agent_comms.session_file import RegistrySessionLocation
from agent_comms.fresh_private_session import create_fresh_private_session

from support.agents import deliver
from toad.widgets.transcript_history import TranscriptHistory


async def test_native_unmount_retires_the_acquired_history_after_children_leave(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        source = view.transcript.binding.history.page_source
        await view.remove()
        await ui.step()
        assert source.closed
        assert not view.transcript.binding.matches(view)
        assert ui.failure() is None


@pytest.mark.filterwarnings("error::RuntimeWarning", "error::pytest.PytestUnraisableExceptionWarning")
async def test_closing_the_app_after_the_observation_process_exits_raises_nothing(workspace):
    project = workspace.project
    comms = workspace.comms
    saved = create_fresh_private_session(project / "sessions", worktree=project).path
    with saved.open("a") as stream:
        stream.write(json.dumps({"type": "message", "id": "ask",
            "timestamp": "2026-10-22T00:00:00Z", "message": {
        "role": "user", "content": [{"type": "text", "text": "ASK_ROW"}]}}) + "\n")
    thread = comms.registry.declare(replace(workspace.thread("source"), session_file=RegistrySessionLocation.from_path(str(saved), workspace.comms.root)))
    workspace.thread("peer")
    comms.messaging.send("peer", "source", "SAVED_NOTICE")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        agent = ui.detached_agent("closing")
        view.bind_agent(agent)
        agent.coordination = CoordinationChangedUpdate(
            thread=thread.incarnation, wire_root=str(workspace.roots.wire), owner=ProcessIdentity.capture(os.getpid()),
            worktree=str(project), model="test-model", thinking_level=None, title=thread.name,
            context_usage=UnmeasuredContext())
        await deliver(agent, {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": encode_updates(agent.coordination)})
        await ui.until(lambda: "SAVED_NOTICE" in ui.painted(view.window), why="the saved history")
        assert view.contents.query(TranscriptHistory)
        observer = ui.app.coordination_access.observation.process.process
    # Leaving the block closes the app: the saved history parks and states its last interest,
    # then the observation process exits.
    assert observer.exitcode == 0
