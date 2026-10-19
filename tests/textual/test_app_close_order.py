"""Textual-facing: closing Toad closes its sessions first and the Comms observation process after them,
so a closing view's last interest reaches a live observer and the app shuts down with no trace."""

from dataclasses import replace
import json
import os

import pytest
from agent_comms.acp_extension import CoordinationChangedUpdate, encode_updates
from agent_comms.context_reading import UnmeasuredContext

from support.agents import deliver, detached
from toad.widgets.transcript_history import TranscriptHistory


@pytest.mark.filterwarnings("error::RuntimeWarning", "error::pytest.PytestUnraisableExceptionWarning")
async def test_closing_the_app_after_the_observation_process_exits_raises_nothing(workspace):
    project = workspace.project
    comms = workspace.comms
    comms.messaging.initialize_private_initial_protocol()
    saved = project / "closing-native.jsonl"
    saved.write_text(json.dumps({"type": "message", "id": "ask", "message": {
        "role": "user", "content": [{"type": "text", "text": "ASK_ROW"}]}}) + "\n")
    thread = comms.registry.declare(replace(workspace.thread("source"), session_file=str(saved)))
    workspace.thread("peer")
    comms.messaging.send_message("peer", "source", "SAVED_NOTICE")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        agent = detached(project, "closing", app=ui.app)
        view.set_reactive(type(view).agent, agent)
        view.bind_agent(agent)
        agent.coordination = CoordinationChangedUpdate(
            thread=thread.incarnation, wire_root=str(workspace.roots.wire), owner_pid=os.getpid(),
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
