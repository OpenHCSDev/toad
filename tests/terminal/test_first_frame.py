"""Toad in a real terminal: the first frame is written before the agent starts, then typing, a slash command, resize and quit work."""

import json
from pathlib import Path

from support.terminal import terminal_running

APP = Path(__file__).parents[1] / "support" / "first_frame_app.py"


async def test_first_frame_is_written_before_the_agent_starts_and_input_works_through_quit(
        workspace, terminal_emulator):
    import sys

    project = workspace.project
    wire_path = project / "completion-wire.jsonl"

    def ui():
        return json.loads((project / "current-ui.json").read_text())

    async with terminal_running(workspace, terminal_emulator, (sys.executable, str(APP), str(project))) as terminal:
        # Toad starts with no tab open; Enter on the welcome view's New Session starts the agent.
        await terminal.until_shows("New Session")
        assert not wire_path.exists()
        await terminal.send("\r")
        await terminal.until(wire_path.exists, why="the agent to start")
        first = json.loads(wire_path.read_text().splitlines()[0])
        assert first["new_session_after_frame"]["time_ns"] < first["peer_time_ns"], first
        assert first["new_session_after_frame"]["ready"]
        assert first["new_session_after_frame"]["driver"] == "LinuxDriver"
        assert terminal.output and terminal.shows("New Session"), terminal.text()
        await terminal.until(lambda: ui()["agent_ready"], why="the agent to accept input")
        await terminal.send("PTY_FIRST_FRAME_INPUT")
        await terminal.send("\r")
        await terminal.until_shows("COMPLETION_PEER_EXECUTED PTY_FIRST_FRAME_INPUT")
        await terminal.send("/")
        await terminal.until(lambda: ui()["slash_focused"], why="the slash popup to take focus")
        await terminal.until_shows("Physical ACP completion command")
        await terminal.send("proof")
        await terminal.until(lambda: ui()["slash_query"] == "proof", why="the typed slash query")
        await terminal.send("\r")

        def completion_returned():
            state = ui()
            return state["editor_focused"] and state["text"] == "/proofcmd " and not state["slash_open"]

        await terminal.until(completion_returned, why="the completion to return to the editor")
        await terminal.until_shows("/proofcmd")
        await terminal.send("\r")
        await terminal.until_shows("COMPLETION_PEER_EXECUTED /proofcmd")
        await terminal.resize(32, 105)
        await terminal.until_shows("COMPLETION_PEER_EXECUTED /proofcmd")
        await terminal.resize(40, 120)
        await terminal.send("Reader draft after terminal resize")
        await terminal.until_shows("Reader draft after terminal resize")
        await terminal.send(b"\x11")
        assert await terminal.until_exit(seconds=6) == 0, terminal.text()
        assert "Traceback" not in terminal.output.decode("utf-8", "replace")
        rows = [json.loads(line) for line in wire_path.read_text().splitlines()]
        assert [row["prompt"] for row in rows if "prompt" in row] == ["PTY_FIRST_FRAME_INPUT", "/proofcmd"]
