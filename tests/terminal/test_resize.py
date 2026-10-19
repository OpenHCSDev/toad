"""Toad repaints its transcript, sidebar and composer across large terminal size changes."""

import sys

from support.journals import assistant_entry, write_journal
from support.terminal import native_wire_environment, terminal_running, toad_command


async def test_every_terminal_resize_repaints_transcript_sidebar_and_composer(
        workspace, terminal_emulator, native_package):

    journal = write_journal(workspace.project / "session.jsonl", *(
        assistant_entry(f"REPLAY_MARKER_{i}\n\n" + "A paragraph to wrap. " * 100, id=f"a{i}",
                        parent=f"a{i - 1}" if i else None) for i in range(40)))
    environment = native_wire_environment(workspace, native_package) | {
        "AGENT_COMMS_AGENT_BIN": "pi", "AGENT_COMMS_AGENT_MODELS": "test/model",
        "AGENT_COMMS_AGENT_ARGS": "--model test/model"}
    workspace.comms.registry.declare(workspace.comms.registry.new_thread(
        "resize", frozenset(), str(workspace.project), session_file=str(journal)))
    command = toad_command("acp", f"{sys.executable} -m agent_comms.acp", "--session", "resize")
    async with terminal_running(workspace, terminal_emulator, command, environment=environment) as terminal:
        await terminal.until(lambda: terminal.shows("A paragraph") or terminal.shows("REPLAY_MARKER_39"),
                             seconds=30, why="the saved transcript")
        for rows, columns in ((25, 70), (28, 145), (25, 70), (50, 180), (35, 95), (25, 70)):
            await terminal.resize(rows, columns)
            await terminal.until(
                lambda: (terminal.shows("A paragraph") or terminal.shows("REPLAY_MARKER_39"))
                and terminal.shows("Channels") and terminal.shows("❯"),
                why=f"transcript, sidebar and composer at {columns}x{rows}")
            assert terminal.returncode is None
