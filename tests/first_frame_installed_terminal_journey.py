"""Real Linux terminal writes, first-frame ACP startup and physical input flow."""
import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from e2e_pty import PtyLaunch, ToadSession


async def until(predicate, session, seconds=15):
    async with asyncio.timeout(seconds):
        while not predicate():
            assert session.alive(), "Actual terminal app exited before acceptance"
            await asyncio.sleep(.05)


async def main():
    receipt = Path(os.environ["Q7_EVIDENCE"])
    receipt.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="frame-terminal-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        env = dict(os.environ, AGENT_COMMS_ROOT=str(root / "wire"),
                   XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                   XDG_DATA_HOME=str(root / "data"), TOAD_TEST_ATTEMPT=root.name)
        for name in ("AGENT_COMMS_THREAD", "PI_AGENT_ID", "PI_PROMPT", "TOAD_RENDERER", "PYTHONPATH"):
            env.pop(name, None)
        command = (sys.executable, str(Path(__file__).with_name("first_frame_terminal_app.py")), str(root))
        terminal = ToadSession(PtyLaunch(command, root, env))
        try:
            await terminal.start()
            wire_path = root / "completion-wire.jsonl"
            await until(wire_path.exists, terminal)
            first = json.loads(wire_path.read_text().splitlines()[0])
            assert first["new_session_after_frame"]["time_ns"] < first["peer_time_ns"], first
            assert first["new_session_after_frame"]["ready"]
            assert first["new_session_after_frame"]["driver"] == "LinuxDriver"
            assert len(terminal.buffer) or "Physical" in terminal._screen()
            await terminal.type_text("PTY_FIRST_FRAME_INPUT")
            await terminal.press_enter()
            await until(lambda: "COMPLETION_PEER_EXECUTED PTY_FIRST_FRAME_INPUT" in terminal._screen(), terminal)
            await terminal.type_text("/")
            await until(lambda: "Physical ACP completion command" in terminal._screen(), terminal)
            await terminal.type_text("proof")
            await terminal.press_enter()
            await until(lambda: "/proofcmd" in terminal._screen(), terminal)
            await terminal.press_enter()
            await until(lambda: "COMPLETION_PEER_EXECUTED /proofcmd" in terminal._screen(), terminal)
            terminal._set_size(32, 105)
            await until(lambda: "COMPLETION_PEER_EXECUTED /proofcmd" in terminal._screen(), terminal)
            terminal._set_size(40, 120)
            await terminal.type_text("Reader draft after terminal resize")
            await until(lambda: "Reader draft after terminal resize" in terminal._screen(), terminal)
            (receipt / "terminal-visible.txt").write_text(terminal._screen())
            (receipt / "terminal-wire.jsonl").write_text(wire_path.read_text())
            (receipt / "terminal-frames.jsonl").write_text((root / "frames.jsonl").read_text())
            await terminal.send(b"\x11")
            await asyncio.wait_for(terminal.proc.wait(), 6)
            assert terminal.proc.returncode == 0, terminal._screen()
            assert "Traceback" not in terminal.buffer.decode("utf-8", "replace")
            rows = list(map(json.loads, wire_path.read_text().splitlines()))
            assert [row["prompt"] for row in rows if "prompt" in row] == ["PTY_FIRST_FRAME_INPUT", "/proofcmd"]
            print("INSTALLED_LINUX_WRITER_FLUSH_BEFORE_ACP_START_PHYSICAL_FIRST_INPUT_SLASH_REPLY_RESIZE_DRAFT_AND_CLOSE_PASS", flush=True)
        finally:
            terminal._drain()
            (receipt / "terminal-output.txt").write_bytes(terminal.buffer)
            await terminal.stop()


if __name__ == "__main__":
    asyncio.run(main())
