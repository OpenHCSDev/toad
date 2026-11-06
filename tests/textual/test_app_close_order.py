"""Textual-facing: closing Toad closes its sessions first and the Comms observation process after them,
so a closing view's last interest reaches a live observer and the app shuts down with no trace."""

from dataclasses import replace
import json
import os

import pytest
from agent_comms.child_process import ProcessIdentity
from agent_comms.session_file import RegistrySessionLocation
from agent_comms.fresh_private_session import create_fresh_private_session

from support.agents import deliver
from support.coordination import carrying, coordination_fact
from support.ui import saved_tab
from toad.screens.main import MainScreen
from toad.widgets.transcript_history import TranscriptHistory


async def test_an_evicted_tab_retires_the_acquired_history_after_children_leave(workspace):
    """A conversation leaves its screen only by eviction, once another tab is presented."""
    async with workspace.app() as ui:
        app, _ = ui.textual
        evicted = ui.selected_tab
        owner = app.selected_session
        view = ui.conversation
        source = view.transcript.binding.history.page_source
        await app.session_navigation.new(await saved_tab(app), lambda: MainScreen(app.project_dir))
        await app.selected_session.wait_content_ready()
        await owner.presentation.evict(owner)
        await ui.step()
        # Eviction releases the native tree and unbinds the view: the source is either
        # parked for the restore or closed, never left without an owner.
        assert owner.presentation.widget is None
        assert not view.transcript.binding.matches(view)
        assert source.closed or source in owner.presentation.transcript.documents
        # Closing the tab retires whatever the eviction kept.
        await ui.close_tab(evicted)
        await ui.until(lambda: source.closed, seconds=5, why="the closed tab's history source to close")
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
        coordination = coordination_fact(
            comms, "source", owner=ProcessIdentity.capture(os.getpid()), worktree=project, model="test-model")
        await deliver(agent, carrying(coordination))
        await ui.until(lambda: "SAVED_NOTICE" in ui.painted(view.window), why="the saved history")
        assert view.contents.query(TranscriptHistory)
        observer = ui.app.coordination_access.observation.process.peer.process
    # Leaving the block closes the app: the saved history parks and states its last interest,
    # then the observation process exits.
    assert observer.exitcode == 0
