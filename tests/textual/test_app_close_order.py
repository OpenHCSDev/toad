"""Textual-facing: closing Toad closes its sessions first and the Comms observation process after them,
so a closing view's last interest reaches a live observer and the app shuts down with no trace."""

from dataclasses import replace
import json

import pytest

from toad.widgets.transcript_history import TranscriptHistory


@pytest.mark.filterwarnings("error")
async def test_closing_the_app_after_the_observation_process_exits_raises_nothing(workspace):
    project = workspace.project
    comms = workspace.comms
    comms.messaging.initialize_private_initial_protocol()
    saved = project / "closing-native.jsonl"
    saved.write_text(json.dumps({"type": "message", "id": "ask", "message": {
        "role": "user", "content": [{"type": "text", "text": "ASK_ROW"}]}}) + "\n")
    comms.registry.declare(replace(workspace.thread("source"), session_file=str(saved)))
    workspace.thread("peer")
    comms.messaging.send_message("peer", "source", "SAVED_NOTICE")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        await ui.until(lambda: "SAVED_NOTICE" in ui.painted(view.window), why="the saved history")
        assert view.contents.query(TranscriptHistory)
        observer = ui.app.coordination_access.observation.process.process
    # Leaving the block closes the app: the saved history parks and states its last interest,
    # then the observation process exits.
    assert observer.exitcode == 0
